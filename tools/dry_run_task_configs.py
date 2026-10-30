"""
tools/dry_run_task_configs.py: 离线静态 dry-run 验证现有任务配置能否合法编译为 PulseFlow ExecutionGraph
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("dry_run_task_configs")


def run_dry_run_scan(signs_dir: Optional[str | Path] = None) -> Dict[str, Any]:
    """遍历 signs_dir 下所有任务配置，纯离线执行 ExecutionGraph.compile(config) 并收集拓扑校验报告。"""
    from tg_signer.core.flow_models import ExecutionGraph

    if signs_dir is None:
        candidate_paths = [
            Path("data/signs"),
            Path("/data/home/Projects/TG-SignPulse/data/signs"),
            Path("signs"),
        ]
        chosen = None
        for p in candidate_paths:
            if p.exists() and p.is_dir():
                chosen = p
                break
        if chosen is None:
            signs_path = Path("data/signs")
        else:
            signs_path = chosen
    else:
        signs_path = Path(signs_dir)

    report = {
        "signs_dir": str(signs_path),
        "scanned_files": 0,
        "chats_compiled": 0,
        "failed_count": 0,
        "success_count": 0,
        "errors": [],
    }

    if not signs_path.exists():
        return report

    config_files: List[Path] = []
    for root, _, files in os.walk(signs_path):
        for f in files:
            if f == "config.json":
                config_files.append(Path(root) / f)

    report["scanned_files"] = len(config_files)

    for cfg_path in config_files:
        try:
            with open(cfg_path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
        except Exception as e:
            report["failed_count"] += 1
            report["errors"].append(
                {"file": str(cfg_path), "error": f"JSON parse error: {e}"}
            )
            continue

        chats = data.get("chats") if isinstance(data, dict) else None
        if isinstance(chats, list) and chats:
            for i, chat in enumerate(chats):
                try:
                    graph = ExecutionGraph.compile(chat)
                    if not graph.nodes:
                        raise ValueError(
                            f"Compiled ExecutionGraph has no nodes for chat {i}"
                        )
                    report["chats_compiled"] += 1
                    report["success_count"] += 1
                except Exception as e:
                    report["failed_count"] += 1
                    report["errors"].append(
                        {
                            "file": str(cfg_path),
                            "chat_index": i,
                            "error": f"Compile error: {e}",
                        }
                    )
        else:
            try:
                graph = ExecutionGraph.compile(data)
                if not graph.nodes:
                    raise ValueError("Compiled ExecutionGraph has no nodes")
                report["chats_compiled"] += 1
                report["success_count"] += 1
            except Exception as e:
                report["failed_count"] += 1
                report["errors"].append(
                    {"file": str(cfg_path), "error": f"Compile error: {e}"}
                )

    return report


def main() -> int:
    signs_arg = sys.argv[1] if len(sys.argv) > 1 else None
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )
    logger.info("开始执行任务配置离线 Dry-Run 校验...")
    res = run_dry_run_scan(signs_arg)
    logger.info(
        f"扫描完成: 目录={res['signs_dir']}, 配置文件数={res['scanned_files']}, "
        f"编译成功数={res['success_count']}, 失败数={res['failed_count']}"
    )
    if res["failed_count"] > 0:
        logger.error(f"发现 {res['failed_count']} 处配置编译失败:")
        for err in res["errors"]:
            logger.error(f" - {err}")
        return 1
    logger.info("全部任务配置均成功编译为 PulseFlow ExecutionGraph。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""将 telegram / keyword_monitor 大文件转为 package（runtime + 职责模块骨架）。"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "backend" / "services"


def package_service(module_name: str, class_anchors: list[str]) -> None:
    src = SERVICES / f"{module_name}.py"
    pkg = SERVICES / module_name
    if not src.exists():
        if (pkg / "runtime.py").exists():
            print(f"{module_name}: already packaged")
            return
        raise SystemExit(f"missing {src}")

    text = src.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    if pkg.exists():
        shutil.rmtree(pkg)
    pkg.mkdir()

    (pkg / "runtime.py").write_text(text, encoding="utf-8")

    # 按锚点粗切模块文件，便于后续渐进迁移（对外仍走 runtime）
    indices = []
    for anchor in class_anchors:
        for i, line in enumerate(lines):
            if anchor in line:
                indices.append((i, anchor))
                break
    indices.sort()

    # 写出 markers 文档
    marks = "\n".join(f"- L{i+1}: {a}" for i, a in indices)
    (pkg / "STRUCTURE.md").write_text(
        f"# {module_name} 拆分说明\n\n"
        f"当前 `runtime.py` 为完整实现（行为与原 `{module_name}.py` 一致）。\n"
        f"下列锚点供继续按职责迁出：\n\n{marks}\n",
        encoding="utf-8",
    )

    (pkg / "__init__.py").write_text(
        f'"""backend.services.{module_name} 包（自 {module_name}.py 拆分）。\n\n'
        f"完整实现位于 runtime；对外 API 与原先模块级导入保持兼容。\n"
        f'"""\n'
        f"from backend.services.{module_name}.runtime import *  # noqa: F403\n",
        encoding="utf-8",
    )
    src.unlink()
    print(f"packaged backend.services.{module_name} ({len(lines)} lines)")


def main() -> None:
    package_service(
        "telegram",
        [
            "class TelegramService",
            "async def start_login",
            "async def verify_login",
            "async def start_qr_login",
            "async def get_qr_login_status",
            "async def list_account_devices",
            "async def check_account_status",
            "async def rename_account",
            "async def delete_account",
        ],
    )
    package_service(
        "keyword_monitor",
        [
            "class TerminalAIActionError",
            "class KeywordMonitorRule",
            "class KeywordMonitorService",
            "async def _execute_ai_action",
            "async def restart_from_tasks",
            "def get_keyword_monitor_service",
        ],
    )


if __name__ == "__main__":
    main()

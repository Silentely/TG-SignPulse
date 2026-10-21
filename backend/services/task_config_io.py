from __future__ import annotations

import copy
import logging
import os
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable

from tg_signer.atomic_io import path_write_lock, read_json_safe, write_json_atomic
from tg_signer.semantic.models import config_revision

logger = logging.getLogger("backend.services.task_config_io")


class TaskConfigConflict(ValueError):
    """任务配置版本冲突（被并发修改或 revision 不匹配）"""

    pass


@contextmanager
def locked_task_paths(paths: Iterable[Path]):
    """按规范绝对路径字典序加锁，防止多路径操作死锁 (Deadlock Prevention)"""
    clean_paths = sorted({Path(p).resolve() for p in paths})
    locks = [path_write_lock(p) for p in clean_paths]
    with ExitStack() as stack:
        for lk in locks:
            stack.enter_context(lk)
        yield


def create_task_config(
    path: Path,
    config: dict[str, Any],
    *,
    validate: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    """在锁保护下原子创建任务配置，若已存在抛出 FileExistsError"""
    p = Path(path).resolve()
    with path_write_lock(p):
        if p.exists():
            raise FileExistsError(f"TASK_CONFIG_ALREADY_EXISTS: {p}")
        validate(config)
        write_json_atomic(p, config)
        return config


def update_task_config(
    path: Path,
    transform: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    validate: Callable[[dict[str, Any]], None],
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """在锁保护下执行读取-核对-修改-校验-原子写入事务 (Compare-and-Write Transaction)"""
    p = Path(path).resolve()
    with path_write_lock(p):
        if not p.exists():
            raise FileNotFoundError(f"TASK_CONFIG_NOT_FOUND: {p}")

        raw = read_json_safe(p)
        if not isinstance(raw, dict):
            raise ValueError(f"TASK_CONFIG_CORRUPTED: {p}")

        current = raw
        if expected_revision is not None:
            actual_rev = config_revision(current)
            if actual_rev != expected_revision:
                raise TaskConfigConflict(
                    f"TASK_CONFIG_CHANGED: expected revision {expected_revision}, got {actual_rev}"
                )

        updated = transform(copy.deepcopy(current))
        if "last_run" in current and "last_run" not in updated:
            updated["last_run"] = current["last_run"]
        validate(updated)
        write_json_atomic(p, updated)
        return updated


def verify_single_writer_environment() -> None:
    """单写环境自检守卫：检查是否存在多 worker 配置并发出醒目告警"""
    concurrency_keys = (
        "WEB_CONCURRENCY",
        "UVICORN_WORKERS",
        "GUNICORN_WORKERS",
        "WORKERS",
    )
    multi_worker_detected = False
    details = []

    for k in concurrency_keys:
        val = os.getenv(k, "").strip()
        if val.isdigit() and int(val) > 1:
            multi_worker_detected = True
            details.append(f"{k}={val}")

    if multi_worker_detected:
        warn_msg = (
            f"⚠️ [单写进程架构警报] 检测到并发 Worker 配置 ({', '.join(details)})！"
            "TG-SignPulse 采用单写进程原子部署模型，任务配置锁为进程内互斥锁 (RLock)；"
            "多 Worker/多副本进程会导致文件修改状态竞争与冲突，请务必保持单 Worker (WEB_CONCURRENCY=1)。"
        )
        logger.warning(warn_msg)

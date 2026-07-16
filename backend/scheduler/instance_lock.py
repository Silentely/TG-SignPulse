"""
进程级调度锁

多实例挂载同一 data 目录时，仅持有锁的进程执行 APScheduler 业务 job，
避免重复签到。Telegram 长连接监听仍不建议多实例共享同一 session。
"""
from __future__ import annotations

import atexit
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("backend.scheduler.lock")

_lock = None
_held = False


def _lock_path() -> Path:
    from backend.core.config import get_settings

    base = get_settings().resolve_base_dir()
    base.mkdir(parents=True, exist_ok=True)
    return base / ".scheduler.lock"


def try_acquire_scheduler_lock() -> bool:
    """
    尝试获取调度锁。

    - APP_SCHEDULER_LOCK=0 时跳过（单实例开发默认也可不设）
    - 默认开启文件锁（filelock）
    - 同进程已持有时直接返回 True（测试/热重载可重入）
    """
    global _lock, _held
    if _held:
        return True
    if os.getenv("APP_SCHEDULER_LOCK", "1").strip() in {"0", "false", "False", "no"}:
        _held = True
        logger.info("调度锁已禁用 (APP_SCHEDULER_LOCK=0)，本进程将调度任务")
        return True

    try:
        from filelock import FileLock, Timeout
    except ImportError:  # pragma: no cover
        logger.warning("filelock 不可用，跳过调度锁")
        _held = True
        return True

    path = _lock_path()
    if _lock is None:
        _lock = FileLock(str(path), timeout=0)
    try:
        _lock.acquire(timeout=0)
        _held = True
        atexit.register(release_scheduler_lock)
        logger.info("已获取调度锁: %s", path)
        return True
    except Timeout:
        _held = False
        logger.warning(
            "未能获取调度锁 %s，本进程将跳过业务调度（仅适合只读/API 副本）",
            path,
        )
        return False


def release_scheduler_lock() -> None:
    global _lock, _held
    if _lock is not None and _held:
        try:
            _lock.release()
        except Exception as exc:  # pragma: no cover
            logger.debug("释放调度锁失败: %s", exc)
    _held = False
    _lock = None


def has_scheduler_lock() -> bool:
    return _held

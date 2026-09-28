from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

_logger = logging.getLogger("backend.atomic_io")

# 按路径的写锁注册表：保护「读-改-写」序列的原子性。
# 仅靠单次原子 rename 只能保证不写坏文件，但两个线程各自 read→mutate→write
# 时后写者会覆盖先写者的字段（丢失更新）；调用方用 path_write_lock 包住整个
# 读-改-写序列即可串行化。
_path_locks: dict[str, threading.RLock] = {}
_path_locks_guard = threading.Lock()


def path_write_lock(path) -> threading.RLock:
    """返回指定路径的进程内写锁（同一路径全局互斥）。

    用于包住「读配置 → 改字段 → 写回」的完整序列，防止并发丢失更新。
    同一路径重复获取是可重入的（RLock），因此不会与 _atomic_temp_file
    内部再次取锁产生死锁。
    """
    key = str(Path(path).resolve())
    with _path_locks_guard:
        lock = _path_locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _path_locks[key] = lock
        return lock


@contextlib.contextmanager
def _atomic_temp_file(path, mode: str, encoding: str | None = None):
    """原子写入临时文件上下文：写入 + fsync + 权限收敛(0600) + rename，异常时清理临时文件。

    内部除全局 _lock 外还会取该路径的 path_write_lock，使调用方在锁内完成的
    读-改-写不会被其他线程的写入插队。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path_write_lock(path):
        actual_tmp = None
        replaced = False
        try:
            kwargs: dict[str, Any] = {
                "mode": mode,
                "dir": str(path.parent),
                "prefix": f".{path.name}.tmp-",
                "delete": False,
            }
            if encoding is not None:
                kwargs["encoding"] = encoding
            with tempfile.NamedTemporaryFile(**kwargs) as tmp:
                actual_tmp = Path(tmp.name)
                yield tmp
                tmp.flush()
                os.fsync(tmp.fileno())
            with contextlib.suppress(OSError):
                actual_tmp.chmod(0o600)
            os.replace(actual_tmp, path)
            replaced = True
        finally:
            if not replaced:
                with contextlib.suppress(OSError):
                    if actual_tmp is not None and actual_tmp.exists():
                        actual_tmp.unlink()


def write_json_atomic(path, data: Any) -> None:
    """原子写入 JSON：临时文件 + 权限收敛(0600) + fsync + rename，崩溃不留下半截文件。"""
    with _atomic_temp_file(path, "w", encoding="utf-8") as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)


def write_text_atomic(path, text: str, encoding: str = "utf-8") -> None:
    """原子写入纯文本：临时文件 + 权限收敛(0600) + fsync + rename，崩溃不留下半截文件。"""
    with _atomic_temp_file(path, "w", encoding=encoding) as tmp:
        tmp.write(text)


def write_bytes_atomic(path, data: bytes) -> None:
    """原子写入二进制数据：临时文件 + 权限收敛(0600) + fsync + rename，崩溃不留下半截文件。"""
    with _atomic_temp_file(path, "wb") as tmp:
        tmp.write(data)


def read_json_safe(path, default: Any = None) -> Any:
    """读取 JSON 文件；文件缺失或内容损坏时返回 default。

    取该路径的写锁，避免读到「写事务进行中」的状态，并与调用方的
    读-改-写序列共用同一把锁。
    """
    path = Path(path)
    if not path.exists():
        return default
    try:
        with path_write_lock(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError, TypeError, ValueError) as exc:
        _logger.warning("读取 %s 失败，回退为默认值: %s", path, exc)
        return default

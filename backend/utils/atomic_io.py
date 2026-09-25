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

# 跨线程互斥，避免同进程并发写入同一文件写坏内容
_lock = threading.RLock()


@contextlib.contextmanager
def _atomic_temp_file(path, mode: str, encoding: str | None = None):
    """原子写入临时文件上下文：写入 + fsync + 权限收敛(0600) + rename，异常时清理临时文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
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
    """读取 JSON 文件；文件缺失或内容损坏时返回 default。"""
    path = Path(path)
    if not path.exists():
        return default
    try:
        with _lock:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError, TypeError, ValueError) as exc:
        _logger.warning("读取 %s 失败，回退为默认值: %s", path, exc)
        return default

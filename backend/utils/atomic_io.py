"""JSON 原子读写工具

全项目配置文件/状态文件统一走本模块：进程内锁串行化同进程并发写、
临时文件 + fsync + rename 保证崩溃不留下半截文件。
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

_logger = logging.getLogger("backend.utils.atomic_io")

# 进程内写锁：同进程并发读写同一文件时串行化，避免交错
_lock = threading.RLock()


def write_json_atomic(path, data: Any) -> None:
    """原子写入 JSON：临时文件 + fsync + rename，崩溃不留下半截文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False, dir=path.parent
        )
        actual_tmp = Path(tmp.name)
        replaced = False
        try:
            with tmp:
                json.dump(data, tmp, ensure_ascii=False, indent=2)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(actual_tmp, path)
            replaced = True
        finally:
            if not replaced:
                with contextlib.suppress(OSError):
                    actual_tmp.unlink()


def read_json_safe(path, default: Any = None) -> Any:
    """读取 JSON 文件；文件缺失或内容损坏时返回 default。"""
    path = Path(path)
    if not path.exists():
        return default
    try:
        with _lock:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError, TypeError, ValueError):
        _logger.debug("读取 JSON 失败，使用默认值: %s", path)
        return default

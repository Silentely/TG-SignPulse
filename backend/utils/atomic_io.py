from __future__ import annotations

# 为保持对上层后向兼容，直接从 tg_signer.atomic_io 导出
from tg_signer.atomic_io import (
    _atomic_temp_file,
    _path_locks,
    _path_locks_guard,
    path_write_lock,
    read_json_safe,
    read_text_safe,
    write_bytes_atomic,
    write_json_atomic,
    write_text_atomic,
)

__all__ = [
    "_atomic_temp_file",
    "_path_locks",
    "_path_locks_guard",
    "path_write_lock",
    "read_json_safe",
    "read_text_safe",
    "write_bytes_atomic",
    "write_json_atomic",
    "write_text_atomic",
]

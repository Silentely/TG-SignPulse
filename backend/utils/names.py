from __future__ import annotations

import re
from typing import Union


def validate_storage_name(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")

    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} cannot be empty")
    if cleaned in {".", ".."}:
        raise ValueError(f"{field_name} cannot be '.' or '..'")
    # Only forbid path separators and null bytes (filesystem safety on Linux)
    if "/" in cleaned or "\\" in cleaned or "\x00" in cleaned:
        raise ValueError(
            f"{field_name} cannot contain path separators or null bytes: / \\"
        )
    try:
        byte_length = len(cleaned.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field_name} contains invalid Unicode") from exc
    if byte_length > 128:
        raise ValueError(f"{field_name} length cannot exceed 128 bytes")
    return cleaned


def natural_sort_key(s: str) -> list[Union[int, str]]:
    """自然排序键函数（数字按数值大小，文本按不区分大小写排序）。"""
    return [
        int(text) if text.isdigit() else text.lower()
        for text in re.split(r"(\d+)", s or "")
    ]

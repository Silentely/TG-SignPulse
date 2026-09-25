from __future__ import annotations

import unicodedata

# 拒绝的 Unicode 常规类别：
# Cc 控制字符、Cf 格式字符（零宽/BOM/软连字符等）、Cs 代理区、Co 私用区、Cn 未分配码位。
# 这些字符在文件系统与终端上不可见或语义不定，出现在账号/任务名中会让目录难以定位和清理。
_REJECTED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})


def validate_storage_name(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")

    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} cannot be empty")
    if cleaned in {".", ".."}:
        raise ValueError(f"{field_name} cannot be \x27.\x27 or \x27..\x27")
    # Only forbid path separators and null bytes (filesystem safety on Linux)
    if "/" in cleaned or "\\" in cleaned or "\x00" in cleaned:
        raise ValueError(
            f"{field_name} cannot contain path separators or null bytes: / \\"
        )
    for char in cleaned:
        if unicodedata.category(char) in _REJECTED_CATEGORIES:
            raise ValueError(
                f"{field_name} cannot contain control or invisible characters"
            )
    try:
        byte_length = len(cleaned.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field_name} contains invalid Unicode") from exc
    if byte_length > 128:
        raise ValueError(f"{field_name} length cannot exceed 128 bytes")
    return cleaned

from __future__ import annotations

import re

_INVALID_STORAGE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def validate_storage_name(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")

    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} cannot be empty")
    if cleaned in {".", ".."}:
        raise ValueError(f"{field_name} cannot be '.' or '..'")
    if cleaned.endswith((" ", ".")):
        raise ValueError(f"{field_name} cannot end with a space or dot")
    if _INVALID_STORAGE_CHARS.search(cleaned):
        raise ValueError(
            f"{field_name} contains invalid filesystem characters: < > : \" / \\ | ? *"
        )
    return cleaned

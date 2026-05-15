from __future__ import annotations


def validate_storage_name(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")

    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} cannot be empty")
    if cleaned in {".", ".."}:
        raise ValueError(f"{field_name} cannot be '.' or '..'")
    # Only forbid path separators and null bytes (filesystem safety on Linux)
    if '/' in cleaned or '\\' in cleaned or '\x00' in cleaned:
        raise ValueError(
            f"{field_name} cannot contain path separators: / \\"
        )
    return cleaned

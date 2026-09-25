from __future__ import annotations

_ZERO_WIDTH_CHARS = {
    "\u200b",  # zero-width space
    "\u200c",  # zero-width non-joiner
    "\u200d",  # zero-width joiner
    "\ufeff",  # zero-width no-break space / byte order mark
}


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
    if any(ord(c) < 32 or ord(c) == 127 or c in _ZERO_WIDTH_CHARS for c in cleaned):
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

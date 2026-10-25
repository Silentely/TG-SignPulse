"""Approved Bot response contracts and drift comparison."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from tg_signer.atomic_io import path_write_lock, read_json_safe, write_json_atomic


def _root() -> Path:
    from backend.core.config import get_settings

    return get_settings().resolve_workdir() / "bot_contracts.json"


def build_bot_contract(event: Any) -> dict[str, Any]:
    buttons = getattr(event, "button_snapshot", ()) or ()
    payload = {
        "chat_id": event.chat_id,
        "thread_id": event.message_thread_id,
        "sender_id": event.sender_id,
        "text": event.text or "",
        "event_type": event.event_type,
        "buttons": buttons,
    }
    payload["fingerprint"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()
    return payload


def compare_bot_contract(
    expected: dict[str, Any], actual: dict[str, Any]
) -> dict[str, Any]:
    differences = {}
    for key in ("text", "sender_id", "thread_id", "buttons", "event_type"):
        if expected.get(key) != actual.get(key):
            differences[key] = {
                "expected": expected.get(key),
                "actual": actual.get(key),
            }
    return {
        "match": not differences,
        "differences": differences,
        "expected_fingerprint": expected.get("fingerprint"),
        "actual_fingerprint": actual.get("fingerprint"),
    }


def save_contract(name: str, contract: dict[str, Any]) -> None:
    with path_write_lock(_root()):
        data = read_json_safe(_root(), default={})
        data[str(name)] = contract
        write_json_atomic(_root(), data)


def load_contract(name: str) -> dict[str, Any] | None:
    return read_json_safe(_root(), default={}).get(str(name))

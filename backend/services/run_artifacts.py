"""Bounded, redacted execution evidence persisted for every terminal state."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from tg_signer.atomic_io import path_write_lock, read_json_safe, write_json_atomic
from tg_signer.semantic.security import redact_sensitive_text

MAX_ARTIFACTS = 1000
MAX_ARTIFACT_BYTES = 524288
_SECRET_KEY = re.compile(r"secret|token|password|session|api.?key|credential", re.I)


def artifact_root() -> Path:
    from backend.core.config import get_settings

    return get_settings().resolve_workdir() / "run_artifacts"


def redact_artifact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): "[REDACTED]" if _SECRET_KEY.search(str(k)) else redact_artifact(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_artifact(v) for v in value[:500]]
    if isinstance(value, str):
        return redact_sensitive_text(value[:2000])
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return "[UNSERIALIZABLE]"


def _artifact_path(run_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
        raise ValueError("Invalid run artifact identifier")
    return artifact_root() / f"{run_id}.json"


def record_run_artifact(
    *,
    run_id: str,
    config_revision: str,
    graph_revision: str,
    terminal_status: str,
    node_outcomes: list[dict[str, Any]],
    events: list[dict[str, Any]],
    receipts: list[dict[str, Any]],
    **metadata: Any,
) -> str:
    target = _artifact_path(run_id)
    payload = redact_artifact(
        {
            "version": 1,
            "run_id": run_id,
            "config_revision": config_revision,
            "graph_revision": graph_revision,
            "terminal_status": terminal_status,
            "node_outcomes": node_outcomes,
            "events": events,
            "receipts": receipts,
            **metadata,
        }
    )
    if len(json.dumps(payload).encode()) > MAX_ARTIFACT_BYTES:
        raise ValueError("Run artifact exceeds size limit")
    target.parent.mkdir(parents=True, exist_ok=True)
    with path_write_lock(target.parent / ".retention"):
        write_json_atomic(target, payload)
        candidates = sorted(
            target.parent.glob("*.json"), key=lambda p: p.stat().st_mtime_ns
        )
        for old in candidates[: max(0, len(candidates) - MAX_ARTIFACTS)]:
            old.unlink()
    return run_id


def load_run_artifact(run_id: str) -> dict[str, Any] | None:
    return read_json_safe(_artifact_path(run_id), default=None)

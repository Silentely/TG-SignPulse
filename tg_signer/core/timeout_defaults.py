"""Central timeout defaults shared by task normalization and execution."""

from __future__ import annotations

DEFAULT_ACTION_TIMEOUT_SECONDS = 90.0
DEFAULT_FLOW_NODE_TIMEOUT_SECONDS = 180.0
DEFAULT_TASK_EXECUTION_TIMEOUT_SECONDS = 300.0
LEGACY_ACTION_TIMEOUT_SECONDS = 25.0


def is_legacy_action_timeout(value: object) -> bool:
    """Return whether a persisted timeout is the historical 25-second default."""
    try:
        return float(value) == LEGACY_ACTION_TIMEOUT_SECONDS
    except (TypeError, ValueError):
        return False

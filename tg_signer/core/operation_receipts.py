"""Attempt-scoped external operation facts shared across runner adapters."""

from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class OperationAttemptState(str, Enum):
    NOT_STARTED = "not_started"
    ATTEMPTED = "attempted"
    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"


@dataclass
class OperationReceipt:
    operation_id: str
    node_id: str
    attempt: int
    kind: str
    state: OperationAttemptState = OperationAttemptState.NOT_STARTED
    remote_id: Optional[str] = None
    evidence: dict[str, Any] = field(default_factory=dict)


current_operation: ContextVar[Optional[OperationReceipt]] = ContextVar(
    "pulseflow_current_operation", default=None
)


def mark_operation_attempted() -> None:
    receipt = current_operation.get()
    if receipt is not None:
        receipt.state = OperationAttemptState.ATTEMPTED


class UnknownOperationResult(RuntimeError):
    non_retryable = True
    failure_code = "operation_unknown"

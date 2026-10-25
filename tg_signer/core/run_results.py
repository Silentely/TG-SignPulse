"""Additive business outcomes independent of transport completion."""

from enum import Enum
from typing import Any, Optional, TypedDict


class BusinessStatus(str, Enum):
    NOT_EVALUATED = "not_evaluated"
    CONFIRMED = "confirmed"
    ALREADY_DONE = "already_done"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class TargetRunResult(TypedDict):
    account_name: str
    chat_id: str
    thread_id: Optional[int]
    execution_status: str
    business_status: str
    failure_category: Optional[str]
    evidence: list[dict[str, Any]]
    retry_safe: bool


def aggregate_target_status(rows: list[dict[str, Any]]) -> str:
    statuses = {r["business_status"] for r in rows}
    if "unknown" in statuses:
        return "unknown"
    if "needs_review" in statuses:
        return "needs_review"
    if "partial" in statuses or ("failed" in statuses and len(statuses) > 1):
        return "partial"
    if statuses == {"failed"}:
        return "failed"
    return "not_evaluated" if "not_evaluated" in statuses else "confirmed"

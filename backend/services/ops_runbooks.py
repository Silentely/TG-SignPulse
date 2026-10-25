"""Read-first operational diagnoses and explicitly allowlisted actions."""

from __future__ import annotations

from typing import Any


def get_runbook_diagnosis(account_name: str, task_name: str) -> dict[str, Any]:
    from backend.services.sign_tasks import get_sign_task_service

    service = get_sign_task_service()
    status = service.get_task_run_status(account_name, task_name)
    return {
        "account_name": account_name,
        "task_name": task_name,
        "status": status,
        "confidence": "source_state",
        "actions": ["refresh_task_cache"],
    }


def apply_runbook_action(
    action_id: str, *, account_name: str = "", task_name: str = "", dry_run: bool = True
) -> dict[str, Any]:
    allowed = {"refresh_task_cache"}
    if action_id not in allowed:
        raise ValueError("RUNBOOK_ACTION_NOT_ALLOWED")
    if dry_run:
        return {"action_id": action_id, "dry_run": True, "applied": False}
    from backend.services.sign_tasks import get_sign_task_service

    service = get_sign_task_service()
    if action_id == "refresh_task_cache":
        service.invalidate_tasks_cache()
    return {
        "action_id": action_id,
        "dry_run": False,
        "applied": True,
        "account_name": account_name,
        "task_name": task_name,
    }

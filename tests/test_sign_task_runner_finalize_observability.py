from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from backend.services.sign_task_runner import _runner_finalize


@pytest.fixture
def base_state():
    svc = MagicMock()
    svc._active_logs = {}
    svc._cleanup_tasks = {}
    svc._active_tasks = {}
    svc._account_last_run_end = {}
    svc.get_task_run_status = MagicMock(return_value={})
    svc._update_run_status_memory = MagicMock()
    svc._clean_task_status_memory = MagicMock()

    return {
        "svc": svc,
        "account_name": "acc1",
        "task_name": "task1",
        "task_key": "acc1:task1",
        "run_id": "run-1",
        "cancelled": False,
        "success": True,
        "lock_acquired": False,
    }


@pytest.mark.asyncio
async def test_runner_finalize_records_structured_errors():
    """Exact test case from task brief."""
    svc = MagicMock()
    svc._active_logs = {}
    svc._cleanup_tasks = {}
    svc._active_tasks = {}
    svc._account_last_run_end = {}
    svc.get_task_run_status = MagicMock(return_value={})
    svc._update_run_status_memory = MagicMock()
    svc._clean_task_status_memory = MagicMock()

    state = {
        "svc": svc,
        "account_name": "acc1",
        "task_name": "task1",
        "task_key": "acc1:task1",
        "run_id": "run-1",
        "cancelled": False,
        "success": True,
        "lock_acquired": False,
    }
    with patch("backend.services.sign_task_runner._runner_save_run_info", side_effect=IOError("Disk full")):
        await _runner_finalize(state)
        assert state.get("persistence_error", {}).get("message") == "Disk full"
        assert state.get("persistence_error", {}).get("type") == "IOError"


@pytest.mark.asyncio
async def test_runner_finalize_records_persistence_error(base_state):
    state = base_state
    start_time = time.time()

    with patch(
        "backend.services.sign_task_runner._runner_save_run_info",
        side_effect=IOError("Disk full"),
    ), patch(
        "backend.services.sign_task_runner._runner_send_notifications",
    ) as mock_send_notifications, patch(
        "backend.services.sign_task_runner._service_logger.error",
    ) as mock_log_error:
        await _runner_finalize(state)

        # Assert persistence_error is captured
        assert "persistence_error" in state
        err = state["persistence_error"]
        assert err.get("message") == "Disk full"
        assert err.get("type") == "IOError"
        assert start_time <= err.get("timestamp") <= time.time()

        # Notification should still proceed despite persistence error
        mock_send_notifications.assert_called_once_with(state)
        # Structured error must be logged
        mock_log_error.assert_called()

        # Cleanup in finally must have executed
        assert state["svc"]._active_tasks[state["task_key"]] is False


@pytest.mark.asyncio
async def test_runner_finalize_records_notification_error(base_state):
    state = base_state
    start_time = time.time()

    with patch(
        "backend.services.sign_task_runner._runner_save_run_info",
    ) as mock_save_run_info, patch(
        "backend.services.sign_task_runner._runner_send_notifications",
        side_effect=RuntimeError("Notification network timeout"),
    ), patch(
        "backend.services.sign_task_runner._service_logger.error",
    ) as mock_log_error:
        await _runner_finalize(state)

        # Persistence succeeded
        mock_save_run_info.assert_called_once_with(state)
        assert "persistence_error" not in state

        # Notification error is captured
        assert "notification_error" in state
        err = state["notification_error"]
        assert err.get("message") == "Notification network timeout"
        assert err.get("type") == "RuntimeError"
        assert start_time <= err.get("timestamp") <= time.time()

        # Structured error must be logged
        mock_log_error.assert_called()

        # Cleanup in finally must have executed
        assert state["svc"]._active_tasks[state["task_key"]] is False


@pytest.mark.asyncio
async def test_runner_finalize_records_both_errors(base_state):
    state = base_state

    with patch(
        "backend.services.sign_task_runner._runner_save_run_info",
        side_effect=IOError("Disk failure"),
    ), patch(
        "backend.services.sign_task_runner._runner_send_notifications",
        side_effect=ValueError("Invalid webhook"),
    ), patch(
        "backend.services.sign_task_runner._service_logger.error",
    ) as mock_log_error:
        await _runner_finalize(state)

        assert state.get("persistence_error", {}).get("message") == "Disk failure"
        assert state.get("persistence_error", {}).get("type") == "IOError"
        assert state.get("notification_error", {}).get("message") == "Invalid webhook"
        assert state.get("notification_error", {}).get("type") == "ValueError"

        assert mock_log_error.call_count >= 2
        assert state["svc"]._active_tasks[state["task_key"]] is False


@pytest.mark.asyncio
async def test_runner_finalize_cancelled_skips_persistence_and_notifications(base_state):
    state = base_state
    state["cancelled"] = True

    with patch(
        "backend.services.sign_task_runner._runner_save_run_info",
        side_effect=IOError("Should not be called"),
    ) as mock_save, patch(
        "backend.services.sign_task_runner._runner_send_notifications",
        side_effect=RuntimeError("Should not be called"),
    ) as mock_notify:
        await _runner_finalize(state)

        mock_save.assert_not_called()
        mock_notify.assert_not_called()
        assert "persistence_error" not in state
        assert "notification_error" not in state
        assert state["svc"]._active_tasks[state["task_key"]] is False

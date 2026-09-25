from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from backend.services.flood_backoff import FloodBackoffManager
from backend.services.sign_task_failure import FailureCategory
from backend.services.sign_task_runner import (
    _runner_check_account,
    _runner_send_notifications,
)


def test_flood_backoff_manager_basic():
    mgr = FloodBackoffManager()
    acc = "test_acc_1"
    assert mgr.is_cooling_down(acc) == (False, 0)

    # 记录 10 秒冷却
    info = mgr.record_flood_wait(acc, wait_seconds=10, reason="test rate limit")
    assert info.account_name == acc
    assert info.duration == 10

    cooling, rem = mgr.is_cooling_down(acc)
    assert cooling is True
    assert 8 <= rem <= 10

    all_cooling = mgr.get_all_cooling_accounts()
    assert acc in all_cooling
    assert all_cooling[acc]["duration"] == 10

    # 清除冷却
    mgr.clear_cooldown(acc)
    assert mgr.is_cooling_down(acc) == (False, 0)


def test_flood_backoff_expiration():
    mgr = FloodBackoffManager()
    acc = "test_acc_expired"
    # 手动注入一个已经过去的冷却
    mgr.record_flood_wait(acc, wait_seconds=5)
    mgr._cooldowns[acc].cooldown_until = time.time() - 1

    cooling, rem = mgr.is_cooling_down(acc)
    assert cooling is False
    assert rem == 0
    assert acc not in mgr._cooldowns


@pytest.mark.asyncio
async def test_runner_check_account_flood_wait_not_marking_account_invalid():
    mock_svc = MagicMock()
    mock_svc._task_key = lambda acc, t: f"{acc}:{t}"
    mock_svc._append_active_log = MagicMock()
    mock_svc._update_run_phase = MagicMock()

    mgr = FloodBackoffManager()
    mgr.record_flood_wait("acc_flood", wait_seconds=60)

    state = {
        "svc": mock_svc,
        "account_name": "acc_flood",
        "task_name": "task1",
        "signer_no_updates": True,
        "task_notify_on_failure": True,
        "account_invalid_detected": False,
        "flood_wait_cooling": False,
    }

    with patch("backend.services.flood_backoff.get_flood_backoff_manager", return_value=mgr):
        await _runner_check_account(state)

    assert state["flood_wait_cooling"] is True
    assert state["account_invalid_detected"] is False
    assert state["failure_category"] == FailureCategory.FLOOD_WAIT
    assert "Telegram FloodWait" in state["error_msg"]


@pytest.mark.asyncio
async def test_runner_send_notifications_suppressed_during_flood_cooldown():
    """FloodWait 冷却期的失败不触发失败通知（与账号失效同级的通知抑制）。"""
    state = {
        "account_name": "acc_flood",
        "task_name": "task1",
        "success": False,
        "account_invalid_detected": False,
        "flood_wait_cooling": True,
        "task_notify_on_failure": True,
        "failure_category": FailureCategory.FLOOD_WAIT.value,
        "error_msg": "Telegram FloodWait: A wait of 60 seconds is required",
        "final_logs": [],
        "last_reply": "",
        "last_target_message": None,
    }
    with patch(
        "backend.services.sign_task_notify.send_failure_notification"
    ) as send_failure, patch(
        "backend.services.sign_task_notify.send_success_notification"
    ) as send_success:
        await _runner_send_notifications(state)

    send_failure.assert_not_called()
    send_success.assert_not_called()


@pytest.mark.asyncio
async def test_runner_send_notifications_failure_sent_when_not_cooldown():
    """非冷却期的一般失败仍正常发送失败通知。"""
    state = {
        "account_name": "acc_normal",
        "task_name": "task1",
        "success": False,
        "account_invalid_detected": False,
        "flood_wait_cooling": False,
        "task_notify_on_failure": True,
        "failure_category": FailureCategory.TIMEOUT.value,
        "error_msg": "request timeout",
        "final_logs": [],
        "last_reply": "",
        "last_target_message": None,
    }
    with patch(
        "backend.services.sign_task_notify.send_failure_notification"
    ) as send_failure, patch(
        "backend.services.sign_task_notify.send_success_notification"
    ) as send_success:
        await _runner_send_notifications(state)

    send_failure.assert_called_once()
    send_success.assert_not_called()

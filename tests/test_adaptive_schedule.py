from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.scheduler import reschedule_sign_task_once
from tests.test_sign_task_runner import FakeSvc
from tg_signer.core.adaptive_schedule import parse_cooldown_timedelta


def test_parse_cooldown_chinese_formats():
    assert parse_cooldown_timedelta("冷却中，请等待 15 分钟") == timedelta(minutes=15)
    assert parse_cooldown_timedelta("距离下次签到还有 1天2小时") == timedelta(days=1, hours=2)
    assert parse_cooldown_timedelta("操作频繁，请 45秒 后重试") == timedelta(seconds=45)
    assert parse_cooldown_timedelta("请在2小时后再试") == timedelta(hours=2)
    assert parse_cooldown_timedelta("冷却时间剩余 1天3小时20分10秒") == timedelta(days=1, hours=3, minutes=20, seconds=10)
    assert parse_cooldown_timedelta("请在 3小时15分钟 后再试") == timedelta(hours=3, minutes=15)
    assert parse_cooldown_timedelta("请等待半小时后再试") == timedelta(minutes=30)
    assert parse_cooldown_timedelta("距离下次签到还有一个半小时") == timedelta(hours=1, minutes=30)
    assert parse_cooldown_timedelta("冷却时间：1小时零5分钟") == timedelta(hours=1, minutes=5)
    assert parse_cooldown_timedelta("请在2小时半后再试") == timedelta(hours=2, minutes=30)
    assert parse_cooldown_timedelta("请等待半天后再试") == timedelta(hours=12)


def test_parse_cooldown_english_formats():
    assert parse_cooldown_timedelta("Try again in 2h 30m") == timedelta(hours=2, minutes=30)
    assert parse_cooldown_timedelta("Cooldown: 45s") == timedelta(seconds=45)
    assert parse_cooldown_timedelta("Please wait 1 day 2 hours") == timedelta(days=1, hours=2)
    assert parse_cooldown_timedelta("Retry in 15 minutes") == timedelta(minutes=15)
    assert parse_cooldown_timedelta("Wait 10s before next attempt") == timedelta(seconds=10)
    assert parse_cooldown_timedelta("Cooldown: 1h30m") == timedelta(hours=1, minutes=30)


def test_parse_cooldown_rejects_numeric_noise():
    # Strict unit anchoring must not treat random numbers as time units
    assert parse_cooldown_timedelta("获得 500 积分") is None
    assert parse_cooldown_timedelta("用户 ID: 12345") is None
    assert parse_cooldown_timedelta("签到成功！当前连续签到 7 天，获得经验 100 点") is None


def test_parse_cooldown_custom_patterns_priority():
    text = "系统提示：距离下次签到限制还需 1800 秒，请知悉"
    custom_patterns = [r"还需\s*(\d+)\s*秒"]
    assert parse_cooldown_timedelta(text, custom_patterns=custom_patterns) == timedelta(seconds=1800)


def test_reschedule_sign_task_once_modifies_next_run_time():
    mock_job = MagicMock()
    mock_scheduler = MagicMock()
    mock_scheduler.get_job.return_value = mock_job

    with patch("backend.scheduler.scheduler", mock_scheduler):
        run_at = datetime.now(timezone.utc) + timedelta(minutes=30)
        success = reschedule_sign_task_once("test_account", "test_task", run_at)

        assert success is True
        mock_scheduler.get_job.assert_called_once_with("sign-test_account-test_task")
        mock_job.modify.assert_called_once_with(next_run_time=run_at)


@pytest.mark.asyncio
async def test_task_runner_triggers_adaptive_reschedule(monkeypatch):
    import asyncio

    from backend.services.sign_task_runner import execute_sign_task

    task_cfg = {
        "name": "daily_checkin",
        "account_name": "user1",
        "adaptive_schedule_enabled": True,
        "adaptive_schedule_padding_seconds": 30,
        "adaptive_schedule_patterns": [],
    }
    svc = FakeSvc(task_cfg)

    monkeypatch.setattr("backend.services.sign_task_notify.check_account_before_task", AsyncMock(return_value=None))
    monkeypatch.setattr("backend.services.sign_task_notify.send_success_notification", AsyncMock())
    monkeypatch.setattr("backend.services.sign_task_notify.send_failure_notification", AsyncMock())
    monkeypatch.setattr("backend.utils.account_locks.get_account_lock", lambda a: asyncio.Lock())
    monkeypatch.setattr("backend.utils.tg_session.get_session_mode", lambda: "file")
    monkeypatch.setattr("backend.utils.tg_session.load_account_session_string", lambda *a, **k: None)
    monkeypatch.setattr("backend.utils.tg_session.get_global_semaphore", lambda: asyncio.Semaphore(10))
    monkeypatch.setattr("backend.services.runtime_settings.get_execution_timeout", lambda: 10.0)
    monkeypatch.setattr("backend.services.runtime_settings.get_flow_retry_attempts", lambda: 0)
    monkeypatch.setattr("backend.services.sign_task_runner.POST_RUN_LOCK_BUFFER_SECONDS", 0)

    # Wire up signer factory
    class MockBackendUserSigner:
        def __init__(self, *a, **kw):
            pass

        async def run_once(self, *a, **kw):
            # Simulate bot response logged
            task_key = svc._task_key("user1", "daily_checkin")
            svc._append_active_log(task_key, "收到来自「Bot」的消息: Message: text: 冷却中，请等待 15 分钟")
            return None

    monkeypatch.setattr("backend.services.sign_task_backend.BackendUserSigner", MockBackendUserSigner)

    with patch("backend.scheduler.reschedule_sign_task_once") as mock_reschedule:
        mock_reschedule.return_value = True
        res = await execute_sign_task(svc, "user1", "daily_checkin")
        assert res["success"] is True

        assert mock_reschedule.called
        call_args = mock_reschedule.call_args[0]
        assert call_args[0] == "user1"
        assert call_args[1] == "daily_checkin"
        scheduled_dt = call_args[2]
        # Should be roughly now + 15 mins + 30s padding
        expected_min = datetime.now(timezone.utc) + timedelta(minutes=14, seconds=50)
        expected_max = datetime.now(timezone.utc) + timedelta(minutes=16)
        assert expected_min <= scheduled_dt <= expected_max


def test_adaptive_schedule_schema_and_config():
    from backend.api.routes.sign_tasks_v2 import (
        SignTaskCreate,
    )
    from backend.services.sign_task_config_build import (
        build_sign_task_config,
        resolve_update_field_values,
    )

    # Test SignTaskCreate defaults
    create_payload = SignTaskCreate(
        name="task1",
        sign_at="08:00",
        chats=[{"chat_id": 123, "actions": [{"action": "send", "message": "checkin"}]}],
    )
    assert create_payload.adaptive_schedule_enabled is False
    assert create_payload.adaptive_schedule_patterns == []
    assert create_payload.adaptive_schedule_padding_seconds == 30

    # Test custom values
    custom_create = SignTaskCreate(
        name="task2",
        sign_at="08:00",
        chats=[{"chat_id": 123, "actions": [{"action": "send", "message": "checkin"}]}],
        adaptive_schedule_enabled=True,
        adaptive_schedule_patterns=[r"还需\s*(\d+)\s*秒"],
        adaptive_schedule_padding_seconds=60,
    )
    assert custom_create.adaptive_schedule_enabled is True
    assert custom_create.adaptive_schedule_patterns == [r"还需\s*(\d+)\s*秒"]
    assert custom_create.adaptive_schedule_padding_seconds == 60

    # Test config builder
    cfg = build_sign_task_config(
        account_name="acc1",
        account_names=["acc1"],
        adaptive_schedule_enabled=True,
        adaptive_schedule_patterns=[r"\d+s"],
        adaptive_schedule_padding_seconds=45,
    )
    assert cfg["adaptive_schedule_enabled"] is True
    assert cfg["adaptive_schedule_patterns"] == [r"\d+s"]
    assert cfg["adaptive_schedule_padding_seconds"] == 45

    # Test config update resolution
    updated = resolve_update_field_values(
        cfg,
        adaptive_schedule_enabled=False,
    )
    assert updated["adaptive_schedule_enabled"] is False
    assert updated["adaptive_schedule_patterns"] == [r"\d+s"]
    assert updated["adaptive_schedule_padding_seconds"] == 45

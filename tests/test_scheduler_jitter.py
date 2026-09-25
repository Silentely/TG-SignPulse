from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from backend.api.routes.sign_tasks_v2 import SignTaskCreate, SignTaskUpdate
from backend.scheduler import _job_run_sign_task, create_cron_trigger


def test_create_cron_trigger_with_jitter():
    # 5-field cron
    t1 = create_cron_trigger("*/5 * * * *", jitter=10)
    assert t1.jitter == 10

    # 6-field cron
    t2 = create_cron_trigger("0 0 8 * * *", jitter=15)
    assert t2.jitter == 15

    # HH:MM clock format
    t3 = create_cron_trigger("08:00", jitter=20)
    assert t3.jitter == 20

    # Default jitter is 0 (or falsy)
    t4 = create_cron_trigger("08:00")
    assert not t4.jitter


@pytest.mark.asyncio
async def test_job_run_sign_task_does_not_apply_jitter_twice_in_cron_mode():
    """错峰延迟只由 CronTrigger.jitter 承担，Job 体内不得再次 sleep 叠加。"""
    mock_service = MagicMock()
    mock_service.get_task.return_value = {
        "name": "daily_task",
        "execution_mode": "fixed",
        "jitter_seconds": 30,
    }
    mock_service.run_task_with_logs = AsyncMock(return_value={"success": True})

    with patch(
        "backend.services.sign_tasks.get_sign_task_service", return_value=mock_service
    ), patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep, patch(
        "random.uniform", return_value=12.5
    ) as mock_uniform:
        await _job_run_sign_task("account1", "daily_task")

        mock_uniform.assert_not_called()
        mock_sleep.assert_not_called()
        mock_service.run_task_with_logs.assert_awaited_once_with("account1", "daily_task")


@pytest.mark.asyncio
async def test_job_run_sign_task_clears_pending_adaptive_reschedule():
    """Job 真正执行后应清除待生效的自适应调度覆盖时间。"""
    from backend.scheduler import _ADAPTIVE_NEXT_RUNS

    mock_service = MagicMock()
    mock_service.get_task.return_value = {
        "name": "daily_task",
        "execution_mode": "fixed",
        "jitter_seconds": 0,
    }
    mock_service.run_task_with_logs = AsyncMock(return_value={"success": True})

    job_id = "sign-account1-daily_task"
    _ADAPTIVE_NEXT_RUNS[job_id] = datetime(2026, 9, 19, 12, 0, 0)
    try:
        with patch(
            "backend.services.sign_tasks.get_sign_task_service", return_value=mock_service
        ):
            await _job_run_sign_task("account1", "daily_task")
        assert job_id not in _ADAPTIVE_NEXT_RUNS
    finally:
        _ADAPTIVE_NEXT_RUNS.pop(job_id, None)


@pytest.mark.asyncio
async def test_job_run_sign_task_skips_jitter_when_zero():
    mock_service = MagicMock()
    mock_service.get_task.return_value = {
        "name": "daily_task",
        "execution_mode": "fixed",
        "jitter_seconds": 0,
    }
    mock_service.run_task_with_logs = AsyncMock(return_value={"success": True})

    with patch(
        "backend.services.sign_tasks.get_sign_task_service", return_value=mock_service
    ), patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await _job_run_sign_task("account1", "daily_task")

        mock_sleep.assert_not_called()
        mock_service.run_task_with_logs.assert_awaited_once_with("account1", "daily_task")


@pytest.mark.asyncio
async def test_job_run_sign_task_range_mode_precedence():
    mock_service = MagicMock()
    mock_service.get_task.return_value = {
        "name": "daily_task",
        "execution_mode": "range",
        "range_start": "08:00",
        "range_end": "08:30",
        "jitter_seconds": 300,
    }
    mock_service.run_task_with_logs = AsyncMock(return_value={"success": True})

    with patch(
        "backend.services.sign_tasks.get_sign_task_service", return_value=mock_service
    ), patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep, patch(
        "backend.scheduler._parse_clock_time"
    ) as mock_parse, patch(
        "backend.scheduler.datetime"
    ) as mock_dt:
        from datetime import datetime, time
        mock_parse.side_effect = lambda s: time(8, 0) if s == "08:00" else time(8, 30)
        fixed_now = datetime(2026, 9, 19, 8, 0, 0)
        mock_dt.now.return_value = fixed_now
        mock_dt.strptime = datetime.strptime

        await _job_run_sign_task("account1", "daily_task")

        # Range mode performs exactly one sleep based on range delay, not jitter_seconds
        assert mock_sleep.await_count == 1
        mock_service.run_task_with_logs.assert_awaited_once_with("account1", "daily_task")


def test_sign_task_schema_jitter_validation():
    base_data = {
        "name": "test_jitter_task",
        "sign_at": "08:00",
        "chats": [{"chat_id": 123456, "actions": [{"type": "text", "text": "checkin"}]}],
    }
    # Valid jitter_seconds in SignTaskCreate
    item = SignTaskCreate(**base_data, jitter_seconds=30)
    assert item.jitter_seconds == 30

    # Upper bound: 3600 is valid
    item_max = SignTaskCreate(**base_data, jitter_seconds=3600)
    assert item_max.jitter_seconds == 3600

    # Default is 0
    item_default = SignTaskCreate(**base_data)
    assert item_default.jitter_seconds == 0

    # Exceeds 3600: invalid
    with pytest.raises(ValidationError):
        SignTaskCreate(**base_data, jitter_seconds=3601)

    # Negative: invalid
    with pytest.raises(ValidationError):
        SignTaskCreate(**base_data, jitter_seconds=-1)

    # SignTaskUpdate validation
    update_valid = SignTaskUpdate(jitter_seconds=600)
    assert update_valid.jitter_seconds == 600

    with pytest.raises(ValidationError):
        SignTaskUpdate(jitter_seconds=3601)

    with pytest.raises(ValidationError):
        SignTaskUpdate(jitter_seconds=-5)


def test_create_cron_trigger_with_invalid_jitter_and_tz():
    # Negative jitter falls back to 0
    t1 = create_cron_trigger("*/5 * * * *", jitter=-10)
    assert not t1.jitter

    # String jitter coerced to int
    t2 = create_cron_trigger("0 0 8 * * *", jitter="25")  # type: ignore[arg-type]
    assert t2.jitter == 25

    # Invalid timezone string falls back safely without raising
    t3 = create_cron_trigger("08:00", timezone="Invalid/NonExistent_TZ")
    assert t3 is not None


@pytest.mark.asyncio
async def test_job_run_sign_task_cancelled_error():
    mock_service = MagicMock()
    mock_service.get_task.return_value = {"name": "t1", "execution_mode": "fixed"}
    mock_service.run_task_with_logs = AsyncMock(side_effect=asyncio.CancelledError())

    with patch("backend.services.sign_tasks.get_sign_task_service", return_value=mock_service):
        with pytest.raises(asyncio.CancelledError):
            await _job_run_sign_task("acc1", "t1")

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import backend.scheduler as scheduler_mod
from backend.scheduler import (
    _RANGE_COMPENSATION_RUNS,
    _compute_range_task_compensation,
    _get_range_window,
    _job_run_sign_task,
    sync_jobs,
)


def test_get_range_window_normal():
    tz = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 9, 21, 11, 14, 0, tzinfo=tz)
    res = _get_range_window("09:00", "18:00", now)
    assert res is not None
    start_dt, end_dt = res
    assert start_dt == datetime(2026, 9, 21, 9, 0, 0, tzinfo=tz)
    assert end_dt == datetime(2026, 9, 21, 18, 0, 0, tzinfo=tz)


def test_get_range_window_cross_midnight():
    tz = ZoneInfo("Asia/Shanghai")
    # Night before midnight
    now_night = datetime(2026, 9, 21, 23, 30, 0, tzinfo=tz)
    res = _get_range_window("22:00", "06:00", now_night)
    assert res is not None
    start_dt, end_dt = res
    assert start_dt == datetime(2026, 9, 21, 22, 0, 0, tzinfo=tz)
    assert end_dt == datetime(2026, 9, 22, 6, 0, 0, tzinfo=tz)

    # Early morning after midnight
    now_morning = datetime(2026, 9, 22, 3, 30, 0, tzinfo=tz)
    res2 = _get_range_window("22:00", "06:00", now_morning)
    assert res2 is not None
    start_dt2, end_dt2 = res2
    assert start_dt2 == datetime(2026, 9, 21, 22, 0, 0, tzinfo=tz)
    assert end_dt2 == datetime(2026, 9, 22, 6, 0, 0, tzinfo=tz)


def test_compute_range_task_compensation_outside_window():
    tz = ZoneInfo("Asia/Shanghai")
    cfg = {
        "execution_mode": "range",
        "range_start": "09:00",
        "range_end": "18:00",
    }
    # Before window
    now_before = datetime(2026, 9, 21, 8, 30, 0, tzinfo=tz)
    assert _compute_range_task_compensation(cfg, tz=tz, now=now_before) is None

    # After window
    now_after = datetime(2026, 9, 21, 18, 30, 0, tzinfo=tz)
    assert _compute_range_task_compensation(cfg, tz=tz, now=now_after) is None

    # Not range mode
    cfg_fixed = {"execution_mode": "fixed", "sign_at": "09:00"}
    now_mid = datetime(2026, 9, 21, 11, 14, 0, tzinfo=tz)
    assert _compute_range_task_compensation(cfg_fixed, tz=tz, now=now_mid) is None


def test_compute_range_task_compensation_already_succeeded():
    tz = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 9, 21, 11, 14, 0, tzinfo=tz)
    # Succeeded at 09:30 today
    cfg = {
        "execution_mode": "range",
        "range_start": "09:00",
        "range_end": "18:00",
        "last_run": {
            "time": "2026-09-21T09:30:00+08:00",
            "success": True,
        },
    }
    assert _compute_range_task_compensation(cfg, tz=tz, now=now) is None


def test_compute_range_task_compensation_not_run_or_failed():
    tz = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 9, 21, 11, 14, 0, tzinfo=tz)

    # 1. Not run yet (last run yesterday)
    cfg_yesterday = {
        "execution_mode": "range",
        "range_start": "09:00",
        "range_end": "18:00",
        "last_run": {
            "time": "2026-09-20T14:30:00+08:00",
            "success": True,
        },
    }
    run_at = _compute_range_task_compensation(cfg_yesterday, tz=tz, now=now)
    assert run_at is not None
    assert now <= run_at <= datetime(2026, 9, 21, 18, 0, 0, tzinfo=tz)

    # 2. Failed earlier today in current window
    cfg_failed = {
        "execution_mode": "range",
        "range_start": "09:00",
        "range_end": "18:00",
        "last_run": {
            "time": "2026-09-21T09:42:00+08:00",
            "success": False,
        },
    }
    run_at_failed = _compute_range_task_compensation(cfg_failed, tz=tz, now=now)
    assert run_at_failed is not None
    assert now <= run_at_failed <= datetime(2026, 9, 21, 18, 0, 0, tzinfo=tz)


def test_compute_range_task_compensation_tight_remaining_window():
    tz = ZoneInfo("Asia/Shanghai")
    # 5 seconds remaining before 18:00
    now = datetime(2026, 9, 21, 17, 59, 55, tzinfo=tz)
    cfg = {
        "execution_mode": "range",
        "range_start": "09:00",
        "range_end": "18:00",
    }
    run_at = _compute_range_task_compensation(cfg, tz=tz, now=now)
    assert run_at is not None
    assert (run_at - now).total_seconds() <= 2.0


@pytest.mark.asyncio
async def test_job_run_sign_task_cross_midnight_delay_stays_in_window():
    """跨天窗口在凌晨迟到触发时，随机延迟必须落在窗口内，不得推出 range_end。"""
    _RANGE_COMPENSATION_RUNS.clear()
    tz = ZoneInfo("Asia/Shanghai")
    # 窗口 22:00→06:00，进程在凌晨 03:30 才迟到触发（misfire/重启）
    late_now = datetime(2026, 9, 22, 3, 30, 0, tzinfo=tz)

    mock_service = MagicMock()
    mock_service.get_task.return_value = {
        "name": "night_task",
        "account_name": "acc1",
        "execution_mode": "range",
        "range_start": "22:00",
        "range_end": "06:00",
    }
    mock_service.run_task_with_logs = AsyncMock(return_value={"success": True})

    with patch("backend.services.sign_tasks.get_sign_task_service", return_value=mock_service):
        with patch("backend.scheduler._resolve_scheduler_timezone", return_value=tz):
            with patch("backend.scheduler.datetime") as mock_dt:
                mock_dt.now.side_effect = lambda t=None: late_now
                mock_dt.strptime = datetime.strptime
                mock_dt.fromisoformat = datetime.fromisoformat
                with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                    await _job_run_sign_task("acc1", "night_task")

    mock_sleep.assert_awaited_once()
    delay_seconds = mock_sleep.await_args.args[0]
    # 剩余窗口只有 2.5 小时（03:30 → 06:00），延迟不得越过它
    assert 0 <= delay_seconds <= (6 * 3600) - (3.5 * 3600) + 1
    mock_service.run_task_with_logs.assert_awaited_once_with("acc1", "night_task")


@pytest.mark.asyncio
async def test_job_run_sign_task_bypasses_sleep_on_compensation():
    _RANGE_COMPENSATION_RUNS.clear()
    job_id = "sign-acc1-task1"
    _RANGE_COMPENSATION_RUNS[job_id] = datetime.now()

    mock_service = MagicMock()
    mock_service.get_task.return_value = {
        "name": "task1",
        "account_name": "acc1",
        "execution_mode": "range",
        "range_start": "09:00",
        "range_end": "18:00",
    }
    mock_service.run_task_with_logs = AsyncMock(return_value={"success": True})

    with patch("backend.services.sign_tasks.get_sign_task_service", return_value=mock_service):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await _job_run_sign_task("acc1", "task1")

            # Compensation should pop the job_id
            assert job_id not in _RANGE_COMPENSATION_RUNS
            # asyncio.sleep should NOT be called!
            mock_sleep.assert_not_called()
            # Task was executed
            mock_service.run_task_with_logs.assert_awaited_once_with("acc1", "task1")


@pytest.mark.asyncio
async def test_sync_jobs_schedules_compensation_for_midday_restart():
    _RANGE_COMPENSATION_RUNS.clear()
    tz = ZoneInfo("Asia/Shanghai")
    # Midday restart at 11:14
    now = datetime(2026, 9, 21, 11, 14, 0, tzinfo=tz)

    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler_mod.scheduler = scheduler

    mock_service = MagicMock()
    mock_service._expand_wildcard_tasks = MagicMock()
    mock_service.list_tasks.return_value = [
        {
            "name": "pixel_task",
            "account_name": "acc1",
            "enabled": True,
            "execution_mode": "range",
            "range_start": "09:00",
            "range_end": "18:00",
            "sign_at": "09:00",
            "last_run": {
                "time": "2026-09-20T10:00:00+08:00",  # run yesterday
                "success": True,
            },
        }
    ]

    with patch("backend.scheduler.instance_lock.has_scheduler_lock", return_value=True):
        with patch("backend.services.sign_tasks.get_sign_task_service", return_value=mock_service):
            with patch("backend.scheduler.datetime") as mock_dt:
                mock_dt.now.side_effect = lambda t=None: now
                mock_dt.strptime = datetime.strptime
                mock_dt.fromisoformat = datetime.fromisoformat

                await sync_jobs()

    job_id = "sign-acc1-pixel_task"
    assert job_id in _RANGE_COMPENSATION_RUNS
    job = scheduler.get_job(job_id)
    assert job is not None
    # Verify next_run_time was modified to compensation time within today's window
    assert job.next_run_time == _RANGE_COMPENSATION_RUNS[job_id]
    assert now <= job.next_run_time <= datetime(2026, 9, 21, 18, 0, 0, tzinfo=tz)

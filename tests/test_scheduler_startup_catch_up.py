"""固定时间任务启动补跑测试。

覆盖:
- 只挑出「今天计划时刻已过且今天没有成功记录」的 fixed 任务
- range/listen/禁用/尚未到点/今天无计划的任务不补跑
- 补跑经 _job_run_sign_task → run_task_with_logs(force=False)，受 BP-2 当日去重门约束
- 未持有调度锁时跳过
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

import backend.scheduler as scheduler_mod
from backend.scheduler import (
    _compute_catch_up_tasks,
    _last_scheduled_fire_time,
    run_startup_catch_up,
)

TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 9, 21, 10, 0, 0, tzinfo=TZ)


@pytest.fixture(autouse=True)
def _reset_catch_up_state(monkeypatch):
    monkeypatch.setattr(scheduler_mod, "_CATCH_UP_STARTED", False)


def _fixed_task(**overrides):
    task = {
        "name": "daily_checkin",
        "account_name": "acc",
        "enabled": True,
        "execution_mode": "fixed",
        "sign_at": "09:00",
    }
    task.update(overrides)
    return task


def _svc(tasks, history=None):
    svc = MagicMock()
    svc.list_tasks.return_value = tasks
    svc.get_task.return_value = tasks[0] if tasks else None
    svc.get_task_history.return_value = history or []
    svc.run_task_with_logs = AsyncMock(return_value={"success": True})
    return svc


def test_last_scheduled_fire_time():
    assert _last_scheduled_fire_time("09:00", now=NOW) == datetime(
        2026, 9, 21, 9, 0, 0, tzinfo=TZ
    )
    # 今天尚未到点 → 没有已过去的计划时刻
    assert _last_scheduled_fire_time("23:00", now=NOW) is None
    # 每周一次且今天不是计划日 → 今天没有计划
    assert _last_scheduled_fire_time("0 9 * * 1", now=NOW) is None
    # 非法表达式静默跳过
    assert _last_scheduled_fire_time("not-a-cron", now=NOW) is None
    # offset-naive now 兼容带时区 trigger，不会抛出 TypeError
    naive_now = datetime(2026, 9, 21, 10, 0, 0)
    res = _last_scheduled_fire_time("09:00", now=naive_now)
    assert res is not None
    assert res.hour == 9 and res.minute == 0


def test_compute_catch_up_tasks_selects_only_missed_fixed_tasks():
    tasks = [
        _fixed_task(),
        _fixed_task(
            name="already_done", last_run={"success": True, "time": NOW.isoformat()}
        ),
        _fixed_task(name="not_yet", sign_at="23:00"),
        _fixed_task(name="range_task", execution_mode="range"),
        _fixed_task(name="listen_task", execution_mode="listen"),
        _fixed_task(name="disabled", enabled=False),
        _fixed_task(name="weekly", sign_at="0 9 * * 1"),
    ]
    candidates = _compute_catch_up_tasks(_svc(tasks), tasks, now=NOW)

    assert [c["name"] for c in candidates] == ["daily_checkin"]
    assert (
        candidates[0]["scheduled_at"]
        == datetime(2026, 9, 21, 9, 0, 0, tzinfo=TZ).isoformat()
    )


def test_compute_catch_up_tasks_uses_history_success():
    tasks = [_fixed_task()]
    svc = _svc(tasks, history=[{"success": True, "time": NOW.isoformat()}])
    assert _compute_catch_up_tasks(svc, tasks, now=NOW) == []


@pytest.mark.asyncio
async def test_startup_catch_up_runs_missed_task_through_force_false_gate():
    tasks = [_fixed_task()]
    svc = _svc(tasks)

    with (
        patch("backend.services.sign_tasks.get_sign_task_service", return_value=svc),
        patch("backend.scheduler.instance_lock.has_scheduler_lock", return_value=True),
        patch("backend.scheduler._resolve_scheduler_timezone", return_value=TZ),
        patch("backend.scheduler.datetime") as mock_dt,
    ):
        mock_dt.now.side_effect = lambda t=None: NOW
        mock_dt.fromisoformat = datetime.fromisoformat
        ran = await run_startup_catch_up(delay_seconds=0, now=NOW)

    assert [item["name"] for item in ran] == ["daily_checkin"]
    # 补跑走非手动路径：force=False 才会命中 BP-2 的当日去重门
    svc.run_task_with_logs.assert_awaited_once_with("acc", "daily_checkin", force=False)


@pytest.mark.asyncio
async def test_startup_catch_up_logs_task_and_reason(caplog):
    tasks = [_fixed_task()]
    svc = _svc(tasks)

    with (
        patch("backend.services.sign_tasks.get_sign_task_service", return_value=svc),
        patch("backend.scheduler.instance_lock.has_scheduler_lock", return_value=True),
        patch("backend.scheduler._resolve_scheduler_timezone", return_value=TZ),
        caplog.at_level("INFO", logger="backend.scheduler"),
    ):
        ran = await run_startup_catch_up(delay_seconds=0, now=NOW)

    assert [item["name"] for item in ran] == ["daily_checkin"]
    assert any(
        "启动补跑任务 daily_checkin" in rec.message and "依据" in rec.message
        for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_startup_catch_up_does_not_run_when_already_succeeded_today():
    tasks = [
        _fixed_task(
            last_run={"success": True, "time": NOW.isoformat()},
        )
    ]
    svc = _svc(tasks)

    with (
        patch("backend.services.sign_tasks.get_sign_task_service", return_value=svc),
        patch("backend.scheduler.instance_lock.has_scheduler_lock", return_value=True),
        patch("backend.scheduler._resolve_scheduler_timezone", return_value=TZ),
    ):
        ran = await run_startup_catch_up(delay_seconds=0, now=NOW)

    assert ran == []
    svc.run_task_with_logs.assert_not_awaited()


@pytest.mark.asyncio
async def test_startup_catch_up_skipped_without_scheduler_lock():
    tasks = [_fixed_task()]
    svc = _svc(tasks)

    with (
        patch("backend.services.sign_tasks.get_sign_task_service", return_value=svc),
        patch("backend.scheduler.instance_lock.has_scheduler_lock", return_value=False),
    ):
        ran = await run_startup_catch_up(delay_seconds=0, now=NOW)

    assert ran == []
    svc.run_task_with_logs.assert_not_awaited()

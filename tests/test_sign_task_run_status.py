"""运行状态纯函数测试。"""
from __future__ import annotations

from backend.services.sign_task_run_status import (
    PHASE_COOLDOWN,
    PHASE_STARTING,
    RUN_STATE_FINISHED,
    RUN_STATE_RUNNING,
    RUN_STATE_TIMEOUT,
    build_run_status,
    build_runner_failure_result,
    idle_running_placeholder,
    is_timeout_error_message,
    make_task_key,
    resolve_effective_retry_count,
    resolve_stored_run_status,
    summarize_active_run,
)


def test_make_task_key():
    assert make_task_key("a", "t") == ("a", "t")
    assert make_task_key(None, None) == ("", "")  # type: ignore[arg-type]


def test_build_run_status_defaults():
    st = build_run_status(
        run_id="r1",
        state="running",
        default_started_at="2026-01-01T00:00:00Z",
    )
    assert st["run_id"] == "r1"
    assert st["state"] == "running"
    assert st["started_at"] == "2026-01-01T00:00:00Z"
    assert st["finished_at"] is None
    assert st["success"] is None
    assert st["phase"] == PHASE_STARTING


def test_build_run_status_terminal_clears_phase():
    st = build_run_status(
        run_id="r1",
        state=RUN_STATE_FINISHED,
        phase=PHASE_COOLDOWN,
        success=True,
        default_started_at="t0",
    )
    assert st["phase"] is None
    assert st["success"] is True


def test_build_run_status_timeout_and_fields():
    st = build_run_status(
        run_id="r1",
        state=RUN_STATE_TIMEOUT,
        success=False,
        error="任务执行超时（30秒），已强制终止",
        failure_category="timeout",
        timeout_seconds=30,
        retry_count_effective=2,
        account_name="acc",
        task_name="daily",
        default_started_at="t0",
    )
    assert st["state"] == RUN_STATE_TIMEOUT
    assert st["failure_category"] == "timeout"
    assert st["timeout_seconds"] == 30
    assert st["retry_count_effective"] == 2
    assert st["account_name"] == "acc"
    assert st["phase"] is None


def test_idle_running_placeholder():
    st = idle_running_placeholder(started_at="t0")
    assert st["state"] == "running"
    assert st["run_id"] == ""
    assert st["started_at"] == "t0"
    assert st["phase"] == PHASE_STARTING


def test_resolve_stored_run_status_idle_and_stale():
    idle = resolve_stored_run_status(None, requested_run_id="r1")
    assert idle["state"] == "idle"
    assert idle["run_id"] == "r1"

    current = build_run_status(run_id="r2", state="finished", default_started_at="t")
    stale = resolve_stored_run_status(current, requested_run_id="r1")
    assert stale["state"] == "stale"
    same = resolve_stored_run_status(current, requested_run_id="r2")
    assert same["state"] == "finished"
    assert same["run_id"] == "r2"


def test_build_runner_failure_result():
    c = build_runner_failure_result(cancelled=True)
    assert c["error"] == "Task execution cancelled"
    assert c["timed_out"] is False
    assert c.get("failure_category") is None
    f = build_runner_failure_result(error="boom")
    assert f["error"] == "boom"
    assert f["success"] is False
    assert f.get("failure_category") is None
    t = build_runner_failure_result(
        error="任务执行超时（10秒），已强制终止",
    )
    assert t["timed_out"] is True
    assert t.get("failure_category") == "timeout"


def test_resolve_terminal_failure_category():
    from backend.services.sign_task_run_status import (
        RUN_STATE_CANCELLED,
        RUN_STATE_FINISHED,
        RUN_STATE_TIMEOUT,
        resolve_terminal_failure_category,
    )

    assert (
        resolve_terminal_failure_category(
            state=RUN_STATE_FINISHED, success=True, error="x"
        )
        is None
    )
    assert (
        resolve_terminal_failure_category(
            state=RUN_STATE_CANCELLED,
            success=False,
            error="Task execution cancelled",
        )
        is None
    )
    assert (
        resolve_terminal_failure_category(
            state=RUN_STATE_TIMEOUT, success=False, error="timeout"
        )
        == "timeout"
    )
    assert (
        resolve_terminal_failure_category(
            state=RUN_STATE_FINISHED,
            success=False,
            result_category="session_invalid",
            error="other",
        )
        == "session_invalid"
    )
    cat = resolve_terminal_failure_category(
        state=RUN_STATE_FINISHED,
        success=False,
        error="invalid session / needs relogin",
    )
    assert cat == "session_invalid"


def test_resolve_effective_retry_count():
    assert resolve_effective_retry_count({}, 5) == 5
    assert resolve_effective_retry_count(None, 4) == 4
    assert resolve_effective_retry_count({"retry_count": 2}, 9) == 2
    assert resolve_effective_retry_count({"retry_count": "7"}, 1) == 7
    assert resolve_effective_retry_count({"retry_count": "bad"}, 3) == 3
    # 夹紧
    assert resolve_effective_retry_count({"retry_count": 999}, 1, max_v=99) == 99


def test_summarize_active_run():
    running = build_run_status(
        run_id="r1",
        state=RUN_STATE_RUNNING,
        phase=PHASE_COOLDOWN,
        phase_detail="冷却 3 秒",
        wait_seconds=3,
        account_name="a",
        task_name="t",
        default_started_at="t0",
    )
    s = summarize_active_run(running)
    assert s is not None
    assert s["phase"] == PHASE_COOLDOWN
    assert s["wait_seconds"] == 3
    assert summarize_active_run(
        build_run_status(run_id="x", state=RUN_STATE_FINISHED, default_started_at="t")
    ) is None


def test_is_timeout_error_message():
    assert is_timeout_error_message("任务执行超时（30秒），已强制终止")
    assert not is_timeout_error_message("按钮未找到")


def test_list_active_runs_and_resolve_for_task():
    """SignTaskService 活跃 run 列表与任务挂载逻辑（不连 Telegram）。"""
    from backend.services.sign_tasks import SignTaskService

    svc = SignTaskService.__new__(SignTaskService)
    svc._run_statuses = {
        ("acc1", "daily"): build_run_status(
            run_id="r1",
            state=RUN_STATE_RUNNING,
            phase=PHASE_COOLDOWN,
            phase_detail="冷却",
            account_name="acc1",
            task_name="daily",
            started_at="2026-07-19T10:00:00+00:00",
            default_started_at="2026-07-19T10:00:00+00:00",
        ),
        ("acc2", "other"): build_run_status(
            run_id="r2",
            state=RUN_STATE_FINISHED,
            success=True,
            account_name="acc2",
            task_name="other",
            default_started_at="t",
        ),
    }

    runs = SignTaskService.list_active_runs(svc)
    assert len(runs) == 1
    assert runs[0]["task_name"] == "daily"
    assert runs[0]["phase"] == PHASE_COOLDOWN

    task = {
        "name": "daily",
        "account_name": "acc1",
        "account_names": ["acc1", "acc2"],
    }
    ar = SignTaskService._resolve_active_run_for_task(svc, task)
    assert ar is not None
    assert ar["run_id"] == "r1"

    attached = SignTaskService._attach_active_runs(svc, [task, {"name": "other", "account_name": "acc2", "account_names": ["acc2"]}])
    assert attached[0]["active_run"] is not None
    assert attached[1]["active_run"] is None


def test_resolve_effective_retry_key_presence_contract():
    """仅键存在才用任务值；缺省键走全局（C3 契约）。"""
    assert resolve_effective_retry_count({"name": "x"}, 5) == 5
    assert resolve_effective_retry_count({"retry_count": 0}, 5) == 0
    assert resolve_effective_retry_count({"retry_count": None}, 5) == 5


def test_cancel_task_run_no_background():
    from backend.services.sign_tasks import SignTaskService

    svc = SignTaskService.__new__(SignTaskService)
    svc._run_statuses = {}
    svc._background_run_tasks = {}
    svc._active_tasks = {}
    svc._active_logs = {}
    res = SignTaskService.cancel_task_run(svc, "acc1", "daily")
    assert res["ok"] is False
    assert res["cancelled"] is False


def test_cancel_task_run_cancels_background():
    from unittest.mock import MagicMock

    from backend.services.sign_tasks import SignTaskService

    svc = SignTaskService.__new__(SignTaskService)
    bg = MagicMock()
    bg.done.return_value = False
    svc._run_statuses = {("acc1", "daily"): {"run_id": "r1", "state": "running"}}
    svc._background_run_tasks = {("acc1", "daily"): bg}
    svc._active_tasks = {("acc1", "daily"): True}
    svc._active_logs = {("acc1", "daily"): []}
    res = SignTaskService.cancel_task_run(svc, "acc1", "daily", run_id="r1")
    assert res["ok"] is True
    assert res["cancelled"] is True
    bg.cancel.assert_called_once()


def test_cancel_task_run_run_id_mismatch():
    from unittest.mock import MagicMock

    from backend.services.sign_tasks import SignTaskService

    svc = SignTaskService.__new__(SignTaskService)
    bg = MagicMock()
    bg.done.return_value = False
    svc._run_statuses = {("acc1", "daily"): {"run_id": "r1", "state": "running"}}
    svc._background_run_tasks = {("acc1", "daily"): bg}
    svc._active_tasks = {("acc1", "daily"): True}
    svc._active_logs = {}
    res = SignTaskService.cancel_task_run(svc, "acc1", "daily", run_id="other")
    assert res["ok"] is False
    assert res["cancelled"] is False
    bg.cancel.assert_not_called()


def test_is_terminal_run_state():
    from backend.services.sign_task_run_status import (
        RUN_STATE_CANCELLED,
        RUN_STATE_FINISHED,
        RUN_STATE_IDLE,
        RUN_STATE_RUNNING,
        RUN_STATE_TIMEOUT,
        is_terminal_run_state,
    )

    assert is_terminal_run_state(RUN_STATE_FINISHED)
    assert is_terminal_run_state(RUN_STATE_CANCELLED)
    assert is_terminal_run_state(RUN_STATE_TIMEOUT)
    assert not is_terminal_run_state(RUN_STATE_RUNNING)
    assert not is_terminal_run_state(RUN_STATE_IDLE)


def test_prune_stale_does_not_drop_terminal_with_finished_at():
    """有 finished_at 的终态由 cleanup 定时器负责，prune 不立刻删。"""
    from backend.services.sign_tasks import SignTaskService

    svc = SignTaskService.__new__(SignTaskService)
    svc._active_tasks = {}
    svc._active_logs = {}
    svc._background_run_tasks = {}
    svc._cleanup_tasks = {}
    svc._run_status_cleanup_tasks = {}
    svc._account_last_run_end = {}
    svc._max_account_last_run_entries = 100
    svc._run_statuses = {
        ("a", "t"): build_run_status(
            run_id="r1",
            state=RUN_STATE_FINISHED,
            success=True,
            finished_at="2026-07-26T00:00:00+00:00",
            default_started_at="t0",
        ),
        ("b", "u"): build_run_status(
            run_id="r2",
            state=RUN_STATE_FINISHED,
            success=False,
            finished_at=None,
            default_started_at="t0",
        ),
    }
    SignTaskService._prune_stale_entries(svc)
    assert ("a", "t") in svc._run_statuses
    assert ("b", "u") not in svc._run_statuses


def test_build_cancel_run_response_and_mismatch():
    from backend.services.sign_task_run_status import (
        build_cancel_run_response,
        is_run_id_mismatch,
    )

    assert is_run_id_mismatch(None, "r1") is False
    assert is_run_id_mismatch({"run_id": "r1"}, None) is False
    assert is_run_id_mismatch({"run_id": "r1"}, "r1") is False
    assert is_run_id_mismatch({"run_id": "r1"}, "r2") is True
    resp = build_cancel_run_response(
        ok=False,
        cancelled=False,
        error="x",
        status={"run_id": "r1", "state": "running"},
        requested_run_id="r2",
    )
    assert resp["ok"] is False
    assert resp["cancelled"] is False
    assert resp["error"] == "x"
    assert resp["status"]["state"] == "stale"


def test_schedule_run_status_cleanup_replacement_survives_old_cancel():
    """旧 run_status 清理任务被取消后，其 finally 不得误删新注册的清理任务（竞态回归）。"""
    import asyncio

    from backend.services.sign_tasks import SignTaskService

    svc = SignTaskService.__new__(SignTaskService)
    svc._active_tasks = {}
    svc._run_statuses = {}
    svc._run_status_cleanup_tasks = {}

    async def scenario():
        svc._schedule_run_status_cleanup("acc", "t")
        first = svc._run_status_cleanup_tasks[("acc", "t")]
        # 让 first 真正启动并悬挂在 sleep(600)，否则取消未启动任务不会执行 finally
        await asyncio.sleep(0)
        assert not first.done()

        # 第二次调度：取消 first 并注册 second
        svc._schedule_run_status_cleanup("acc", "t")
        second = svc._run_status_cleanup_tasks[("acc", "t")]
        assert second is not first

        # 让事件循环处理 first 的取消（CancelledError → finally → pop）
        for _ in range(5):
            await asyncio.sleep(0)

        assert first.cancelled()
        # 竞态 bug 下：second 的条目被 first 的 finally 误删，此处将断言失败
        assert svc._run_status_cleanup_tasks.get(("acc", "t")) is second
        assert not second.done()

        # 收尾：取消 second，避免悬挂任务
        second.cancel()
        for _ in range(3):
            await asyncio.sleep(0)
        assert second.done()

    asyncio.run(scenario())

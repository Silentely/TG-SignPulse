"""运行状态纯函数测试。"""
from __future__ import annotations

from backend.services.sign_task_run_status import (
    build_run_status,
    idle_running_placeholder,
    make_task_key,
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


def test_idle_running_placeholder():
    st = idle_running_placeholder(started_at="t0")
    assert st["state"] == "running"
    assert st["run_id"] == ""
    assert st["started_at"] == "t0"


def test_resolve_stored_run_status_idle_and_stale():
    from backend.services.sign_task_run_status import resolve_stored_run_status

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
    from backend.services.sign_task_run_status import build_runner_failure_result

    c = build_runner_failure_result(cancelled=True)
    assert c["error"] == "Task execution cancelled"
    f = build_runner_failure_result(error="boom")
    assert f["error"] == "boom"
    assert f["success"] is False

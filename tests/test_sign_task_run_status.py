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

"""BackgroundJobStore 状态机与重启恢复测试。"""
import json
from pathlib import Path

from backend.services.background_job import (
    ACTIVE_STATUSES,
    BackgroundJobStore,
    public_job_view,
)


def test_public_job_view_strips_private_keys():
    view = public_job_view({"job_id": "a", "status": "running", "_task": object()})
    assert "job_id" in view
    assert "_task" not in view


def test_create_list_get_and_complete(tmp_path: Path):
    store = BackgroundJobStore(tmp_path / "jobs")
    created = store.create_job(kind="demo", payload={"x": 1}, progress={"total": 2, "done": 0})
    job_id = created["job_id"]
    assert created["status"] == "running"
    assert store.get_job(job_id)["kind"] == "demo"

    store.append_log(job_id, "info", "step 1")
    store.update_progress(job_id, done=1)
    store.mark_completed(job_id, summary={"ok": 1}, results=[{"id": 1}])

    done = store.get_job(job_id)
    assert done["status"] == "completed"
    assert done["summary"]["ok"] == 1
    assert done["progress"]["done"] == 1
    assert any(item["message"] == "step 1" for item in done["logs"])
    assert store.list_jobs(limit=5)[0]["job_id"] == job_id


def test_cancel_request_then_complete_as_canceled(tmp_path: Path):
    store = BackgroundJobStore(tmp_path / "jobs")
    job_id = store.create_job(kind="cancel-demo")["job_id"]
    assert store.request_cancel(job_id) is True
    assert store.is_cancel_requested(job_id) is True
    store.mark_completed(job_id)
    assert store.get_job(job_id)["status"] == "canceled"


def test_mark_failed(tmp_path: Path):
    store = BackgroundJobStore(tmp_path / "jobs")
    job_id = store.create_job(kind="fail-demo")["job_id"]
    store.mark_failed(job_id, "boom")
    job = store.get_job(job_id)
    assert job["status"] == "failed"
    assert job["error"] == "boom"


def test_restart_marks_active_jobs_failed(tmp_path: Path):
    root = tmp_path / "jobs"
    root.mkdir()
    job_id = "abc123"
    path = root / f"{job_id}.json"
    path.write_text(
        json.dumps(
            {
                "job_id": job_id,
                "kind": "bulk",
                "status": "running",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "finished_at": None,
                "progress": {"total": 1, "done": 0},
                "summary": {},
                "results": [],
                "logs": [],
                "error": None,
                "payload": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = BackgroundJobStore(root, restart_error="服务重启，原任务已中断")
    job = store.get_job(job_id)
    assert job is not None
    assert job["status"] == "failed"
    assert job["error"] == "服务重启，原任务已中断"
    assert job["status"] not in ACTIVE_STATUSES


def test_request_cancel_on_terminal_returns_false(tmp_path: Path):
    store = BackgroundJobStore(tmp_path / "jobs")
    job_id = store.create_job(kind="x")["job_id"]
    store.mark_failed(job_id, "done")
    assert store.request_cancel(job_id) is False

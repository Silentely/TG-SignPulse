"""账号状态批量检测 Job 测试。"""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.services import account_status_jobs as jobs_mod
from backend.services.background_job import BackgroundJobStore


@pytest.fixture(autouse=True)
def _reset_store(tmp_path: Path, monkeypatch):
    store = BackgroundJobStore(tmp_path / "jobs")
    monkeypatch.setattr(jobs_mod, "_store", store)
    monkeypatch.setattr(jobs_mod, "get_account_status_job_store", lambda: store)
    yield
    jobs_mod._store = None


@pytest.mark.asyncio
async def test_run_status_check_updates_progress_and_results(tmp_path: Path):
    store = jobs_mod.get_account_status_job_store()
    created = store.create_job(
        kind=jobs_mod.KIND,
        payload={"account_names": ["a", "b"]},
        progress={"total": 2, "done": 0, "ok": 0, "fail": 0},
    )
    job_id = created["job_id"]

    async def _fake_check(name, timeout_seconds=8.0):
        return {
            "account_name": name,
            "ok": name == "a",
            "status": "connected" if name == "a" else "invalid",
            "message": "ok" if name == "a" else "expired",
            "needs_relogin": name != "a",
        }

    with patch("backend.services.telegram.get_telegram_service") as mock_get:
        mock_svc = mock_get.return_value
        mock_svc.check_account_status = AsyncMock(side_effect=_fake_check)
        # 缩短间隔
        with patch.object(jobs_mod, "INTER_DELAY_SECONDS", 0):
            await jobs_mod._run_status_check(job_id, ["a", "b"], 5.0)

    job = store.get_job(job_id)
    assert job["status"] == "completed"
    assert job["summary"]["ok"] == 1
    assert job["summary"]["fail"] == 1
    assert len(job["results"]) == 2


def test_start_rejects_when_already_running(monkeypatch):
    store = jobs_mod.get_account_status_job_store()
    store.create_job(kind=jobs_mod.KIND, progress={"total": 1, "done": 0})

    with patch.object(jobs_mod, "_normalize_names", return_value=["a"]):
        with pytest.raises(ValueError, match="已有批量状态检测"):
            jobs_mod.start_account_status_check_job(account_names=["a"])


def test_normalize_names_dedupe_and_limit(monkeypatch):
    with patch("backend.services.telegram.get_telegram_service") as mock_get:
        mock_get.return_value.list_accounts.return_value = []
        names = jobs_mod._normalize_names(["a", "a", " b ", ""])
        assert names == ["a", "b"]

    with patch("backend.services.telegram.get_telegram_service") as mock_get:
        mock_get.return_value.list_accounts.return_value = []
        with pytest.raises(ValueError, match="最多"):
            jobs_mod._normalize_names([f"acc{i}" for i in range(jobs_mod.MAX_ACCOUNTS + 1)])


def test_normalize_names_rejects_path_segments():
    with patch("backend.services.telegram.get_telegram_service") as mock_get:
        mock_get.return_value.list_accounts.return_value = []
        names = jobs_mod._normalize_names(["ok", "../evil", "a/b", "good"])
        assert names == ["ok", "good"]
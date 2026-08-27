"""新版签到批量操作、失败分类与运维 API 测试。"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from backend.core.auth import create_access_token
from backend.services.sign_task_failure import (
    FailureCategory,
    classify_failure,
    failure_category_label,
    message_indicates_strong_failure,
)


def _auth_headers() -> dict:
    token = create_access_token(
        {"sub": "admin"},
        expires_delta=timedelta(hours=1),
    )
    return {"Authorization": f"Bearer {token}"}


class TestFailureClassification:
    def test_session_invalid(self):
        assert (
            classify_failure(
                error="AUTH_KEY_UNREGISTERED invalid session", success=False
            )
            == FailureCategory.SESSION_INVALID
        )

    def test_flood_wait(self):
        assert (
            classify_failure(error="FloodWait of 30 seconds", success=False)
            == FailureCategory.FLOOD_WAIT
        )

    def test_success_none(self):
        assert classify_failure(error="anything", success=True) == FailureCategory.NONE

    def test_strong_failure_message(self):
        assert message_indicates_strong_failure("签到失败，请稍后重试") is True
        assert message_indicates_strong_failure("签到成功") is False

    def test_label_zh(self):
        assert "会话" in failure_category_label(FailureCategory.SESSION_INVALID)


class TestActiveRunsApi:
    def test_list_active_runs_requires_auth(self, client):
        resp = client.get("/api/sign-tasks/runs/active")
        assert resp.status_code in (401, 403)

    def test_cancel_run_not_running(self, client, db_session):
        service = MagicMock()
        service.get_task.return_value = {
            "name": "daily",
            "account_name": "acc1",
            "account_names": ["acc1"],
        }
        service.cancel_task_run.return_value = {
            "ok": False,
            "cancelled": False,
            "error": "当前没有进行中的运行",
            "status": {"state": "idle", "run_id": ""},
        }
        with patch(
            "backend.api.routes.sign_tasks_v2.get_sign_task_service",
            return_value=service,
        ):
            resp = client.post(
                "/api/sign-tasks/daily/run/cancel",
                headers=_auth_headers(),
                params={"account_name": "acc1"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["cancelled"] is False
        service.cancel_task_run.assert_called_once()

    def test_cancel_run_ok(self, client, db_session):
        service = MagicMock()
        service.get_task.return_value = {
            "name": "daily",
            "account_name": "acc1",
            "account_names": ["acc1"],
        }
        service.cancel_task_run.return_value = {
            "ok": True,
            "cancelled": True,
            "error": "",
            "status": {"state": "running", "run_id": "r1", "phase": "running"},
        }
        with patch(
            "backend.api.routes.sign_tasks_v2.get_sign_task_service",
            return_value=service,
        ):
            resp = client.post(
                "/api/sign-tasks/daily/run/cancel",
                headers=_auth_headers(),
                params={"account_name": "acc1", "run_id": "r1"},
            )
        assert resp.status_code == 200
        assert resp.json()["cancelled"] is True

    def test_list_active_runs_ok(self, client, db_session):
        service = MagicMock()
        service.list_active_runs.return_value = [
            {
                "run_id": "r1",
                "state": "running",
                "phase": "cooldown",
                "phase_detail": "等待账号冷却 3 秒",
                "account_name": "acc1",
                "task_name": "daily",
                "started_at": "2026-07-19T10:00:00+00:00",
                "wait_seconds": 3,
            }
        ]
        with patch(
            "backend.api.routes.sign_tasks_v2.get_sign_task_service",
            return_value=service,
        ):
            resp = client.get(
                "/api/sign-tasks/runs/active",
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "runs" in body
        assert len(body["runs"]) == 1
        assert body["runs"][0]["phase"] == "cooldown"
        assert body["runs"][0]["task_name"] == "daily"

    def test_run_status_schema_fields(self, client, db_session):
        service = MagicMock()
        service.get_task.return_value = {
            "name": "daily",
            "account_name": "acc1",
            "account_names": ["acc1"],
        }
        service.get_task_run_status.return_value = {
            "run_id": "r9",
            "state": "running",
            "phase": "waiting_lock",
            "phase_detail": "等待账号锁 acc1",
            "wait_seconds": None,
            "account_name": "acc1",
            "task_name": "daily",
            "success": None,
            "error": "",
            "output": "",
            "started_at": "t0",
            "finished_at": None,
            "failure_category": None,
            "timeout_seconds": 300,
            "retry_count_effective": 2,
        }
        with patch(
            "backend.api.routes.sign_tasks_v2.get_sign_task_service",
            return_value=service,
        ):
            resp = client.get(
                "/api/sign-tasks/daily/run/status",
                headers=_auth_headers(),
                params={"account_name": "acc1"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["phase"] == "waiting_lock"
        assert data["retry_count_effective"] == 2
        assert data["timeout_seconds"] == 300


class TestSignBatchApi:
    def test_batch_enable_sign_tasks(self, client, db_session):
        """批量 enable 应调用 SignTaskService.update_task。"""
        service = MagicMock()
        service.get_task.return_value = {
            "name": "daily",
            "account_name": "acc1",
            "account_names": ["acc1"],
            "enabled": False,
        }
        service.update_task.return_value = {"name": "daily", "enabled": True}

        with (
            patch(
                "backend.api.routes.batch.get_sign_task_service",
                return_value=service,
            ),
            patch(
                "backend.api.routes.batch.sync_jobs",
                new_callable=AsyncMock,
            ),
            patch(
                "backend.api.routes.batch._restart_keyword_monitors",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.post(
                "/api/batch/sign-tasks",
                headers=_auth_headers(),
                json={
                    "action": "enable",
                    "tasks": [{"name": "daily", "account_name": "acc1"}],
                },
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success_count"] == 1
        assert body["fail_count"] == 0
        service.update_task.assert_called()

    def test_batch_missing_task(self, client, db_session):
        service = MagicMock()
        service.get_task.return_value = None

        with patch(
            "backend.api.routes.batch.get_sign_task_service",
            return_value=service,
        ):
            resp = client.post(
                "/api/batch/sign-tasks",
                headers=_auth_headers(),
                json={
                    "action": "disable",
                    "tasks": [{"name": "nope"}],
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["fail_count"] == 1
        assert body["results"][0]["message"] == "任务不存在"

    def test_legacy_batch_route_removed(self, client, db_session):
        resp = client.post(
            "/api/batch/tasks",
            headers=_auth_headers(),
            json={"action": "enable", "task_ids": [1]},
        )
        assert resp.status_code in {404, 405}


class TestOpsApi:
    def test_scheduled_jobs(self, client, db_session):
        with patch("backend.scheduler.scheduler", None):
            resp = client.get("/api/ops/scheduled-jobs", headers=_auth_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["jobs"] == []

    def test_backup_status(self, client, db_session):
        resp = client.get("/api/ops/backup/status", headers=_auth_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert "data_dir" in body
        assert "recommended_paths" in body
        assert isinstance(body["entries"], list)

    def test_backup_status_tolerates_ghost_backup_file(self, client, db_session, monkeypatch):
        """glob 与 stat 之间备份文件被并发删除时接口不 500，跳过该文件。"""
        from pathlib import Path as _Path

        from backend.core.config import get_settings

        backup_dir = _Path(get_settings().resolve_base_dir()) / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        real_glob = _Path.glob

        def fake_glob(self, pattern):
            if pattern == "auto-*.tar.gz":
                # 返回一个从未落盘的“幽灵”文件：stat 时必抛 FileNotFoundError
                return iter([self / "auto-ghost.tar.gz"])
            return real_glob(self, pattern)

        monkeypatch.setattr(_Path, "glob", fake_glob)
        resp = client.get("/api/ops/backup/status", headers=_auth_headers())
        assert resp.status_code == 200
        names = [f["name"] for f in resp.json().get("local_auto_backups", [])]
        assert "auto-ghost.tar.gz" not in names

    def test_dir_size_cached_reuses_within_ttl(self, tmp_path):
        """全量目录大小统计走 TTL 缓存：TTL 内不重扫，过期后重新统计。"""
        from backend.api.routes import ops as ops_mod

        ops_mod._dir_size_cache.clear()
        (tmp_path / "a.bin").write_bytes(b"x" * 10)
        assert ops_mod._dir_size_cached(tmp_path) == 10
        (tmp_path / "b.bin").write_bytes(b"y" * 5)
        assert ops_mod._dir_size_cached(tmp_path) == 10, "TTL 内应返回缓存值"
        key = str(tmp_path)
        ts, _ = ops_mod._dir_size_cache[key]
        ops_mod._dir_size_cache[key] = (ts - 9999, 10)
        assert ops_mod._dir_size_cached(tmp_path) == 15
        ops_mod._dir_size_cache.clear()

    def test_memory_stats(self, client, db_session):
        resp = client.get("/api/ops/memory", headers=_auth_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert "available" in body

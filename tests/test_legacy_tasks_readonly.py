"""旧版 /api/tasks 已完全移除：路由 404，readyz 标记 removed。"""
from __future__ import annotations

from datetime import timedelta

from backend.core.auth import create_access_token


def _auth() -> dict:
    token = create_access_token(
        {"sub": "admin"},
        expires_delta=timedelta(hours=1),
    )
    return {"Authorization": f"Bearer {token}"}


def _gone(status_code: int) -> bool:
    """路由已移除：404，或被 SPA/挂载仅允许部分方法时的 405。"""
    return status_code in {404, 405}


def test_legacy_tasks_routes_gone(client, db_session):
    headers = _auth()
    assert _gone(client.get("/api/tasks", headers=headers).status_code)
    assert _gone(client.get("/api/tasks/legacy-status", headers=headers).status_code)
    assert _gone(
        client.post(
            "/api/tasks",
            headers=headers,
            json={"name": "x", "cron": "0 8 * * *", "enabled": True, "account_id": 1},
        ).status_code
    )
    assert _gone(
        client.post(
            "/api/batch/tasks",
            headers=headers,
            json={"action": "enable", "task_ids": [1]},
        ).status_code
    )


def test_legacy_events_logs_gone(client, db_session):
    """旧版 SSE /api/events/logs 已物理移除。"""
    resp = client.get("/api/events/logs", headers=_auth())
    assert _gone(resp.status_code)


def test_readyz_includes_ops_fields(client, db_session):
    resp = client.get("/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "ready"
    assert "scheduler_lock_held" in body
    assert body.get("legacy_tasks_writable") is False
    assert body.get("legacy_tasks_removed") is True
    assert body.get("scheduler_role") in {"primary", "replica"}
    if body["scheduler_lock_held"]:
        assert body["scheduler_role"] == "primary"
    else:
        assert body["scheduler_role"] == "replica"


def test_runtime_status_requires_auth(client, db_session):
    assert client.get("/api/ops/runtime-status").status_code == 401
    resp = client.get("/api/ops/runtime-status", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert "scheduler_lock_held" in body
    assert "database_is_sqlite" in body
    assert body.get("legacy_tasks_writable") is False

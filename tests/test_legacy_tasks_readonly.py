"""旧版 /api/tasks 只读开关测试。"""
from __future__ import annotations

from datetime import timedelta

from backend.core.auth import create_access_token


def _auth() -> dict:
    token = create_access_token(
        {"sub": "admin"},
        expires_delta=timedelta(hours=1),
    )
    return {"Authorization": f"Bearer {token}"}


def test_legacy_tasks_readonly_blocks_create(client, db_session, monkeypatch):
    monkeypatch.setenv("APP_LEGACY_TASKS_READONLY", "1")
    resp = client.post(
        "/api/tasks",
        headers=_auth(),
        json={
            "name": "x",
            "cron": "0 8 * * *",
            "enabled": True,
            "account_id": 1,
        },
    )
    assert resp.status_code == 410
    assert "sign-tasks" in resp.json()["detail"]


def test_legacy_tasks_list_still_works(client, db_session, monkeypatch):
    monkeypatch.setenv("APP_LEGACY_TASKS_READONLY", "1")
    resp = client.get("/api/tasks", headers=_auth())
    assert resp.status_code == 200
    assert resp.headers.get("deprecation") == "true" or resp.headers.get(
        "Deprecation"
    ) == "true"


def test_legacy_status_endpoint(client, db_session, monkeypatch):
    monkeypatch.setenv("APP_LEGACY_TASKS_READONLY", "1")
    resp = client.get("/api/tasks/legacy-status", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["legacy_writes_allowed"] is False
    assert body["preferred_api"] == "/api/sign-tasks"
    assert "task_count" in body


def test_legacy_batch_tasks_readonly(client, db_session, monkeypatch):
    monkeypatch.setenv("APP_LEGACY_TASKS_READONLY", "1")
    resp = client.post(
        "/api/batch/tasks",
        headers=_auth(),
        json={"action": "enable", "task_ids": [1]},
    )
    assert resp.status_code == 410
    assert "sign-tasks" in resp.json()["detail"]


def test_readyz_includes_ops_fields(client, db_session):
    resp = client.get("/readyz")
    # client fixture 启动完成后应为 ready
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "ready"
    assert "scheduler_lock_held" in body
    assert "legacy_tasks_writable" in body


def test_runtime_status_requires_auth(client, db_session):
    assert client.get("/api/ops/runtime-status").status_code == 401
    resp = client.get("/api/ops/runtime-status", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert "scheduler_lock_held" in body
    assert "database_is_sqlite" in body

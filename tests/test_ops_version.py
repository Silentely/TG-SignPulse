"""版本 API 集成测试。"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from backend.core.auth import create_access_token
from backend.utils.version_info import clear_update_check_cache


def _auth() -> dict:
    token = create_access_token(
        {"sub": "admin"},
        expires_delta=timedelta(hours=1),
    )
    return {"Authorization": f"Bearer {token}"}


def test_version_requires_auth(client, db_session):
    assert client.get("/api/ops/version").status_code == 401


def test_version_check_requires_auth(client, db_session):
    assert client.post("/api/ops/version/check").status_code == 401


def test_version_returns_local_fields(client, db_session, monkeypatch):
    monkeypatch.setenv("APP_VERSION", "2.0.0")
    monkeypatch.setenv("GIT_SHA", "abc123def456")
    monkeypatch.setenv("GIT_BRANCH", "dev")
    monkeypatch.setenv("BUILD_TIME", "2026-07-17T00:00:00Z")
    resp = client.get("/api/ops/version", headers=_auth())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["version"] == "2.0.0"
    assert body["git_sha"] == "abc123def456"
    assert body["git_branch"] == "dev"
    assert body["build_time"] == "2026-07-17T00:00:00Z"
    assert body["python"]
    assert "update_check_enabled" in body
    assert "update_check" not in body


def test_version_check_disabled(client, db_session, monkeypatch):
    clear_update_check_cache()
    monkeypatch.setenv("APP_UPDATE_CHECK", "0")
    monkeypatch.setenv("APP_VERSION", "2.0.0")
    resp = client.post("/api/ops/version/check", headers=_auth())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["version"] == "2.0.0"
    assert body["update_check"]["enabled"] is False
    assert body["update_check"]["update_available"] is False


def test_version_check_success(client, db_session, monkeypatch):
    clear_update_check_cache()
    monkeypatch.setenv("APP_UPDATE_CHECK", "1")
    monkeypatch.setenv("APP_VERSION", "2.0.0")
    remote = {
        "enabled": True,
        "latest_version": "2.5.0",
        "latest_url": "https://github.com/Silentely/TG-SignPulse/releases/tag/v2.5.0",
        "update_available": True,
        "checked_at": "2026-07-17T12:00:00+00:00",
        "error": None,
        "source": "github_releases",
        "cached": False,
    }
    with patch(
        "backend.utils.version_info.check_remote_update",
        return_value=remote,
    ) as mocked:
        resp = client.post(
            "/api/ops/version/check?force=true",
            headers=_auth(),
        )
        mocked.assert_called_once_with(force=True)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["update_check"]["latest_version"] == "2.5.0"
    assert body["update_check"]["update_available"] is True


def test_version_check_soft_fail(client, db_session, monkeypatch):
    clear_update_check_cache()
    monkeypatch.setenv("APP_UPDATE_CHECK", "1")
    remote = {
        "enabled": True,
        "latest_version": None,
        "latest_url": None,
        "update_available": False,
        "checked_at": "2026-07-17T12:00:00+00:00",
        "error": "timeout",
        "source": "github_releases",
        "cached": False,
    }
    with patch(
        "backend.utils.version_info.check_remote_update",
        return_value=remote,
    ):
        resp = client.post("/api/ops/version/check", headers=_auth())
    assert resp.status_code == 200
    assert resp.json()["update_check"]["error"] == "timeout"
    assert resp.json()["update_check"]["update_available"] is False

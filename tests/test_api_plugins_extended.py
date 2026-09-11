from datetime import datetime
import os
from pathlib import Path
import tempfile
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.core.auth import get_current_user
from backend.models.user import User
from tg_signer.core.plugins import PluginRegistry

client = TestClient(app)


def mock_admin_user():
    return User(username="admin")


@pytest.fixture(autouse=True)
def override_user():
    app.dependency_overrides[get_current_user] = mock_admin_user
    yield
    app.dependency_overrides.clear()


def test_api_list_plugins_metadata():
    resp = client.get("/api/plugins")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 4

    math_plugin = next((p for p in data if p["name"] == "math_solver"), None)
    assert math_plugin is not None
    assert math_plugin["version"] == "1.0.0"
    assert math_plugin["updated_at"] == "2026-09-11"
    assert math_plugin["author"] == "TG-SignPulse Team"


def test_api_get_plugin_source_success():
    resp = client.get("/api/plugins/math_solver/source")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "math_solver"
    assert data["version"] == "1.0.0"
    assert data["builtin"] is True
    assert "solve_math_challenge" in data["source"]


def test_api_get_plugin_source_not_found():
    resp = client.get("/api/plugins/non_existent_plugin_xyz/source")
    assert resp.status_code == 404


def test_api_delete_builtin_forbidden():
    resp = client.delete("/api/plugins/math_solver")
    assert resp.status_code == 403
    assert "内置插件" in resp.json()["detail"]


def test_api_create_and_delete_custom_plugin():
    # 1. Create a custom plugin
    payload = {
        "name": "test_created_plugin",
        "mode": "reactive",
        "template": "basic_reactive",
        "description": "单元测试生成的插件",
        "author": "Tester",
        "version": "1.0.0",
    }
    create_resp = client.post("/api/plugins/create", json=payload)
    assert create_resp.status_code == 200, create_resp.text
    created_info = create_resp.json()
    assert created_info["name"] == "test_created_plugin"
    assert created_info["version"] == "1.0.0"
    assert created_info["author"] == "Tester"
    assert created_info["builtin"] is False

    # 2. Verify it shows in list_plugins
    list_resp = client.get("/api/plugins")
    assert any(p["name"] == "test_created_plugin" for p in list_resp.json())

    # 3. Read source
    src_resp = client.get("/api/plugins/test_created_plugin/source")
    assert src_resp.status_code == 200
    assert "test_created_plugin_handler" in src_resp.json()["source"]

    # 4. Delete custom plugin
    del_resp = client.delete("/api/plugins/test_created_plugin")
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True

    # 5. Verify it is removed from list
    list_resp2 = client.get("/api/plugins")
    assert not any(p["name"] == "test_created_plugin" for p in list_resp2.json())

import pytest
from fastapi.testclient import TestClient

from backend.core.auth import get_current_user
from backend.main import app
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


def test_api_get_plugin_diagnostics():
    from tg_signer.core.plugins import PluginLoadError
    # Clear and test clean state
    resp = client.get("/api/plugins/diagnostics")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_loaded" in data
    assert "total_errors" in data
    assert "load_errors" in data
    assert isinstance(data["load_errors"], list)

    # Simulate an error in PluginRegistry
    PluginRegistry._load_errors["/tmp/fake_plugin.py"] = PluginLoadError(
        file_path="/tmp/fake_plugin.py",
        plugin_name="fake_plugin",
        error_type="missing_dependency",
        error_message="缺少依赖模块 'bs4'",
        missing_module="bs4",
        suggested_command="pip install bs4",
        timestamp="2026-09-11 19:30:00",
    )
    resp2 = client.get("/api/plugins/diagnostics")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["total_errors"] >= 1
    fake_err = next((e for e in data2["load_errors"] if e["plugin_name"] == "fake_plugin"), None)
    assert fake_err is not None
    assert fake_err["missing_module"] == "bs4"
    assert fake_err["suggested_command"] == "pip install bs4"

    # Clean up
    PluginRegistry._load_errors.pop("/tmp/fake_plugin.py", None)


def test_api_test_plugin_with_reset_storage():
    resp = client.post(
        "/api/plugins/math_solver/test",
        json={
            "text": "计算 5+5 等于多少",
            "params": {},
            "reset_storage": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "math_solver"
    assert data["mode"] == "reactive"
    assert any("已清空该插件测试命名空间持久化存储" in log for log in data["logs"])


def test_api_plugin_metrics_recording():
    # Run test on math_solver and verify metrics updated
    PluginRegistry.reset_metrics("math_solver")
    m_before = PluginRegistry.get_metrics("math_solver")
    assert m_before is None

    resp = client.post(
        "/api/plugins/math_solver/test",
        json={"text": "计算 10+20", "params": {}},
    )
    assert resp.status_code == 200

    m_after = PluginRegistry.get_metrics("math_solver")
    assert m_after is not None
    assert m_after.run_count >= 1
    assert m_after.success_count >= 1
    assert m_after.success_rate == 100.0
    assert m_after.last_duration_ms > 0

    # Also verify metrics returned in list_plugins
    list_resp = client.get("/api/plugins")
    assert list_resp.status_code == 200
    math_info = next((p for p in list_resp.json() if p["name"] == "math_solver"), None)
    assert math_info is not None
    assert math_info["metrics"] is not None
    assert math_info["metrics"]["run_count"] >= 1


def test_api_plugin_export():
    resp = client.get("/api/plugins/math_solver/export")
    assert resp.status_code == 200
    assert "attachment; filename=\"math_solver.py\"" in resp.headers.get("content-disposition", "")
    assert "@PluginRegistry.register" in resp.text

    # Non-existent plugin
    resp_404 = client.get("/api/plugins/non_existent_plugin_xyz/export")
    assert resp_404.status_code == 404


def test_api_plugin_upload_and_validation():
    # 1. Invalid file extension
    resp_bad_ext = client.post(
        "/api/plugins/upload",
        files={"file": ("plugin.txt", b"print('hello')", "text/plain")},
    )
    assert resp_bad_ext.status_code == 400
    assert "仅支持上传 .py" in resp_bad_ext.json()["detail"]

    # 2. Syntax error
    resp_syntax = client.post(
        "/api/plugins/upload",
        files={"file": ("syntax_bad.py", b"def broken(: pass", "text/x-python")},
    )
    assert resp_syntax.status_code == 400
    assert "Python 语法错误" in resp_syntax.json()["detail"]

    # 3. Valid plugin upload
    valid_code = b'''"""Uploaded test plugin"""
from tg_signer.core.plugins import PluginContext, PluginRegistry

@PluginRegistry.register(name="uploaded_test_plug", description="Test upload")
async def uploaded_test_plug_handler(ctx: PluginContext) -> bool:
    return True
'''
    resp_ok = client.post(
        "/api/plugins/upload",
        files={"file": ("uploaded_test_plug.py", valid_code, "text/x-python")},
    )
    assert resp_ok.status_code == 200
    data = resp_ok.json()
    assert data["name"] == "uploaded_test_plug"

    # Cleanup: delete uploaded plugin
    del_resp = client.delete("/api/plugins/uploaded_test_plug")
    assert del_resp.status_code == 200


def test_api_test_plugin_with_advanced_context():
    resp = client.post(
        "/api/plugins/math_solver/test",
        json={
            "text": "计算 3*7",
            "chat_id": -10099887766,
            "sender_name": "AliceSuper",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True


def test_api_update_plugin_source_for_custom_plugin():
    client.delete("/api/plugins/editable_plug")
    create_resp = client.post(
        "/api/plugins/create",
        json={"name": "editable_plug", "mode": "reactive", "template": "basic_reactive", "description": "Original"},
    )
    assert create_resp.status_code == 200

    new_source = '''"""Edited description"""
from tg_signer.core.plugins import PluginContext, PluginRegistry

@PluginRegistry.register(name="editable_plug", description="Updated description")
async def editable_plug_handler(ctx: PluginContext) -> bool:
    ctx.reply_text = "edited_hello"
    return True
'''
    put_resp = client.put(
        "/api/plugins/editable_plug/source",
        json={"source": new_source},
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["description"] == "Updated description"

    src_resp = client.get("/api/plugins/editable_plug/source")
    assert src_resp.status_code == 200
    assert "edited_hello" in src_resp.json()["source"]

    del_resp = client.delete("/api/plugins/editable_plug")
    assert del_resp.status_code == 200


def test_api_update_plugin_source_builtin_rejected():
    resp = client.put(
        "/api/plugins/math_solver/source",
        json={"source": "print('fail')"},
    )
    assert resp.status_code == 403
    assert "内置" in resp.json()["detail"]


def test_api_update_plugin_source_syntax_error():
    client.delete("/api/plugins/syntax_err_plug")
    create_resp = client.post(
        "/api/plugins/create",
        json={"name": "syntax_err_plug", "mode": "reactive", "template": "basic_reactive"},
    )
    assert create_resp.status_code == 200

    resp = client.put(
        "/api/plugins/syntax_err_plug/source",
        json={"source": "def syntax_err(: pass"},
    )
    assert resp.status_code == 400
    assert "Python 语法错误" in resp.json()["detail"]

    client.delete("/api/plugins/syntax_err_plug")


def test_api_reset_plugin_metrics():
    from tg_signer.core.plugins import PluginRegistry

    PluginRegistry.record_execution("math_solver", success=True, duration_ms=10.0)
    metrics = PluginRegistry.get_metrics("math_solver")
    assert metrics.run_count >= 1

    resp = client.post("/api/plugins/math_solver/reset-metrics")
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    reset_metrics = PluginRegistry.get_metrics("math_solver")
    assert reset_metrics is None

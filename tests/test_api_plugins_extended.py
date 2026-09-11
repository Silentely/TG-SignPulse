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


def test_api_create_plugin_with_new_templates():
    client.delete("/api/plugins/plug_regex")
    client.delete("/api/plugins/plug_webhook")

    # 1. regex_extractor template
    resp1 = client.post(
        "/api/plugins/create",
        json={
            "name": "plug_regex",
            "mode": "reactive",
            "template": "regex_extractor",
            "description": "正则提取测试",
        },
    )
    assert resp1.status_code == 200
    src1 = client.get("/api/plugins/plug_regex/source").json()
    assert "re.search" in src1["source"]
    assert "pattern" in src1["source"]

    # 2. webhook_alert template
    resp2 = client.post(
        "/api/plugins/create",
        json={
            "name": "plug_webhook",
            "mode": "reactive",
            "template": "webhook_alert",
            "description": "Webhook推送测试",
        },
    )
    assert resp2.status_code == 200
    src2 = client.get("/api/plugins/plug_webhook/source").json()
    assert "urllib.request" in src2["source"]
    assert "network" in src2["source"]

    # cleanup
    client.delete("/api/plugins/plug_regex")
    client.delete("/api/plugins/plug_webhook")


def test_api_batch_toggle_custom_plugins():
    client.delete("/api/plugins/batch_p1")
    client.delete("/api/plugins/batch_p2")

    client.post(
        "/api/plugins/create",
        json={"name": "batch_p1", "mode": "reactive", "template": "basic_reactive"},
    )
    client.post(
        "/api/plugins/create",
        json={"name": "batch_p2", "mode": "reactive", "template": "basic_reactive"},
    )

    # 1. Disable all
    resp_disable = client.post("/api/plugins/batch-toggle", json={"enabled": False})
    assert resp_disable.status_code == 200
    assert resp_disable.json()["enabled"] is False

    list_resp = client.get("/api/plugins").json()
    p1 = next((p for p in list_resp if p["name"] == "batch_p1"), None)
    p2 = next((p for p in list_resp if p["name"] == "batch_p2"), None)
    assert p1 is not None and p1["enabled"] is False
    assert p2 is not None and p2["enabled"] is False

    # 2. Enable all
    resp_enable = client.post("/api/plugins/batch-toggle", json={"enabled": True})
    assert resp_enable.status_code == 200
    assert resp_enable.json()["enabled"] is True

    list_resp2 = client.get("/api/plugins").json()
    p1_active = next((p for p in list_resp2 if p["name"] == "batch_p1"), None)
    p2_active = next((p for p in list_resp2 if p["name"] == "batch_p2"), None)
    assert p1_active is not None and p1_active["enabled"] is True
    assert p2_active is not None and p2_active["enabled"] is True

    client.delete("/api/plugins/batch_p1")
    client.delete("/api/plugins/batch_p2")


def test_api_reset_all_metrics():
    from tg_signer.core.plugins import PluginRegistry

    PluginRegistry.record_execution("math_solver", success=True, duration_ms=5.0)
    assert PluginRegistry.get_metrics("math_solver") is not None

    resp = client.post("/api/plugins/reset-all-metrics")
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    assert PluginRegistry.get_metrics("math_solver") is None


def test_plugin_registry_execution_history():
    from tg_signer.core.plugins import PluginRegistry

    PluginRegistry.reset_metrics("math_solver")
    PluginRegistry.record_execution(
        "math_solver",
        duration_ms=15.5,
        success=True,
        trigger_type="manual_test",
        log_summary="运行正常",
    )
    PluginRegistry.record_execution(
        "math_solver",
        duration_ms=30.0,
        success=False,
        error="模拟异常",
        trigger_type="manual_test",
        log_summary="报错中断",
    )

    history = PluginRegistry.get_execution_history("math_solver")
    assert len(history) == 2
    # latest first
    assert history[0].success is False
    assert history[0].error == "模拟异常"
    assert history[0].log_summary == "报错中断"
    assert history[1].success is True
    assert history[1].duration_ms == 15.5

    # API test
    resp = client.get("/api/plugins/math_solver/history")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "math_solver"
    assert len(data["history"]) == 2

    # Reset
    PluginRegistry.reset_metrics("math_solver")
    assert len(PluginRegistry.get_execution_history("math_solver")) == 0


def test_api_clone_plugin():
    client.delete("/api/plugins/plug_orig")
    client.delete("/api/plugins/plug_copied")

    # 1. Create source plugin
    resp_create = client.post(
        "/api/plugins/create",
        json={"name": "plug_orig", "mode": "reactive", "template": "basic_reactive", "description": "源插件"},
    )
    assert resp_create.status_code == 200

    # 2. Clone to new plugin
    resp_clone = client.post(
        "/api/plugins/plug_orig/clone",
        json={"new_name": "plug_copied", "description": "克隆出来的副插件"},
    )
    assert resp_clone.status_code == 200
    copied_info = resp_clone.json()
    assert copied_info["name"] == "plug_copied"
    assert copied_info["description"] == "克隆出来的副插件"
    assert copied_info["builtin"] is False

    # Check source code of cloned plugin
    src_resp = client.get("/api/plugins/plug_copied/source").json()
    assert "plug_copied" in src_resp["source"]

    # 3. Conflict check (cloning again to the same name)
    resp_conflict = client.post(
        "/api/plugins/plug_orig/clone",
        json={"new_name": "plug_copied"},
    )
    assert resp_conflict.status_code == 409

    # cleanup
    client.delete("/api/plugins/plug_orig")
    client.delete("/api/plugins/plug_copied")


def test_api_plugin_dependencies_inspector():
    from pathlib import Path
    from tg_signer.core.plugins import PluginRegistry

    client.delete("/api/plugins/plug_deps_test")

    source_code = '''"""依赖体检插件"""
import json
import sys
import pytest
from imaginary_missing_lib import some_func
from tg_signer.core.plugins import PluginContext, PluginRegistry

@PluginRegistry.register(name="plug_deps_test", mode="reactive")
async def plug_deps_test_handler(ctx: PluginContext) -> bool:
    return True
'''
    custom_dir = Path.cwd() / "data" / "plugins"
    custom_dir.mkdir(parents=True, exist_ok=True)
    file_path = custom_dir / "plug_deps_test.py"
    file_path.write_text(source_code, encoding="utf-8")

    PluginRegistry.reload_all_plugins()

    resp = client.get("/api/plugins/plug_deps_test/dependencies")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "plug_deps_test"
    deps = {d["module"]: d for d in data["dependencies"]}

    # 标准库与本地库被过滤
    assert "json" not in deps
    assert "sys" not in deps
    assert "tg_signer" not in deps

    # 已安装第三方库检测
    assert "pytest" in deps
    assert deps["pytest"]["installed"] is True

    # 未安装缺失依赖检测
    assert "imaginary_missing_lib" in deps
    assert deps["imaginary_missing_lib"]["installed"] is False
    assert "pip install imaginary_missing_lib" in deps["imaginary_missing_lib"]["install_command"]

    # cleanup
    client.delete("/api/plugins/plug_deps_test")


def test_api_plugin_config_and_reset():
    client.delete("/api/plugins/plug_cfg_test")
    client.post(
        "/api/plugins/create",
        json={
            "name": "plug_cfg_test",
            "mode": "reactive",
            "template": "basic_reactive",
            "description": "配置重置测试",
        },
    )

    # 1. 获取默认配置
    get_resp = client.get("/api/plugins/plug_cfg_test/config")
    assert get_resp.status_code == 200
    cfg = get_resp.json()
    assert cfg["params"].get("reply_prefix") == "[自动应答]"
    assert cfg["is_customized"] is False

    # 2. 保存自定义配置
    save_resp = client.put(
        "/api/plugins/plug_cfg_test/config",
        json={"params": {"reply_prefix": "[VIP回复]"}},
    )
    assert save_resp.status_code == 200
    assert save_resp.json()["params"]["reply_prefix"] == "[VIP回复]"
    assert save_resp.json()["is_customized"] is True

    # 3. 重置配置为默认值
    reset_resp = client.post("/api/plugins/plug_cfg_test/reset-config")
    assert reset_resp.status_code == 200
    reset_cfg = reset_resp.json()
    assert reset_cfg["params"].get("reply_prefix") == "[自动应答]"
    assert reset_cfg["is_customized"] is False

    # cleanup
    client.delete("/api/plugins/plug_cfg_test")


def test_api_export_all_and_import_bundle_zip():
    import io
    import zipfile

    # 清理可能残留的测试插件
    client.delete("/api/plugins/bundle_p1")
    client.delete("/api/plugins/bundle_p2")
    client.delete("/api/plugins/bundle_imported")

    # 1. 创建两个自定义插件
    r1 = client.post(
        "/api/plugins/create",
        json={"name": "bundle_p1", "mode": "reactive", "template": "basic_reactive", "description": "插件1"},
    )
    assert r1.status_code == 200
    r2 = client.post(
        "/api/plugins/create",
        json={"name": "bundle_p2", "mode": "active", "template": "basic_active", "description": "插件2"},
    )
    assert r2.status_code == 200

    # 2. 调用全量导出 ZIP
    export_resp = client.get("/api/plugins/export-all")
    assert export_resp.status_code == 200
    assert export_resp.headers["content-type"] == "application/zip"
    assert "filename=" in export_resp.headers.get("content-disposition", "")

    # 检查 ZIP 内容
    zip_bytes = export_resp.content
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        namelist = zf.namelist()
        assert any("bundle_p1" in name for name in namelist)
        assert any("bundle_p2" in name for name in namelist)

    # 3. 构造一个新的 ZIP 包进行批量上传导入测试
    import_buf = io.BytesIO()
    with zipfile.ZipFile(import_buf, "w") as zf:
        code_imported = """\"\"\"从压缩包导入的插件\"\"\"
from tg_signer.core.plugins import PluginContext, PluginRegistry

@PluginRegistry.register(name="bundle_imported", mode="reactive")
async def bundle_imported_handler(ctx: PluginContext) -> bool:
    return True
"""
        zf.writestr("bundle_imported.py", code_imported)

    import_buf.seek(0)
    files = {"file": ("bundle_test.zip", import_buf.getvalue(), "application/zip")}
    import_resp = client.post("/api/plugins/import-bundle", files=files)
    assert import_resp.status_code == 200
    result = import_resp.json()
    assert result["imported_count"] >= 1
    assert "bundle_imported" in result["files"]

    # 确认系统已加载 bundle_imported
    check_resp = client.get("/api/plugins/bundle_imported/source")
    assert check_resp.status_code == 200
    assert check_resp.json()["name"] == "bundle_imported"

    # cleanup
    client.delete("/api/plugins/bundle_p1")
    client.delete("/api/plugins/bundle_p2")
    client.delete("/api/plugins/bundle_imported")


def test_api_check_syntax():
    # 1. 语法正确的代码
    valid_code = """
import os
def hello():
    return "world"
"""
    resp1 = client.post("/api/plugins/check-syntax", json={"source": valid_code})
    assert resp1.status_code == 200
    res1 = resp1.json()
    assert res1["valid"] is True
    assert res1["error"] is None

    # 2. 语法错误的代码（缺少冒号）
    invalid_code = """
def broken_func()
    return 123
"""
    resp2 = client.post("/api/plugins/check-syntax", json={"source": invalid_code})
    assert resp2.status_code == 200
    res2 = resp2.json()
    assert res2["valid"] is False
    assert res2["line"] == 2
    assert "syntax" in res2["error"].lower() or "invalid" in res2["error"].lower()


def test_api_clear_execution_history():
    from tg_signer.core.plugins import PluginRegistry

    # 1. 模拟记录 2 条历史
    PluginRegistry.record_execution("math_solver", duration_ms=12.5, success=True, log_summary="log1")
    PluginRegistry.record_execution("math_solver", duration_ms=30.0, success=False, error="Fail", log_summary="log2")

    # 2. 检查历史存在
    hist = PluginRegistry.get_execution_history("math_solver")
    assert len(hist) >= 2

    # 3. 调用清空历史接口
    resp = client.post("/api/plugins/math_solver/clear-history")
    assert resp.status_code == 200
    res = resp.json()
    assert res["status"] == "ok"
    assert res["cleared_count"] >= 2

    # 4. 确认历史已空
    hist_after = PluginRegistry.get_execution_history("math_solver")
    assert len(hist_after) == 0


def test_api_audit_source():
    # 1. 含有危险函数 eval / os.system 的代码
    risky_code = """
import os

def check():
    os.system("rm -rf /")
    eval("1 + 1")
    exec("pass")
"""
    resp = client.post("/api/plugins/audit-source", json={"source": risky_code})
    assert resp.status_code == 200
    data = resp.json()
    assert data["passed"] is False
    assert len(data["warnings"]) >= 2
    rules = [w["rule"] for w in data["warnings"]]
    assert any("eval" in r or "eval" in w["message"] for r, w in zip(rules, data["warnings"]))
    assert any("os.system" in r or "os.system" in w["message"] for r, w in zip(rules, data["warnings"]))

    # 2. 安全的代码
    safe_code = """
def add(a, b):
    return a + b
"""
    resp_safe = client.post("/api/plugins/audit-source", json={"source": safe_code})
    assert resp_safe.status_code == 200
    data_safe = resp_safe.json()
    assert data_safe["passed"] is True
    assert len(data_safe["warnings"]) == 0


def test_api_plugins_include_doc():
    resp = client.get("/api/plugins")
    assert resp.status_code == 200
    plugins = resp.json()
    assert isinstance(plugins, list)
    assert len(plugins) > 0
    math_p = next((p for p in plugins if p["name"] == "math_solver"), None)
    assert math_p is not None
    # math_solver 应该有模块或函数级 docstring，字段存在
    assert "doc" in math_p


def test_api_test_plugin_timeout():
    import time
    from tg_signer.core.plugins import PluginRegistry

    # 注册一个需要耗时 0.2s 的慢插件
    @PluginRegistry.register(name="slow_sleep_test_p")
    def slow_plugin(ctx):
        time.sleep(0.15)
        return True

    resp = client.post(
        "/api/plugins/slow_sleep_test_p/test",
        json={
            "text": "hi",
            "timeout": 0.05,  # 0.05s < 0.15s，必定超时
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "超时" in (data.get("error") or "")


def test_api_plugins_manifest():
    resp = client.get("/api/plugins/manifest")
    assert resp.status_code == 200
    manifest = resp.json()
    assert isinstance(manifest, list)
    assert len(manifest) > 0
    math_item = next((p for p in manifest if p["name"] == "math_solver"), None)
    assert math_item is not None
    assert "mode" in math_item
    assert "version" in math_item
    assert "enabled" in math_item


def test_api_plugin_recent_results():
    from tg_signer.core.plugins import PluginRegistry

    PluginRegistry.record_execution("math_solver", duration_ms=10.0, success=True)
    PluginRegistry.record_execution("math_solver", duration_ms=20.0, success=False, error="test-fail")

    resp = client.get("/api/plugins")
    assert resp.status_code == 200
    plugins = resp.json()
    math_p = next((p for p in plugins if p["name"] == "math_solver"), None)
    assert math_p is not None
    assert "recent_results" in math_p
    assert isinstance(math_p["recent_results"], list)
    assert len(math_p["recent_results"]) >= 2
    # 最近一次是 False，倒数第二次是 True
    assert math_p["recent_results"][-1] is False
    assert math_p["recent_results"][-2] is True

import pytest
from fastapi import HTTPException
from backend.services.plugin_security_gate import enforce_plugin_security
from backend.core.auth import get_current_user
from backend.main import app
from tg_signer.core.plugins import PluginRegistry

pytest_plugins = ("tests.test_api",)


@pytest.fixture(autouse=True)
def override_current_user():
    class DummyUser:
        id = 1
        username = "admin"
        is_admin = True

    app.dependency_overrides[get_current_user] = lambda: DummyUser()
    yield
    app.dependency_overrides.pop(get_current_user, None)


def test_security_gate_hard_blocks_critical_rules_even_with_force():
    malicious_code = "import os\nos.system('rm -rf /')"

    # 不带 force 抛出 422
    with pytest.raises(HTTPException) as exc_info:
        enforce_plugin_security(malicious_code, force=False)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "PLUGIN_SECURITY_BLOCKED"

    # 关键测试：即使管理员带 force=True 也必须坚决拦截！
    with pytest.raises(HTTPException) as exc_info_force:
        enforce_plugin_security(malicious_code, force=True)
    assert exc_info_force.value.status_code == 422
    assert exc_info_force.value.detail["code"] == "PLUGIN_SECURITY_BLOCKED"


def test_security_gate_hard_blocks_fail_closed_rules():
    # star-import 必须阻断
    star_code = "from shutil import *\nmove('/a', '/b')\n"
    with pytest.raises(HTTPException) as exc_star:
        enforce_plugin_security(star_code, force=True)
    assert exc_star.value.status_code == 422
    assert exc_star.value.detail["code"] == "PLUGIN_SECURITY_BLOCKED"

    # syntax-error 必须阻断
    syntax_code = "def broken(:\n    pass\n"
    with pytest.raises(HTTPException) as exc_syntax:
        enforce_plugin_security(syntax_code, force=True)
    assert exc_syntax.value.status_code == 422
    assert exc_syntax.value.detail["code"] == "PLUGIN_SECURITY_BLOCKED"


def test_security_gate_medium_risk_confirmation():
    # 中危告警：ssl._create_unverified_context
    code_with_warning = (
        "import ssl\n"
        "ctx = ssl._create_unverified_context()\n"
    )
    # force=False 抛出 409
    with pytest.raises(HTTPException) as exc_info:
        enforce_plugin_security(code_with_warning, force=False)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "PLUGIN_SECURITY_CONFIRMATION_REQUIRED"

    # force=True 允许放行
    report = enforce_plugin_security(code_with_warning, force=True)
    assert isinstance(report, dict)
    assert len(report.get("warnings", [])) > 0


def test_security_gate_safe_code_passes():
    safe_code = (
        "from tg_signer.core.plugins import PluginRegistry\n"
        "@PluginRegistry.register('safe_plug', mode='reactive')\n"
        "def safe_handler(ctx):\n"
        "    return True\n"
    )
    report = enforce_plugin_security(safe_code, force=False)
    assert isinstance(report, dict)
    assert report.get("passed") is True


def test_route_put_source_blocks_malicious_code(api_client, tmp_path, monkeypatch):
    custom_dir = tmp_path / "custom_plugins"
    custom_dir.mkdir(parents=True, exist_ok=True)
    plugin_file = custom_dir / "demo_plugin.py"
    safe_code = (
        "from tg_signer.core.plugins import PluginRegistry\n"
        "@PluginRegistry.register('demo_plugin', mode='reactive')\n"
        "def demo_handler(ctx):\n"
        "    return True\n"
    )
    plugin_file.write_text(safe_code, encoding="utf-8")
    monkeypatch.setenv("PLUGINS_DIR", str(custom_dir))

    PluginRegistry.clear()
    PluginRegistry.load_plugins_from_dir(custom_dir)
    assert PluginRegistry.get("demo_plugin") is not None

    payload = {
        "source": "import os\nos.system('rm -rf /')",
        "force": True,
    }
    resp = api_client.put("/api/plugins/demo_plugin/source", json=payload)
    # 门禁坚决返回 422，严禁保存
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "PLUGIN_SECURITY_BLOCKED"
    # 文件源码未被篡改
    assert plugin_file.read_text(encoding="utf-8") == safe_code
    PluginRegistry.reload_all_plugins()

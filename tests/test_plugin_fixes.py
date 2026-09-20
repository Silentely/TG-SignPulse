"""针对插件系统审查问题的回归测试。

覆盖：脚手架/克隆代码注入防护、调试存储命名空间隔离、ZIP 导入路径与布局防护、
上传体积上限、格式化降级标识、注册冲突防护、执行指标口径与覆盖、历史条数约束。
"""
import ast
import io
import zipfile
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.core.auth import get_current_user
from backend.main import app
from backend.models.user import User
from tg_signer.core.plugin_host import PluginProcessHost
from tg_signer.core.plugins import (
    PluginContext,
    PluginMetrics,
    PluginRegistry,
)

client = TestClient(app)


def mock_admin_user():
    return User(username="admin")


@pytest.fixture(autouse=True)
def override_user():
    app.dependency_overrides[get_current_user] = mock_admin_user
    yield
    app.dependency_overrides.clear()


def _cleanup_plugin(name: str) -> None:
    client.delete(f"/api/plugins/{name}")
    PluginRegistry._plugins.pop(name, None)


# ============================================================================
# 后端 API：注入防护
# ============================================================================


def test_api_create_plugin_author_injection_is_neutralized():
    """author 含引号/换行/代码时必须被 repr 转义为字符串字面量，不得成为可执行代码。"""
    _cleanup_plugin("inject_probe")
    malicious_author = 'x"\n__import__("os").system("id")\nY="'
    resp = client.post(
        "/api/plugins/create",
        json={
            "name": "inject_probe",
            "mode": "active",
            "template": "basic_active",
            "author": malicious_author,
            "description": 'desc", __import__("os").system("id"), "x',
        },
    )
    assert resp.status_code == 200

    source = client.get("/api/plugins/inject_probe/source").json()["source"]
    # 生成源码必须可解析，且顶层不存在可执行的 __import__ 调用节点
    tree = ast.parse(source)
    exec_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "__import__"
    ]
    assert not exec_calls
    # 注入载荷仅作为字符串值存在
    assert PluginRegistry.get("inject_probe") is not None
    _cleanup_plugin("inject_probe")


def test_api_create_plugin_duplicate_conflict_returns_409():
    _cleanup_plugin("conflict_probe")
    first = client.post(
        "/api/plugins/create",
        json={"name": "conflict_probe", "mode": "reactive", "template": "basic_reactive"},
    )
    assert first.status_code == 200
    second = client.post(
        "/api/plugins/create",
        json={"name": "conflict_probe", "mode": "reactive", "template": "basic_reactive"},
    )
    assert second.status_code == 409
    _cleanup_plugin("conflict_probe")


def test_api_clone_plugin_description_injection_is_neutralized():
    """克隆时恶意 description 不得脱离字符串字面量注入代码。"""
    _cleanup_plugin("clone_src_probe")
    _cleanup_plugin("clone_dst_probe")
    created = client.post(
        "/api/plugins/create",
        json={"name": "clone_src_probe", "mode": "reactive", "template": "basic_reactive"},
    )
    assert created.status_code == 200

    resp = client.post(
        "/api/plugins/clone_src_probe/clone",
        json={
            "new_name": "clone_dst_probe",
            "description": 'a", x=__import__("os").system("id"), y="',
        },
    )
    assert resp.status_code == 200

    source = client.get("/api/plugins/clone_dst_probe/source").json()["source"]
    tree = ast.parse(source)
    exec_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "__import__"
    ]
    assert not exec_calls
    assert PluginRegistry.get("clone_dst_probe") is not None
    _cleanup_plugin("clone_src_probe")
    _cleanup_plugin("clone_dst_probe")


# ============================================================================
# 后端 API：体积与参数约束
# ============================================================================


def test_api_upload_plugin_oversized_rejected():
    from pathlib import Path

    oversized = b"x" * (2 * 1024 * 1024 + 1)
    resp = client.post(
        "/api/plugins/upload",
        files={"file": ("oversized_plug.py", oversized, "text/x-python")},
    )
    assert resp.status_code == 413
    # 不应留下半截文件
    assert not (Path.cwd() / "data" / "plugins" / "oversized_plug.py").exists()


def test_api_update_source_oversized_rejected():
    _cleanup_plugin("size_probe")
    created = client.post(
        "/api/plugins/create",
        json={"name": "size_probe", "mode": "reactive", "template": "basic_reactive"},
    )
    assert created.status_code == 200
    resp = client.put(
        "/api/plugins/size_probe/source",
        json={"source": "x = " + "a" * (1024 * 1024 + 1)},
    )
    assert resp.status_code == 400
    _cleanup_plugin("size_probe")


def test_api_plugin_history_limit_bounds():
    if "math_solver" not in PluginRegistry._plugins:
        PluginRegistry.reload_all_plugins()
    resp_low = client.get("/api/plugins/math_solver/history", params={"limit": 0})
    assert resp_low.status_code == 422
    resp_high = client.get("/api/plugins/math_solver/history", params={"limit": 999})
    assert resp_high.status_code == 422
    resp_ok = client.get("/api/plugins/math_solver/history", params={"limit": 30})
    assert resp_ok.status_code == 200


def test_api_test_plugin_timeout_upper_bound():
    resp = client.post(
        "/api/plugins/math_solver/test",
        json={"text": "1+1", "timeout": 301},
    )
    assert resp.status_code == 422


def test_api_test_plugin_uses_isolated_test_namespace():
    """调试执行写入的 storage 必须落在 __test__ 前缀命名空间，不触碰生产数据。"""
    from tg_signer.core.plugins import PluginStorageBackend

    _cleanup_plugin("ns_probe")
    created = client.post(
        "/api/plugins/create",
        json={"name": "ns_probe", "template": "storage_counter"},
    )
    assert created.status_code == 200

    backend = PluginStorageBackend()
    try:
        resp = client.post(
            "/api/plugins/ns_probe/test",
            json={"text": "", "chat_id": 555000, "params": {}},
        )
        assert resp.status_code == 200
        # 测试命名空间写入计数
        test_value = backend.get("__test__:555000:ns_probe", "total_trigger_count")
        assert test_value == 1
        # 生产命名空间不得被调试执行污染
        prod_value = backend.get("555000:ns_probe", "total_trigger_count")
        assert prod_value is None
    finally:
        backend.clear(namespace="__test__:555000:ns_probe")
        _cleanup_plugin("ns_probe")


# ============================================================================
# 后端 API：ZIP 导入防护
# ============================================================================


def _zip_bytes(members: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_api_import_bundle_rejects_zip_slip_paths():
    payload = _zip_bytes({
        "../evil_plugin.py": "x = 1",
        "/abs/evil_plugin.py": "x = 1",
        "sub\\evil_plugin.py": "x = 1",
    })
    resp = client.post(
        "/api/plugins/import-bundle",
        files={"file": ("slip.zip", payload, "application/zip")},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["imported_count"] == 0
    assert len(result["errors"]) == 3
    from pathlib import Path

    assert not (Path.cwd() / "data" / "plugins" / "evil_plugin.py").exists()


def test_api_import_bundle_rejects_unsupported_layout():
    """嵌套子目录的普通 .py 文件不会被加载器识别，应显式拒绝而非假报导入成功。"""
    payload = _zip_bytes({
        "deep/nested/plugin.py": "x = 1",
    })
    resp = client.post(
        "/api/plugins/import-bundle",
        files={"file": ("layout.zip", payload, "application/zip")},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["imported_count"] == 0
    assert any("不支持的插件布局" in error for error in result["errors"])


def test_api_import_bundle_accepts_directory_layout():
    """单层目录型插件（main.py）应被正常导入并以真实注册名回填。"""
    _cleanup_plugin("dir_bundle_plug")
    code = (
        '"""目录型插件"""\n'
        "from tg_signer.core.plugins import PluginContext, PluginRegistry\n\n"
        '@PluginRegistry.register(name="dir_bundle_plug", mode="reactive")\n'
        "async def dir_bundle_plug_handler(ctx: PluginContext) -> bool:\n"
        "    return True\n"
    )
    payload = _zip_bytes({"dir_bundle_plug/main.py": code})
    resp = client.post(
        "/api/plugins/import-bundle",
        files={"file": ("dir.zip", payload, "application/zip")},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["imported_count"] == 1
    assert "dir_bundle_plug" in result["files"]
    _cleanup_plugin("dir_bundle_plug")


# ============================================================================
# 后端 API：格式化降级标识
# ============================================================================


def test_api_format_source_reports_downgrade_metadata():
    resp = client.post(
        "/api/plugins/format-source",
        json={"source": "x=1\n# a comment\ny  =  2\n"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["formatter"] in ("black", "ast")
    # ast 降级必然有损；black 无损
    assert data["lossy"] is (data["formatter"] == "ast")


# ============================================================================
# 核心：注册冲突防护
# ============================================================================


def test_register_rejects_same_name_from_different_files(tmp_path):
    """不同文件注册同名插件必须抛错，不得静默覆盖。"""
    PluginRegistry.clear()
    code = (
        "from tg_signer.core.plugins import PluginContext, PluginRegistry\n\n"
        '@PluginRegistry.register(name="clash_plugin", mode="active")\n'
        "async def clash_plugin_handler(ctx: PluginContext) -> bool:\n"
        "    return True\n"
    )
    file_a = tmp_path / "plugin_a.py"
    file_b = tmp_path / "plugin_b.py"
    file_a.write_text(code, encoding="utf-8")
    file_b.write_text(code, encoding="utf-8")

    exec(compile(code, str(file_a), "exec"), {})
    assert PluginRegistry.get("clash_plugin") is not None
    first_handler = PluginRegistry.get("clash_plugin").handler

    with pytest.raises(ValueError, match="插件名称已注册"):
        exec(compile(code, str(file_b), "exec"), {})
    assert PluginRegistry.get("clash_plugin").handler is first_handler
    PluginRegistry.clear()


def test_register_allows_reexecution_of_same_file(tmp_path):
    """同一文件再次执行（模块重载场景）允许覆盖注册。"""
    PluginRegistry.clear()
    code = (
        "from tg_signer.core.plugins import PluginContext, PluginRegistry\n\n"
        '@PluginRegistry.register(name="reload_plugin", mode="active")\n'
        "async def reload_plugin_handler(ctx: PluginContext) -> bool:\n"
        "    return True\n"
    )
    plugin_file = tmp_path / "reload_plugin.py"
    plugin_file.write_text(code, encoding="utf-8")

    exec(compile(code, str(plugin_file), "exec"), {})
    first_handler = PluginRegistry.get("reload_plugin").handler
    exec(compile(code, str(plugin_file), "exec"), {})
    second_handler = PluginRegistry.get("reload_plugin").handler
    assert second_handler is not first_handler
    PluginRegistry.clear()


# ============================================================================
# 核心：执行指标口径
# ============================================================================


def _write_plugin(tmp_path, stem: str, mode: str, body: str) -> None:
    (tmp_path / f"{stem}.py").write_text(
        "from tg_signer.core.plugins import PluginContext, PluginRegistry\n\n"
        f'@PluginRegistry.register(name="{stem}", mode="{mode}")\n'
        f"async def {stem}_handler(ctx: PluginContext) -> bool:\n"
        f"{body}\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_host_records_single_failure_on_handler_exception(tmp_path):
    """插件抛异常时只记一条失败，不得出现 成功+失败 双重计数。"""
    _write_plugin(tmp_path, "boom_plug", "active", "    raise RuntimeError('boom inside handler')")
    PluginRegistry.clear()
    assert PluginRegistry.load_plugins_from_dir(tmp_path) == 1
    PluginRegistry.reset_metrics("boom_plug")

    ctx = PluginContext(app=MagicMock(), chat_id=1, plugin_name="boom_plug")
    host = PluginProcessHost(plugin_name="boom_plug", ctx=ctx, timeout=15.0)
    with pytest.raises(RuntimeError, match="boom inside handler"):
        await host.execute()

    metrics = PluginRegistry.get_metrics("boom_plug")
    assert metrics is not None
    assert metrics.run_count == 1
    assert metrics.failure_count == 1
    assert metrics.success_count == 0
    assert metrics.last_error is not None
    PluginRegistry.clear()


@pytest.mark.asyncio
async def test_host_records_false_as_failure_for_active_plugin(tmp_path):
    """active 插件返回 False 属业务失败，成功率口径不得虚高。"""
    _write_plugin(tmp_path, "false_plug", "active", "    return False")
    PluginRegistry.clear()
    PluginRegistry.load_plugins_from_dir(tmp_path)
    PluginRegistry.reset_metrics("false_plug")

    ctx = PluginContext(app=MagicMock(), chat_id=1, plugin_name="false_plug")
    host = PluginProcessHost(plugin_name="false_plug", ctx=ctx, timeout=15.0)
    res = await host.execute()
    assert res is False

    metrics = PluginRegistry.get_metrics("false_plug")
    assert metrics.run_count == 1
    assert metrics.failure_count == 1
    assert metrics.success_count == 0
    PluginRegistry.clear()


@pytest.mark.asyncio
async def test_host_records_false_as_success_for_reactive_plugin(tmp_path):
    """reactive 插件返回 False 仅表示未命中消息，仍属正常执行完成。"""
    _write_plugin(tmp_path, "nohit_plug", "reactive", "    return False")
    PluginRegistry.clear()
    PluginRegistry.load_plugins_from_dir(tmp_path)
    PluginRegistry.reset_metrics("nohit_plug")

    ctx = PluginContext(app=MagicMock(), chat_id=1, plugin_name="nohit_plug")
    host = PluginProcessHost(plugin_name="nohit_plug", ctx=ctx, timeout=15.0)
    res = await host.execute()
    assert res is False

    metrics = PluginRegistry.get_metrics("nohit_plug")
    assert metrics.run_count == 1
    assert metrics.success_count == 1
    assert metrics.failure_count == 0
    PluginRegistry.clear()


def test_metrics_default_success_rate_is_zero_and_duration_rounding_consistent():
    PluginRegistry.reset_metrics("metric_probe")
    assert PluginRegistry.get_metrics("metric_probe") is None
    # 从未执行时成功率为 0.0，不误导
    assert PluginMetrics().success_rate == 0.0

    PluginRegistry.record_execution("metric_probe", 0.03, True)
    PluginRegistry.record_execution("metric_probe", 10.567, False, error="x")
    metrics = PluginRegistry.get_metrics("metric_probe")
    assert metrics.run_count == 2
    assert metrics.success_count == 1
    assert metrics.failure_count == 1
    # last/total/avg 口径一致：均为统一取整（两位小数）后的值
    assert metrics.last_duration_ms == 10.57
    assert metrics.total_duration_ms == pytest.approx(10.6)
    assert metrics.avg_duration_ms == pytest.approx(round(10.6 / 2, 1))
    PluginRegistry.reset_metrics("metric_probe")


def test_audit_plugin_source_deep_attribute_chain_not_flagged():
    """深属性链上的同名方法不应被误报为顶层危险调用。"""
    from tg_signer.core.plugins import audit_plugin_source

    warnings = audit_plugin_source("value = obj.helper.eval(1)\n")
    assert all(w["rule"] != "disallowed-call:eval" for w in warnings)
    # 顶层 eval 仍需告警
    warnings_direct = audit_plugin_source("value = eval('1+1')\n")
    assert any(w["rule"] == "disallowed-call:eval" for w in warnings_direct)


# ============================================================================
# 核心：任务执行路径的指标覆盖
# ============================================================================


def test_signer_task_execution_records_active_metrics(monkeypatch):
    """active 插件进程内正式执行必须记录指标（trigger_type=active）。"""
    from tg_signer.core.signer_actions import SignerActionsMixin

    PluginRegistry.clear()

    @PluginRegistry.register("task_act_plug", mode="active")
    async def task_act_plug_handler(ctx: PluginContext) -> bool:
        return True

    recorded = []
    mixin = SignerActionsMixin.__new__(SignerActionsMixin)
    mixin.log = lambda *a, **k: None
    monkeypatch.setattr(
        "tg_signer.core.plugins.PluginRegistry.record_execution",
        lambda *args, **kwargs: recorded.append((args, kwargs)),
    )
    mixin._record_plugin_task_execution("task_act_plug", 0.0, success=True, trigger_type="active")
    assert recorded and recorded[0][1]["trigger_type"] == "active"
    PluginRegistry.clear()

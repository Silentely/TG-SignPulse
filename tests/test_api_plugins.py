"""Tests for plugins API endpoints: GET /api/plugins, POST /api/plugins/reload, POST /api/plugins/{name}/test."""

from __future__ import annotations

from tests.test_api import _auth, _login
from tg_signer.core.plugins import PluginContext, PluginRegistry

pytest_plugins = ("tests.test_api",)


# Module-level registration so that worker subprocess can resolve plugins when loading this file
def _register_sandbox_worker_fixtures():
    PluginRegistry._plugins.pop("test_sync_hang_sandbox", None)

    @PluginRegistry.register(
        name="test_sync_hang_sandbox",
        mode="reactive",
        description="沙箱同步死循环挂起测试插件",
    )
    def hang_sandbox_handler(ctx: PluginContext):
        import time

        while True:
            time.sleep(0.05)

    PluginRegistry._plugins.pop("test_crashing_plugin", None)

    @PluginRegistry.register(
        name="test_crashing_plugin",
        mode="reactive",
    )
    def crash_handler(ctx: PluginContext):
        raise RuntimeError("模拟插件执行崩溃")


_register_sandbox_worker_fixtures()


def test_list_plugins_requires_auth(api_client):
    """未认证访问 /api/plugins 应返回 401"""
    resp = api_client.get("/api/plugins")
    assert resp.status_code == 401


def test_list_and_reload_plugins(api_client):
    """测试已认证用户获取插件列表与重新加载插件"""
    token = _login(api_client)
    headers = _auth(token)

    # 注册一个临时插件
    @PluginRegistry.register(
        name="test_api_plugin",
        mode="active",
        description="用于测试 API 的插件",
        params_schema=[{"name": "foo", "label": "Foo", "type": "string"}],
    )
    def dummy_handler(ctx: PluginContext):
        return True

    # 测试 GET /api/plugins
    resp = api_client.get("/api/plugins", headers=headers)
    assert resp.status_code == 200
    plugins = resp.json()
    assert isinstance(plugins, list)
    names = [p["name"] for p in plugins]
    assert "test_api_plugin" in names

    target = next(p for p in plugins if p["name"] == "test_api_plugin")
    assert target["mode"] == "active"
    assert target["description"] == "用于测试 API 的插件"
    assert len(target["params_schema"]) == 1
    assert target["params_schema"][0]["name"] == "foo"
    assert target["source_path"] is None or not target["source_path"].startswith("/")

    # 测试 POST /api/plugins/reload
    reload_resp = api_client.post("/api/plugins/reload", headers=headers)
    assert reload_resp.status_code == 200
    data = reload_resp.json()
    assert "count" in data
    assert "plugins" in data
    assert isinstance(data["plugins"], list)


def test_test_plugin_endpoint(api_client):
    """测试 Web 调试沙箱接口 POST /api/plugins/{name}/test"""
    token = _login(api_client)
    headers = _auth(token)

    # 404 测试
    resp_404 = api_client.post(
        "/api/plugins/non_existent_plugin/test",
        headers=headers,
        json={"text": "hello"},
    )
    assert resp_404.status_code == 404

    # 注册响应型计算插件
    @PluginRegistry.register(
        name="test_calculator_sandbox",
        mode="reactive",
        description="计算器沙箱测试",
    )
    async def calc_handler(ctx: PluginContext):
        if "1+1" in ctx.message.text:
            ctx.log("计算表达式 1+1")
            await ctx.reply("2")
            return True
        return False

    # 命中测试
    resp_match = api_client.post(
        "/api/plugins/test_calculator_sandbox/test",
        headers=headers,
        json={"text": "请回答 1+1=?"},
    )
    assert resp_match.status_code == 200
    data = resp_match.json()
    assert data["success"] is True
    assert data["handled"] is True
    assert data["reply_text"] == "2"
    assert data["isolation"] == "in_process"
    assert data["killed"] is False
    assert any("计算表达式 1+1" in log for log in data["logs"])
    assert data["duration_ms"] >= 0

    # 未命中测试
    resp_no_match = api_client.post(
        "/api/plugins/test_calculator_sandbox/test",
        headers=headers,
        json={"text": "无关消息"},
    )
    assert resp_no_match.status_code == 200
    data_no_match = resp_no_match.json()
    assert data_no_match["success"] is True
    assert data_no_match["handled"] is False
    assert data_no_match["reply_text"] is None
    assert data_no_match["isolation"] == "in_process"
    assert data_no_match["killed"] is False


def test_test_plugin_endpoint_error_and_timeout(api_client):
    """测试 Web 调试沙箱接口捕获异常与超时"""
    token = _login(api_client)
    headers = _auth(token)
    _register_sandbox_worker_fixtures()

    resp_crash = api_client.post(
        "/api/plugins/test_crashing_plugin/test",
        headers=headers,
        json={"text": "boom"},
    )
    assert resp_crash.status_code == 200
    data = resp_crash.json()
    assert data["success"] is False
    assert data["handled"] is False
    assert "模拟插件执行崩溃" in data["error"]
    assert any("模拟插件执行崩溃" in log for log in data["logs"])


def test_test_plugin_endpoint_sync_hang_killed(api_client, monkeypatch):
    """测试同步死循环插件在沙箱中被进程组硬杀，返回 isolation=subprocess 与 killed=True"""
    _register_sandbox_worker_fixtures()
    token = _login(api_client)
    headers = _auth(token)
    monkeypatch.setenv("PLUGIN_TEST_TIMEOUT", "0.2")

    resp = api_client.post(
        "/api/plugins/test_sync_hang_sandbox/test",
        headers=headers,
        json={"text": "ping"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["isolation"] == "subprocess"
    assert data["killed"] is True
    assert "超时" in data["error"]

def test_toggle_plugin_endpoint(api_client):
    """测试插件启用/停用软开关切换接口"""
    token = _login(api_client)
    headers = _auth(token)

    @PluginRegistry.register(
        name="test_toggle_candidate",
        mode="reactive",
        description="测试软开关切换",
    )
    def toggle_handler(ctx: PluginContext):
        return True

    # 初始状态应为启用
    resp_init = api_client.get("/api/plugins", headers=headers)
    assert resp_init.status_code == 200
    item = next(p for p in resp_init.json() if p["name"] == "test_toggle_candidate")
    assert item["enabled"] is True

    # 第一次 toggle: 变为停用
    resp_toggle1 = api_client.post("/api/plugins/test_toggle_candidate/toggle", headers=headers)
    assert resp_toggle1.status_code == 200
    data1 = resp_toggle1.json()
    assert data1["name"] == "test_toggle_candidate"
    assert data1["enabled"] is False

    # 再次查询列表验证
    resp_list1 = api_client.get("/api/plugins", headers=headers)
    item1 = next(p for p in resp_list1.json() if p["name"] == "test_toggle_candidate")
    assert item1["enabled"] is False

    # 第二次 toggle: 恢复启用
    resp_toggle2 = api_client.post("/api/plugins/test_toggle_candidate/toggle", headers=headers)
    assert resp_toggle2.status_code == 200
    assert resp_toggle2.json()["enabled"] is True

    # 测试对不存在的插件 toggle 返回 404
    resp_404 = api_client.post("/api/plugins/non_existent_xyz/toggle", headers=headers)
    assert resp_404.status_code == 404


def test_test_plugin_reaction(api_client):
    """测试在沙箱演练场中使用 ctx.react 并返回 reacted_emojis"""
    token = _login(api_client)
    headers = _auth(token)

    @PluginRegistry.register(
        name="test_reaction_plugin",
        mode="reactive",
    )
    async def reaction_handler(ctx: PluginContext):
        await ctx.react("🎉")
        return True

    resp = api_client.post(
        "/api/plugins/test_reaction_plugin/test",
        headers=headers,
        json={"text": "congrats"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["handled"] is True
    assert "🎉" in data["reacted_emojis"]

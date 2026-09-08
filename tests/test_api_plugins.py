"""Tests for plugins API endpoints: GET /api/plugins, POST /api/plugins/reload, POST /api/plugins/{name}/test."""
from __future__ import annotations

import pytest
from tg_signer.core.plugins import PluginRegistry, PluginContext
from tests.test_api import api_client, _login, _auth  # noqa: F401


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

"""Tests for plugins API endpoints: GET /api/plugins and POST /api/plugins/reload."""
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

    # 测试 POST /api/plugins/reload
    reload_resp = api_client.post("/api/plugins/reload", headers=headers)
    assert reload_resp.status_code == 200
    data = reload_resp.json()
    assert "count" in data
    assert "plugins" in data
    assert isinstance(data["plugins"], list)

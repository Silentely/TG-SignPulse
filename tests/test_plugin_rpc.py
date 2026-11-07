from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_signer.core.plugin_host import PluginProcessHost
from tg_signer.core.plugin_worker import ProxyPluginContext
from tg_signer.core.plugins import (
    PluginContext,
    PluginRegistry,
    normalize_permissions,
)


@pytest.fixture(autouse=True)
def clean_registry():
    orig_math = PluginRegistry._plugins.get("math_solver")
    yield
    PluginRegistry._plugins.pop("test_plugin_web_app_allowed", None)
    PluginRegistry._plugins.pop("test_plugin_web_app_denied", None)
    if orig_math is not None:
        PluginRegistry._plugins["math_solver"] = orig_math
    else:
        PluginRegistry._plugins.pop("math_solver", None)


def test_permission_canonical_map_web_app():
    """Verify web_app permission normalization."""
    assert "web_app" in normalize_permissions(["web_app"])
    assert normalize_permissions(["web_app", "message_read"]) == {
        "web_app",
        "message_read",
    }


@pytest.mark.asyncio
async def test_plugin_context_request_web_view_direct():
    """Verify PluginContext.request_web_view parses initData parameters correctly."""
    mock_app = MagicMock()
    mock_app.resolve_peer = AsyncMock(return_value="peer_wallet")

    mock_raw_result = MagicMock()
    mock_raw_result.url = (
        "https://api.example.com/wv#tgWebAppData=query_id%3DAA%26user%3D%257B%2522id%2522%253A1001%257D"
        "%26receiver%3D%257B%2522id%2522%253A2002%257D%26auth_date%3D1710000000%26signature%3Dsig123"
        "%26hash%3D0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        "&tgWebAppVersion=7.0&tgWebAppPlatform=android"
    )
    mock_raw_result.query_id = 98765
    mock_app.invoke = AsyncMock(return_value=mock_raw_result)

    ctx = PluginContext(
        app=mock_app,
        chat_id=12345,
        plugin_name="test_plugin",
        context_version=2,
    )

    res = await ctx.request_web_view(bot_peer="wallet", from_bot_menu=True)

    assert res["url"] == mock_raw_result.url
    assert res["query_id"] == 98765
    assert "query_id=AA" in res["init_data_raw"]
    assert res["init_data_params"]["query_id"] == "AA"
    assert res["init_data_params"]["user"] == '{"id":1001}'
    assert res["init_data_params"]["auth_date"] == "1710000000"
    assert len(res["init_data_params"]["hash"]) == 64
    assert set(res["init_data_params"].keys()) == {
        "query_id",
        "user",
        "receiver",
        "auth_date",
        "signature",
        "hash",
    }


@pytest.mark.asyncio
async def test_proxy_plugin_context_request_web_view_forwarding():
    """Verify ProxyPluginContext forwards request_web_view to rpc."""
    mock_rpc = AsyncMock(
        return_value={
            "url": "https://api.example.com/wv#tgWebAppData=hash%3D123",
            "query_id": 111,
            "init_data_raw": "hash=123",
            "init_data_params": {"hash": "123"},
        }
    )

    proxy_ctx = ProxyPluginContext(
        chat_id=12345,
        message=None,
        params={},
        rpc_requester=mock_rpc,
        logger_sink=lambda x: None,
        plugin_name="test_plugin",
        context_version=2,
    )

    res = await proxy_ctx.request_web_view(
        bot_peer="test_bot", platform="android", from_bot_menu=True
    )
    mock_rpc.assert_awaited_once_with(
        "request_web_view",
        bot_peer="test_bot",
        url=None,
        start_param=None,
        theme_params=None,
        platform="android",
        from_bot_menu=True,
    )
    assert res["query_id"] == 111


@pytest.mark.asyncio
async def test_plugin_host_check_rpc_grant_web_app():
    """Verify PluginProcessHost._check_rpc_grant enforces web_app permission."""

    @PluginRegistry.register(
        name="test_plugin_web_app_allowed",
        mode="active",
        context_version=2,
        permissions=["web_app"],
    )
    def allowed_handler(ctx):
        return True

    @PluginRegistry.register(
        name="test_plugin_web_app_denied",
        mode="active",
        context_version=2,
        permissions=["message_read"],
    )
    def denied_handler(ctx):
        return True

    ctx = MagicMock()
    host_allowed = PluginProcessHost(plugin_name="test_plugin_web_app_allowed", ctx=ctx)
    # Should not raise
    host_allowed._check_rpc_grant("request_web_view", {})

    host_denied = PluginProcessHost(plugin_name="test_plugin_web_app_denied", ctx=ctx)
    with pytest.raises(PermissionError) as exc_info:
        host_denied._check_rpc_grant("request_web_view", {})
    assert "PLUGIN_CAPABILITY_DENIED: web_app" in str(exc_info.value)


def test_whitelisted_legacy_plugin_cannot_bypass_web_app():
    """Verify whitelisted legacy plugin cannot bypass web_app permission check when calling request_web_view."""
    from pathlib import Path

    from tg_signer.core.plugins import PluginMeta

    builtin_dirs = PluginRegistry.get_builtin_directories()
    builtin_path = (
        (builtin_dirs[0] / "math_solver.py")
        if builtin_dirs
        else Path("/app/plugins/math_solver.py")
    )

    PluginRegistry._plugins["math_solver"] = PluginMeta(
        name="math_solver",
        handler=lambda ctx: True,
        mode="active",
        description="legacy math solver",
        version="1.0.0",
        updated_at="2026-01-01",
        author="builtin",
        source_path=str(builtin_path),
        params_schema=[],
        context_version=1,
        permissions=[],
    )

    ctx = MagicMock()
    host = PluginProcessHost(plugin_name="math_solver", ctx=ctx)

    # Calling ordinary method like reply or send_message passes via legacy exemption
    host._check_rpc_grant("reply", {})

    # Calling request_web_view must NOT be exempted by legacy whitelist and must fail
    with pytest.raises(PermissionError) as exc_info:
        host._check_rpc_grant("request_web_view", {})
    assert "PLUGIN_CAPABILITY_DENIED: web_app" in str(exc_info.value)

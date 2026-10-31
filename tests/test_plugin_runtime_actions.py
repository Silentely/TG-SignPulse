import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_signer.core.plugin_host import PluginProcessHost
from tg_signer.core.plugins import (
    PluginConnectionResetError,
    PluginContext,
    PluginFloodWaitError,
    PluginMessageNotFoundError,
    PluginNotSupportedError,
    PluginPermissionDeniedError,
    PluginRegistry,
    PluginTimeoutError,
    audit_plugin_source,
    normalize_permissions,
)


def test_typed_exceptions_inheritance():
    assert issubclass(PluginTimeoutError, RuntimeError)
    assert issubclass(PluginFloodWaitError, RuntimeError)
    flood = PluginFloodWaitError(42)
    assert flood.seconds == 42
    assert "42" in str(flood)
    assert issubclass(PluginPermissionDeniedError, PermissionError)
    assert issubclass(PluginNotSupportedError, RuntimeError)
    assert issubclass(PluginMessageNotFoundError, RuntimeError)
    assert issubclass(PluginConnectionResetError, ConnectionResetError)


def test_normalize_permissions_mapping():
    assert normalize_permissions(["telegram_read", "telegram_send", "storage"]) == {
        "message_read",
        "message_write",
        "storage",
    }
    assert normalize_permissions(["message_write", "global_storage"]) == {
        "message_write",
        "global_storage",
    }


def test_manifest_loading_normalizes_permissions_exact_set(tmp_path):
    p_dir = tmp_path / "test_norm_plugin"
    p_dir.mkdir()
    p_json = p_dir / "plugin.json"
    p_json.write_text(
        json.dumps(
            {
                "id": "test_norm_plugin",
                "name": "Test Norm",
                "version": "1.0.0",
                "mode": "active",
                "category": "utility",
                "description": "testing norm",
                "author": "test",
                "min_app_version": "1.9.0",
                "context_version": 2,
                "plugin_api": "2.0",
                "permissions": ["telegram_read"],
            }
        ),
        encoding="utf-8",
    )

    main_py = p_dir / "main.py"
    main_py.write_text(
        """
from tg_signer.core.plugins import PluginContext, PluginRegistry
@PluginRegistry.register(
    name="test_norm_plugin",
    mode="active",
    context_version=2,
    plugin_api="2.0",
    permissions=["telegram_read"],
)
async def handler(ctx: PluginContext):
    return True
""",
        encoding="utf-8",
    )

    loaded_count = PluginRegistry.load_plugins_from_dir(tmp_path)
    assert loaded_count >= 1
    meta = PluginRegistry.get("test_norm_plugin")
    assert meta is not None
    # Exact normalized list assertion
    assert meta.permissions == ["message_read"]


def test_ast_security_audit_detects_undeclared_capability_as_high_severity():
    code = """
from tg_signer.core.plugins import PluginContext, PluginRegistry
PERMISSIONS = []
@PluginRegistry.register(name="bad_plugin", mode="active", context_version=2, permissions=PERMISSIONS)
async def handler(ctx: PluginContext):
    await ctx.storage.get("leak")
    return True
"""
    warnings = audit_plugin_source(code)
    storage_warnings = [
        w for w in warnings if w.get("rule") == "undeclared-capability:storage"
    ]
    assert len(storage_warnings) == 1
    # Must be high severity so build_marketplace.py --check blocks it directly
    assert storage_warnings[0].get("severity") == "high"


def test_permission_exclusivity_retains_buttons_and_reactions():
    from tg_signer.core.plugins import PluginMeta

    meta = PluginMeta(
        name="test_exclusivity",
        handler=lambda ctx: None,
        mode="active",
        description="",
        version="1.0.0",
        updated_at="2026-10-31",
        author="test",
        source_path="",
        params_schema=[],
        permissions=["message_write"],  # has write but not buttons/reactions
        context_version=2,
    )
    PluginRegistry._plugins["test_exclusivity"] = meta
    host = PluginProcessHost(
        plugin_name="test_exclusivity", ctx=MagicMock(), timeout=1.0
    )

    with pytest.raises(PermissionError) as exc_info:
        host._check_rpc_grant("click", {})
    assert "PLUGIN_CAPABILITY_DENIED: buttons" in str(exc_info.value)

    with pytest.raises(PermissionError) as exc_info:
        host._check_rpc_grant("react", {})
    assert "PLUGIN_CAPABILITY_DENIED: reactions" in str(exc_info.value)


@pytest.mark.asyncio
async def test_plugin_context_send_chat_action_pyrogram_enums():
    app = MagicMock()
    app.send_chat_action = AsyncMock(return_value=True)
    ctx = PluginContext(app=app, chat_id=12345, plugin_name="test")
    res = await ctx.send_chat_action("typing")
    assert res is True
    args, kwargs = app.send_chat_action.call_args
    assert args[0] == 12345
    assert str(args[1]) in ("ChatAction.TYPING", "typing")


@pytest.mark.asyncio
async def test_plugin_context_read_chat_history_coerces_max_id_to_zero():
    app = MagicMock()
    app.read_chat_history = AsyncMock(return_value=True)
    ctx = PluginContext(app=app, chat_id=12345, plugin_name="test")
    res = await ctx.read_chat_history(max_id=None)
    assert res is True
    app.read_chat_history.assert_called_once_with(12345, max_id=0)

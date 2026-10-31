"""TG-SignPulse Community Plugins Real Subprocess IPC Pipe Integration Tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_signer.core.plugin_host import PluginProcessHost
from tg_signer.core.plugins import (
    PluginContext,
    PluginExecutionIdentity,
    PluginPermissionDeniedError,
    PluginRegistry,
)


def _make_identity(chat_id: int = 12345) -> PluginExecutionIdentity:
    return PluginExecutionIdentity(
        account_id="test_acc",
        task_id="test_task",
        run_id="test_run",
        step_id="test_step",
        chat_id=chat_id,
    )


def _register_worker_fixtures() -> None:
    PluginRegistry._plugins.pop("real_ipc_send_chat_action", None)

    @PluginRegistry.register(
        name="real_ipc_send_chat_action",
        mode="active",
        context_version=2,
        plugin_api="2.0",
        permissions=["message_write"],
    )
    async def handle_send_chat_action(ctx: PluginContext) -> bool:
        return await ctx.send_chat_action("typing")

    PluginRegistry._plugins.pop("real_ipc_permission_denied", None)

    @PluginRegistry.register(
        name="real_ipc_permission_denied",
        mode="active",
        context_version=2,
        plugin_api="2.0",
        permissions=[],
    )
    async def handle_permission_denied(ctx: PluginContext) -> bool:
        return await ctx.send_chat_action("typing")

    PluginRegistry._plugins.pop("real_ipc_read_chat_history", None)

    @PluginRegistry.register(
        name="real_ipc_read_chat_history",
        mode="active",
        context_version=2,
        plugin_api="2.0",
        permissions=["message_read"],
    )
    async def handle_read_chat_history(ctx: PluginContext) -> bool:
        return await ctx.read_chat_history(max_id=0)


_register_worker_fixtures()


@pytest.fixture(autouse=True)
def clean_registry():
    """Cleanup and re-register test plugins before and after each test."""
    if hasattr(PluginRegistry, "_plugins"):
        PluginRegistry._plugins.clear()
    metadata = getattr(PluginRegistry, "_metadata", None)
    if isinstance(metadata, dict):
        metadata.clear()
    _register_worker_fixtures()
    yield
    if hasattr(PluginRegistry, "_plugins"):
        PluginRegistry._plugins.clear()
    metadata = getattr(PluginRegistry, "_metadata", None)
    if isinstance(metadata, dict):
        metadata.clear()
    _register_worker_fixtures()


@pytest.mark.asyncio
async def test_real_subprocess_rpc_send_chat_action_success():
    """Test real subprocess worker calls send_chat_action via IPC and host dispatches to mock app."""
    mock_app = MagicMock()
    mock_app.send_chat_action = AsyncMock(return_value=True)
    mock_logger = MagicMock(spec=["log"])

    ctx = PluginContext(
        app=mock_app,
        chat_id=12345,
        plugin_name="real_ipc_send_chat_action",
        identity=_make_identity(12345),
        context_version=2,
        logger=mock_logger,
    )
    host = PluginProcessHost(
        plugin_name="real_ipc_send_chat_action",
        ctx=ctx,
        timeout=10.0,
    )

    result = await host.execute()
    assert result is True
    assert mock_app.send_chat_action.call_count == 1
    call_args, _ = mock_app.send_chat_action.call_args
    assert call_args[0] == 12345
    assert str(call_args[1]) in ("ChatAction.TYPING", "typing")


@pytest.mark.asyncio
async def test_real_subprocess_rpc_permission_denied_raises_typed_error():
    """Test real subprocess worker with empty permissions calling send_chat_action fails with permission error."""
    mock_app = MagicMock()
    mock_app.send_chat_action = AsyncMock(return_value=True)
    mock_logger = MagicMock(spec=["log"])

    ctx = PluginContext(
        app=mock_app,
        chat_id=12345,
        plugin_name="real_ipc_permission_denied",
        identity=_make_identity(12345),
        context_version=2,
        logger=mock_logger,
    )
    host = PluginProcessHost(
        plugin_name="real_ipc_permission_denied",
        ctx=ctx,
        timeout=10.0,
    )

    with pytest.raises((RuntimeError, PluginPermissionDeniedError)) as exc_info:
        await host.execute()

    err_text = str(exc_info.value)
    assert (
        "PluginPermissionDeniedError" in err_text
        or "PLUGIN_CAPABILITY_DENIED" in err_text
    )
    assert "message_write" in err_text or "PLUGIN_CAPABILITY_DENIED" in err_text
    mock_app.send_chat_action.assert_not_called()


@pytest.mark.asyncio
async def test_real_subprocess_rpc_read_chat_history_success():
    """Test real subprocess worker calls read_chat_history via IPC and host dispatches to mock app."""
    mock_app = MagicMock()
    mock_app.read_chat_history = AsyncMock(return_value=True)
    mock_logger = MagicMock(spec=["log"])

    ctx = PluginContext(
        app=mock_app,
        chat_id=12345,
        plugin_name="real_ipc_read_chat_history",
        identity=_make_identity(12345),
        context_version=2,
        logger=mock_logger,
    )
    host = PluginProcessHost(
        plugin_name="real_ipc_read_chat_history",
        ctx=ctx,
        timeout=10.0,
    )

    result = await host.execute()
    assert result is True
    mock_app.read_chat_history.assert_awaited_once_with(12345, max_id=0)


@pytest.mark.asyncio
async def test_real_subprocess_community_plugin_dice_roller():
    """Test real community plugin (dice_roller) executes in subprocess with IPC reply."""
    community_dir = Path("community_plugins")
    if not community_dir.is_dir():
        pytest.skip("community_plugins directory not found")

    PluginRegistry.load_plugins_from_dir(community_dir)
    assert PluginRegistry.get("dice_roller") is not None

    mock_app = MagicMock()
    mock_app.send_message = AsyncMock(return_value={"id": 999, "text": "mocked"})
    mock_logger = MagicMock(spec=["log"])

    class FakeMessage:
        id = 888
        text = "/roll 20"
        chat_id = 12345

    ctx = PluginContext(
        app=mock_app,
        chat_id=12345,
        message=FakeMessage(),
        plugin_name="dice_roller",
        identity=_make_identity(12345),
        context_version=2,
        logger=mock_logger,
    )
    host = PluginProcessHost(
        plugin_name="dice_roller",
        ctx=ctx,
        timeout=10.0,
        trigger_type="reactive",
    )

    result = await host.execute()
    assert result is True
    assert mock_app.send_message.call_count == 1
    call_args, call_kwargs = mock_app.send_message.call_args
    assert call_args[0] == 12345
    assert "骰子掷出了" in call_args[1]
    assert call_kwargs.get("reply_to_message_id") == 888

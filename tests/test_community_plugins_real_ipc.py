"""TG-SignPulse Community Plugins Real Subprocess IPC Pipe Integration Tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_signer.core.plugin_host import PluginProcessHost
from tg_signer.core.plugins import (
    PluginConnectionResetError,
    PluginContext,
    PluginExecutionIdentity,
    PluginFloodWaitError,
    PluginMessageNotFoundError,
    PluginNotSupportedError,
    PluginPermissionDeniedError,
    PluginRegistry,
    PluginTimeoutError,
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

    PluginRegistry._plugins.pop("real_ipc_flood_wait", None)

    @PluginRegistry.register(
        name="real_ipc_flood_wait",
        mode="active",
        context_version=2,
        plugin_api="2.0",
    )
    async def handle_flood_wait(ctx: PluginContext) -> bool:
        raise PluginFloodWaitError(42)

    PluginRegistry._plugins.pop("real_ipc_not_supported", None)

    @PluginRegistry.register(
        name="real_ipc_not_supported",
        mode="active",
        context_version=2,
        plugin_api="2.0",
    )
    async def handle_not_supported(ctx: PluginContext) -> bool:
        raise PluginNotSupportedError("Action not supported on channel")

    PluginRegistry._plugins.pop("real_ipc_message_not_found", None)

    @PluginRegistry.register(
        name="real_ipc_message_not_found",
        mode="active",
        context_version=2,
        plugin_api="2.0",
    )
    async def handle_message_not_found(ctx: PluginContext) -> bool:
        raise PluginMessageNotFoundError("Target message 999 deleted")

    PluginRegistry._plugins.pop("real_ipc_timeout_err", None)

    @PluginRegistry.register(
        name="real_ipc_timeout_err",
        mode="active",
        context_version=2,
        plugin_api="2.0",
    )
    async def handle_timeout_err(ctx: PluginContext) -> bool:
        raise PluginTimeoutError("Operation timed out after 15s")

    PluginRegistry._plugins.pop("real_ipc_request_web_view", None)

    @PluginRegistry.register(
        name="real_ipc_request_web_view",
        mode="active",
        context_version=2,
        plugin_api="2.0",
        permissions=["web_app"],
    )
    async def handle_request_web_view(ctx: PluginContext) -> bool:
        res = await ctx.request_web_view(bot_peer="test_bot", from_bot_menu=True)
        return bool(res and res.get("query_id") == 12345)

    PluginRegistry._plugins.pop("real_ipc_disconnected_err", None)

    @PluginRegistry.register(
        name="real_ipc_disconnected_err",
        mode="active",
        context_version=2,
        plugin_api="2.0",
    )
    async def handle_disconnected_err(ctx: PluginContext) -> bool:
        raise PluginConnectionResetError("Worker IPC pipe terminated")


_register_worker_fixtures()


@pytest.fixture(autouse=True)
def clean_registry():
    """Cleanup and re-register test plugins before and after each test."""
    PluginRegistry.clear()
    _register_worker_fixtures()
    yield
    PluginRegistry.clear()
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

    with pytest.raises(PluginPermissionDeniedError) as exc_info:
        await host.execute()

    assert isinstance(exc_info.value, PluginPermissionDeniedError)
    assert "PLUGIN_CAPABILITY_DENIED" in str(exc_info.value)
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
async def test_real_subprocess_community_plugin_dice_roller(monkeypatch):
    """Test real community plugin (dice_roller) executes in subprocess with IPC reply."""
    community_dir = Path(__file__).resolve().parent.parent / "community_plugins"
    if not community_dir.is_dir():
        pytest.skip("community_plugins directory not found")

    # 执行前门禁按当前开关判定社区插件是否可用，这里显式开启以聚焦 IPC 行为
    monkeypatch.setenv("PLUGINS_ALLOW_COMMUNITY", "true")
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


@pytest.mark.asyncio
async def test_real_subprocess_worker_reconstructs_typed_exceptions():
    """Verify all 5 other typed exceptions from subprocess worker are reconstructed as typed instances on host."""
    cases = [
        ("real_ipc_flood_wait", PluginFloodWaitError, lambda exc: exc.seconds == 42),
        (
            "real_ipc_not_supported",
            PluginNotSupportedError,
            lambda exc: "Action not supported" in str(exc),
        ),
        (
            "real_ipc_message_not_found",
            PluginMessageNotFoundError,
            lambda exc: "Target message 999 deleted" in str(exc),
        ),
        (
            "real_ipc_timeout_err",
            PluginTimeoutError,
            lambda exc: "timed out" in str(exc),
        ),
        (
            "real_ipc_disconnected_err",
            PluginConnectionResetError,
            lambda exc: "terminated" in str(exc),
        ),
    ]

    for plugin_name, expected_cls, check_fn in cases:
        ctx = PluginContext(
            app=MagicMock(),
            chat_id=12345,
            plugin_name=plugin_name,
            identity=_make_identity(12345),
            context_version=2,
            logger=MagicMock(spec=["log"]),
        )
        host = PluginProcessHost(plugin_name=plugin_name, ctx=ctx, timeout=5.0)
        with pytest.raises(expected_cls) as exc_info:
            await host.execute()
        assert isinstance(exc_info.value, expected_cls), (
            f"Expected {expected_cls}, got {type(exc_info.value)}"
        )
        assert check_fn(exc_info.value), (
            f"Check failed for {plugin_name}: {exc_info.value}"
        )


@pytest.mark.asyncio
async def test_production_runtime_path_propagates_typed_exceptions_and_marks_attempted_receipt_unknown():
    """生产路径端到端测试（不使用测试替身，使用默认 SubprocessPluginAdapter）：
    构造真实子进程分别抛出 flood_wait / permission_denied / IPC断开 三种情况，
    断言 signer_actions 拿到的是对应的 typed 异常（isinstance），
    并且 ATTEMPTED 状态的 receipt 在 flow_adapter 中会被置为 UNKNOWN。
    """
    from tg_signer.config import PluginAction, SignChatV3
    from tg_signer.core.flow_adapter import TelegramNodeExecutor
    from tg_signer.core.flow_context import ScopedFlowContext
    from tg_signer.core.flow_models import ActionNode, ExecutionGraph, RetryPolicy
    from tg_signer.core.operation_receipts import (
        OperationAttemptState,
        UnknownOperationResult,
        mark_operation_attempted,
    )
    from tg_signer.core.plugin_runtime import (
        SubprocessPluginAdapter,
        get_plugin_runtime,
    )
    from tg_signer.core.signer_actions import SignerActionsMixin

    # 1. 确保生产默认运行时为 SubprocessPluginAdapter
    runtime = get_plugin_runtime()
    assert isinstance(runtime, SubprocessPluginAdapter)

    cases = [
        ("real_ipc_flood_wait", PluginFloodWaitError, lambda exc: exc.seconds == 42),
        (
            "real_ipc_permission_denied",
            PluginPermissionDeniedError,
            lambda exc: "PLUGIN_CAPABILITY_DENIED" in str(exc),
        ),
        (
            "real_ipc_disconnected_err",
            PluginConnectionResetError,
            lambda exc: "terminated" in str(exc),
        ),
    ]

    class ProductionSigner(SignerActionsMixin):
        def __init__(self):
            self.app = MagicMock()
            self.app.send_chat_action = AsyncMock(return_value=True)
            self.log_entries = []
            self.context = MagicMock()
            self.context.chat_messages = {}
            self.context.waiting_message = None
            self.context.last_callback_answer = None

        def log(self, msg, level="INFO"):
            self.log_entries.append((level, msg))

        def _message_matches_chat_thread(self, message, chat):
            return True

        def _message_is_actionable_target(self, message, action=None):
            return True

        def _log_received_target_message(self, message):
            pass

        def _describe_action(self, action):
            return str(action)

        def _current_action_step_label(self):
            return "第 1 步"

        async def wait_for(self, chat, action, next_action=None, step_timeout=None):
            # 标记 operation receipt 进入 ATTEMPTED 状态，模拟执行过程中发生副作用/已发起调用
            mark_operation_attempted()
            # 走真实生产路径的 _dispatch_reactive_plugin_message
            mock_msg = MagicMock()
            mock_msg.text = "test_trigger"
            return await self._dispatch_reactive_plugin_message(
                action, chat, mock_msg, eff_timeout=5.0
            )

    for plugin_name, expected_cls, check_fn in cases:
        action = PluginAction(plugin_name=plugin_name, mode="reactive")
        chat = SignChatV3(chat_id=12345, actions=[action])
        signer = ProductionSigner()

        # 直接调用 signer._dispatch_reactive_plugin_message：断言抛出 typed 异常（严格 isinstance）
        mock_msg = MagicMock()
        mock_msg.text = "trigger"
        with pytest.raises(expected_cls) as exc_info:
            await signer._dispatch_reactive_plugin_message(
                action, chat, mock_msg, eff_timeout=5.0
            )
        assert isinstance(exc_info.value, expected_cls)
        assert check_fn(exc_info.value)

        # 结合 flow_adapter 运行：在 ATTEMPTED 状态下抛出 typed 异常，断言转为 UnknownOperationResult 且 receipt.state == UNKNOWN
        graph = ExecutionGraph(
            entry_node_id="act",
            nodes={
                "act": ActionNode(
                    id="act",
                    action_type="CUSTOM_PLUGIN",
                    params={"plugin_name": plugin_name, "mode": "reactive"},
                    retry_policy=RetryPolicy(max_attempts=1),
                )
            },
        )
        ctx = ScopedFlowContext()
        executor = TelegramNodeExecutor(signer, chat, graph)

        with pytest.raises(UnknownOperationResult) as unk_info:
            await executor(graph.nodes["act"], ctx)

        # 确认引起 UnknownOperationResult 的原因就是我们抛出的 typed 异常
        cause = unk_info.value.__cause__
        assert isinstance(cause, expected_cls)
        assert check_fn(cause)

        # 核心断言：ATTEMPTED 状态的 receipt 必须转为 UNKNOWN
        assert len(ctx.operation_receipts) >= 1
        assert ctx.operation_receipts[-1].state == OperationAttemptState.UNKNOWN


@pytest.mark.asyncio
async def test_real_subprocess_rpc_request_web_view_success():
    """Test real subprocess worker calls request_web_view via IPC and host dispatches to mock app."""
    mock_app = MagicMock()
    mock_app.resolve_peer = AsyncMock(return_value="peer_test_bot")
    mock_raw_result = MagicMock()
    mock_raw_result.url = (
        "https://api.example.com/wv#tgWebAppData=hash%3D123&tgWebAppVersion=7.0"
    )
    mock_raw_result.query_id = 12345
    mock_app.invoke = AsyncMock(return_value=mock_raw_result)
    mock_logger = MagicMock(spec=["log"])

    ctx = PluginContext(
        app=mock_app,
        chat_id=12345,
        plugin_name="real_ipc_request_web_view",
        identity=_make_identity(12345),
        context_version=2,
        logger=mock_logger,
    )
    host = PluginProcessHost(
        plugin_name="real_ipc_request_web_view",
        ctx=ctx,
        timeout=10.0,
    )

    result = await host.execute()
    assert result is True
    assert mock_app.invoke.call_count == 1

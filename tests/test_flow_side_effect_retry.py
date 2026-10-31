from types import SimpleNamespace

import pytest

from tg_signer.config import SendTextAction, SignChatV3
from tg_signer.core.flow_adapter import TelegramNodeExecutor
from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_engine import PulseFlowEngine
from tg_signer.core.flow_models import ActionNode, ExecutionGraph, RetryPolicy


@pytest.mark.asyncio
async def test_adapter_does_not_replay_send_after_remote_result_becomes_unknown():
    runner = SimpleNamespace(context=SimpleNamespace(), log=lambda *a, **k: None)
    calls = []

    async def wait_for(*args, **kwargs):
        calls.append("sent")
        runner.context.pulseflow_side_effect_started = True
        raise RuntimeError("reply lost after send")

    runner.wait_for = wait_for
    chat = SignChatV3(chat_id=123, actions=[SendTextAction(text="hello")])
    graph = ExecutionGraph(
        entry_node_id="send",
        nodes={
            "send": ActionNode(
                id="send",
                action_type="SEND_TEXT",
                params={"text": "hello"},
                retry_policy=RetryPolicy(max_attempts=2, backoff_seconds=0),
            )
        },
    )
    ctx = ScopedFlowContext()
    result = await PulseFlowEngine().run(
        graph, ctx, TelegramNodeExecutor(runner, chat, graph)
    )
    assert calls == ["sent"]
    assert result["non_retryable"] is True
    assert result["business_status"] == "unknown"
    assert ctx.operation_receipts[-1].state.value == "unknown"


@pytest.mark.asyncio
async def test_pure_node_after_confirmed_operation_can_retry():
    from tg_signer.core.flow_models import NodeStatus, StepOutcome

    ctx = ScopedFlowContext()
    receipt = ctx.begin_operation("previous", "previous", 1, "send")
    ctx.mark_operation_confirmed(receipt.operation_id, {"message_id": 4})
    calls = []

    async def pure(node, context):
        calls.append(node.id)
        if len(calls) == 1:
            raise ValueError("transient read")
        return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)

    graph = ExecutionGraph(
        entry_node_id="read",
        nodes={
            "read": ActionNode(
                id="read",
                retry_policy=RetryPolicy(max_attempts=2, backoff_seconds=0),
            )
        },
    )
    result = await PulseFlowEngine().run(graph, ctx, pure)
    assert result["status"] == "success"
    assert calls == ["read", "read"]


@pytest.mark.asyncio
async def test_transient_error_does_not_resend_when_side_effect_already_started():
    """反例断言：发送已经成功产生副作用，但等待/确认阶段抛出瞬时网络异常（如 TimeoutError），
    adapter 瞬时错误重试逻辑必须进行幂等判定，拒绝重新发起 send，断言只发送一次。"""
    send_attempts = 0

    class MockSigner:
        def __init__(self):
            self.context = SimpleNamespace(pulseflow_side_effect_started=False)
            self.logs = []

        def _is_transient_step_error(self, exc):
            return isinstance(exc, TimeoutError)

        def _current_action_step_label(self):
            return "[Step 1]"

        def log(self, msg, level="INFO"):
            self.logs.append((level, msg))

        async def wait_for(self, chat, action, next_action=None, step_timeout=None):
            nonlocal send_attempts
            send_attempts += 1
            # 模拟：已发送至 Telegram 并产生了副作用
            self.context.pulseflow_side_effect_started = True
            # 等待/确认阶段抛出瞬时超时异常
            raise TimeoutError("Network timeout while waiting for reply")

    runner = MockSigner()
    chat = SignChatV3(chat_id=123, actions=[SendTextAction(text="hello")])
    graph = ExecutionGraph(
        entry_node_id="send",
        nodes={
            "send": ActionNode(
                id="send",
                action_type="SEND_TEXT",
                params={"text": "hello"},
                retry_policy=RetryPolicy(max_attempts=1),
            )
        },
    )
    ctx = ScopedFlowContext()
    executor = TelegramNodeExecutor(runner, chat, graph)

    from tg_signer.core.operation_receipts import UnknownOperationResult

    with pytest.raises((TimeoutError, UnknownOperationResult)):
        await executor(graph.nodes["send"], ctx)

    # 断言：由于检测到 side effect 已产生，没有触发 wait_for 的第 2 次重试重发
    assert send_attempts == 1, f"Expected 1 send attempt, got {send_attempts}"
    # 断言：产生警告日志明确指出避免重复发送
    assert any("避免重复发送" in log[1] for log in runner.logs)

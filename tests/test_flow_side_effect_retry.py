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

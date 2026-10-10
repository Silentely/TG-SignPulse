# tests/test_flow_adapter.py
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_signer.config import (
    ClickKeyboardByTextAction,
    SendTextAction,
    SignChatV3,
)
from tg_signer.core.flow_adapter import TelegramNodeExecutor
from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_engine import PulseFlowEngine
from tg_signer.core.flow_models import (
    ActionNode,
    ExecutionGraph,
    NodeStatus,
    RetryPolicy,
    StepOutcome,
)
from tg_signer.core.flow_normalizer import GraphNormalizer


@pytest.mark.asyncio
async def test_full_pipeline_with_telegram_adapter_barrier():
    chat = SignChatV3(
        chat_id=99999,
        actions=[
            SendTextAction(text="/checkin"),
            ClickKeyboardByTextAction(text="确认领奖"),
        ],
    )
    graph = GraphNormalizer.from_chat(chat)
    ctx = ScopedFlowContext(account={"username": "test_bot"})

    mock_runner = MagicMock()
    mock_runner.wait_for = AsyncMock(return_value=True)
    mock_runner.context = MagicMock()
    mock_runner.context.stop_after_current_action = True

    executor = TelegramNodeExecutor(mock_runner, chat)
    engine = PulseFlowEngine()
    result = await engine.run(graph, ctx, executor)

    assert result["status"] == "success"
    assert result["path"] == ["step_0", "step_1"]
    assert mock_runner.wait_for.call_count == 2


@pytest.mark.asyncio
async def test_adapter_skip_if_matched():
    chat = SignChatV3(
        chat_id=12345,
        actions=[
            SendTextAction(text="/start"),
            SendTextAction(text="/daily", skip_if_matched="今日已签到"),
        ],
    )
    graph = GraphNormalizer.from_chat(chat)
    ctx = ScopedFlowContext()
    ctx.record_step_outcome(
        StepOutcome(
            node_id="step_0",
            status=NodeStatus.SUCCESS,
            output_text="今日已签到，请明日再来",
        )
    )

    mock_runner = MagicMock()
    mock_runner.wait_for = AsyncMock(return_value=True)
    mock_runner.context = None

    executor = TelegramNodeExecutor(mock_runner, chat)
    engine = PulseFlowEngine()
    result = await engine.run(graph, ctx, executor)

    assert result["status"] == "success"
    # step_1 命中 skip_if_matched，被跳过，因此 wait_for 只对 step_0 调用过（或者这里从 step_0 执行到 step_1）
    assert mock_runner.wait_for.call_count == 1
    # step_1 被执行过但被跳过
    assert result["path"] == ["step_0", "step_1"]


@pytest.mark.asyncio
async def test_adapter_continue_on_error():
    chat = SignChatV3(
        chat_id=12345,
        actions=[
            SendTextAction(text="/fragile", continue_on_error=True),
            SendTextAction(text="/next"),
        ],
    )
    graph = GraphNormalizer.from_chat(chat)
    ctx = ScopedFlowContext()

    mock_runner = MagicMock()
    # 第一次抛异常，第二次成功
    mock_runner.wait_for = AsyncMock(side_effect=[RuntimeError("RPC fail"), True])
    mock_runner.context = None

    executor = TelegramNodeExecutor(mock_runner, chat)
    engine = PulseFlowEngine()
    result = await engine.run(graph, ctx, executor)

    assert result["status"] == "success"
    assert result["path"] == ["step_0", "step_1"]
    assert mock_runner.wait_for.call_count == 2


@pytest.mark.asyncio
async def test_adapter_template_rendering():
    chat = SignChatV3(
        chat_id=8888,
        name="TestChat",
        actions=[
            SendTextAction(text="Hello {{ account.username }} in {{ chat.id }}"),
        ],
    )
    graph = GraphNormalizer.from_chat(chat)
    ctx = ScopedFlowContext()

    mock_runner = MagicMock()
    mock_runner.me = MagicMock()
    mock_runner.me.username = "alice_super"
    mock_runner.wait_for = AsyncMock(return_value=True)
    mock_runner.context = None

    executor = TelegramNodeExecutor(mock_runner, chat)
    engine = PulseFlowEngine()
    result = await engine.run(graph, ctx, executor)

    assert result["status"] == "success"
    call_args = mock_runner.wait_for.call_args[0]
    executed_act = call_args[1]
    assert executed_act.text == "Hello alice_super in 8888"


@pytest.mark.asyncio
async def test_adapter_retry_policy_with_transient_error():
    # 模拟未配置 continue_on_error 且发生临时异常，触发 RetryPolicy 指数重试
    node = ActionNode(
        id="s1",
        retry_policy=RetryPolicy(max_attempts=3, backoff_seconds=0.01),
        metadata={"raw_action": SendTextAction(text="/retry_test")},
    )
    graph = ExecutionGraph(entry_node_id="s1", nodes={"s1": node})
    ctx = ScopedFlowContext()

    mock_runner = MagicMock()
    # 前2次抛出网络异常，第3次成功
    mock_runner.wait_for = AsyncMock(
        side_effect=[ConnectionError("Net reset"), TimeoutError("Timed out"), True]
    )
    mock_runner.context = None

    chat = SignChatV3(chat_id=123, actions=[])
    executor = TelegramNodeExecutor(mock_runner, chat)
    engine = PulseFlowEngine()

    result = await engine.run(graph, ctx, executor)
    assert result["status"] == "success"
    assert mock_runner.wait_for.call_count == 3

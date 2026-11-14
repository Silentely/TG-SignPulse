# tests/test_flow_timing_watermark.py
import asyncio
import time

import pytest

from tg_signer.core.flow_engine import PulseFlowEngine, ScopedFlowContext
from tg_signer.core.flow_event_bus import TelegramEventBus, TelegramMessageEvent
from tg_signer.core.flow_models import (
    TERMINAL_COMPLETE_ID,
    ActionNode,
    ExecutionGraph,
    NodeStatus,
    StepOutcome,
    WaitEventNode,
)


@pytest.mark.asyncio
async def test_watermark_id_prevents_input_replay_without_timestamp():
    """变异守护靶向1：
    验证仅依赖 last_handled_message_id 水位线时（未传 since_timestamp），
    WaitEventNode 也能严格根据已消费消息 ID 忽略前序提示，正确接收后续真实回复。
    （若去除 last_handled_message_id 推进，本用例必红 Exit 1）
    """
    bus = TelegramEventBus()
    chat_id = 998877

    ctx = ScopedFlowContext()
    ctx.system["chat_id"] = chat_id
    ctx.system["last_sent_message_id"] = 100
    ctx.system["last_message_id"] = 100

    # 机器人发来带'签到'的提示消息 101
    captcha_ev = TelegramMessageEvent(
        event_id="ev_captcha_1",
        chat_id=chat_id,
        message_thread_id=None,
        message_id=101,
        sender_id=12345,
        event_type="NEW_MESSAGE",
        text="请在 30 秒内点击图中事物的按钮以完成签到",
        occurred_at=time.time(),
    )
    await bus.publish(captcha_ev)

    graph = ExecutionGraph(
        entry_node_id="step_1",
        nodes={
            "step_1": ActionNode(id="step_1", next_node_id="step_1_wait"),
            "step_1_wait": WaitEventNode(
                id="step_1_wait",
                event_type="NEW_MESSAGE",
                success_patterns=["签到"],
                timeout_seconds=3.0,
                next_node_id=TERMINAL_COMPLETE_ID,
            ),
        },
    )

    async def mock_executor(node, context):
        if node.id == "step_1":
            # 关键推进：推进 last_handled_message_id = 101
            context.system["last_handled_message_id"] = 101
            context.system["last_message_id"] = 101
            # 故意不设 last_action_started_at，纯靠 ID 水位线防御
            context.system.pop("last_action_started_at", None)
            context.system.pop("last_action_finished_at", None)
            return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)
        return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)

    engine = PulseFlowEngine(event_bus=bus)

    async def publish_real_reply_later():
        await asyncio.sleep(0.05)
        real_reply_ev = TelegramMessageEvent(
            event_id="ev_success_1",
            chat_id=chat_id,
            message_thread_id=None,
            message_id=102,
            sender_id=12345,
            event_type="NEW_MESSAGE",
            text="🎉 签到成功，获得了 4 积分",
            occurred_at=time.time(),
        )
        await bus.publish(real_reply_ev)

    task = asyncio.create_task(publish_real_reply_later())
    result = await engine.run(graph, ctx, mock_executor)
    await task

    assert result["status"] == "success"
    assert ctx.last_received_text == "🎉 签到成功，获得了 4 积分"
    wait_outcome = ctx.step_outcomes["step_1_wait"]
    assert "4 积分" in wait_outcome.output_text


@pytest.mark.asyncio
async def test_timestamp_filter_prevents_input_replay_without_handled_id():
    """变异守护靶向2：
    验证在未设置 last_handled_message_id（min_msg_id=100 < 101）时，
    时间戳协同防御（occurred_at >= since_timestamp - 0.2）也能精准剔除动作前到达的消息 101。
    （若去除时间戳过滤，本用例必红 Exit 1）
    """
    bus = TelegramEventBus()
    chat_id = 998878

    ctx = ScopedFlowContext()
    ctx.system["chat_id"] = chat_id
    ctx.system["last_sent_message_id"] = 100
    ctx.system["last_message_id"] = 100

    # 101 发生在过去（t1）
    t1 = time.time()
    captcha_ev = TelegramMessageEvent(
        event_id="ev_captcha_2",
        chat_id=chat_id,
        message_thread_id=None,
        message_id=101,
        sender_id=12345,
        event_type="NEW_MESSAGE",
        text="请在 30 秒内点击图中事物的按钮以完成签到",
        occurred_at=t1,
    )
    await bus.publish(captcha_ev)

    graph = ExecutionGraph(
        entry_node_id="step_1",
        nodes={
            "step_1": ActionNode(id="step_1", next_node_id="step_1_wait"),
            "step_1_wait": WaitEventNode(
                id="step_1_wait",
                event_type="NEW_MESSAGE",
                success_patterns=["签到"],
                timeout_seconds=3.0,
                next_node_id=TERMINAL_COMPLETE_ID,
            ),
        },
    )

    async def mock_executor(node, context):
        if node.id == "step_1":
            # 故意不推进 handled_id，仅记录动作发生在 t1 之后 0.5 秒
            await asyncio.sleep(0.3)
            now = time.time()
            context.system["last_action_started_at"] = now
            context.system["last_action_finished_at"] = now
            return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)
        return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)

    engine = PulseFlowEngine(event_bus=bus)

    async def publish_real_reply_later():
        await asyncio.sleep(0.4)
        real_reply_ev = TelegramMessageEvent(
            event_id="ev_success_2",
            chat_id=chat_id,
            message_thread_id=None,
            message_id=102,
            sender_id=12345,
            event_type="NEW_MESSAGE",
            text="🎉 签到成功，获得了 4 积分",
            occurred_at=time.time(),
        )
        await bus.publish(real_reply_ev)

    task = asyncio.create_task(publish_real_reply_later())
    result = await engine.run(graph, ctx, mock_executor)
    await task

    assert result["status"] == "success"
    assert ctx.last_received_text == "🎉 签到成功，获得了 4 积分"
    wait_outcome = ctx.step_outcomes["step_1_wait"]
    assert "4 积分" in wait_outcome.output_text

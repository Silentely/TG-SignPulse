import asyncio
import time

import pytest

from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_engine import PulseFlowEngine
from tg_signer.core.flow_event_bus import TelegramEventBus, TelegramMessageEvent
from tg_signer.core.flow_models import (
    ActionNode,
    ExecutionGraph,
    NodeStatus,
    TerminalPolicy,
    WaitEventNode,
)
from tg_signer.core.flow_normalizer import GraphNormalizer


def test_find_unreachable_nodes_and_warnings():
    nodes = {
        "step_1": ActionNode(id="step_1", next_node_id="_TERMINAL_COMPLETE"),
        "step_orphan_a": ActionNode(id="step_orphan_a", next_node_id="step_orphan_b"),
        "step_orphan_b": ActionNode(
            id="step_orphan_b", next_node_id="_TERMINAL_COMPLETE"
        ),
    }
    graph = ExecutionGraph(entry_node_id="step_1", nodes=nodes)
    unreachable = GraphNormalizer.find_unreachable_nodes(graph)
    assert unreachable == {"step_orphan_a", "step_orphan_b"}

    warnings = []
    GraphNormalizer.validate_graph(graph, warnings=warnings)
    assert len(warnings) == 2
    assert "step_orphan_a" in warnings[0]
    assert "step_orphan_b" in warnings[1]


def test_to_mermaid_highlights_unreachable_and_terminal_branch():
    nodes = {
        "s1": ActionNode(
            id="s1",
            terminal_policy=TerminalPolicy.BRANCH_TO,
            terminal_branch_target="s2",
            next_node_id="_TERMINAL_COMPLETE",
        ),
        "s2": ActionNode(id="s2", next_node_id="_TERMINAL_COMPLETE"),
        "s_dead": ActionNode(id="s_dead", next_node_id="_TERMINAL_COMPLETE"),
    }
    graph = ExecutionGraph(entry_node_id="s1", nodes=nodes)
    mermaid = GraphNormalizer.to_mermaid(graph)

    # 验证不可达样式高亮
    assert "s_dead (不可达)" in mermaid
    assert "style s_dead stroke:#f59e0b,stroke-dasharray: 5 5" in mermaid

    # 验证 terminal_branch 连线
    assert "s1 -.->|terminal_branch| s2" in mermaid


@pytest.mark.asyncio
async def test_wait_event_fails_gracefully_without_event_bus():
    node = WaitEventNode(
        id="wait_1",
        metadata={"chat_id": 12345},
        filter_patterns=[".*"],
        timeout_seconds=2.0,
    )
    graph = ExecutionGraph(entry_node_id="wait_1", nodes={"wait_1": node})
    engine = PulseFlowEngine(event_bus=None)
    ctx = ScopedFlowContext()

    executor_called = False

    async def fake_executor(n, c):
        nonlocal executor_called
        executor_called = True
        return None

    res = await engine.run(graph, ctx, fake_executor, event_bus=None)
    assert res["status"] == "failed"
    assert executor_called is False
    assert "未提供事件总线" in res.get("error", "")


@pytest.mark.asyncio
async def test_wait_event_matches_and_populates_event_details():
    node = WaitEventNode(
        id="wait_1",
        metadata={"chat_id": 999},
        filter_patterns=["code: \\d+"],
        timeout_seconds=3.0,
        next_node_id="_TERMINAL_COMPLETE",
    )
    graph = ExecutionGraph(entry_node_id="wait_1", nodes={"wait_1": node})
    bus = TelegramEventBus()
    engine = PulseFlowEngine(event_bus=bus)
    ctx = ScopedFlowContext()

    async def fake_executor(n, c):
        return None

    # 模拟外部事件生产者在稍后推送消息
    async def delayed_publish():
        await asyncio.sleep(0.05)
        ev = TelegramMessageEvent(
            event_id="ev_1",
            chat_id=999,
            message_thread_id=None,
            message_id=4567,
            sender_id=8888,
            event_type="NEW_MESSAGE",
            text="Your verification code: 123456",
            occurred_at=time.time(),
        )
        await bus.publish(ev)

    asyncio.create_task(delayed_publish())

    res = await engine.run(graph, ctx, fake_executor, event_bus=bus)
    assert res["status"] == "success"

    outcome = ctx.step_outcomes["wait_1"]
    assert outcome.status == NodeStatus.SUCCESS
    assert outcome.details["message_id"] == 4567
    assert outcome.details["sender_id"] == 8888
    assert outcome.details["chat_id"] == 999

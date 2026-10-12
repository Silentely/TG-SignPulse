import asyncio
import time
from unittest.mock import AsyncMock, MagicMock
import pytest

from tg_signer.config import (
    FlowNodeType,
    FlowStepConfig,
    SendTextAction,
    SignChatV3,
)
from tg_signer.core.flow_adapter import TelegramNodeExecutor
from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_engine import PulseFlowEngine
from tg_signer.core.flow_event_bus import TelegramEventBus, TelegramMessageEvent
from tg_signer.core.flow_normalizer import GraphNormalizer


@pytest.mark.asyncio
async def test_flow_full_lifecycle_all_control_nodes():
    """验证包含 Action, Delay, Extractor, Condition, Subflow, Parallel 等全控制节点的完整端到端生命周期"""
    chat_id = 998877

    chat = SignChatV3(
        chat_id=chat_id,
        steps=[
            FlowStepConfig(
                step_id="step_action",
                node_type=FlowNodeType.ACTION,
                action_type="SEND_TEXT",
                params={"text": "/checkin"},
                next_step_id="step_delay",
            ),
            FlowStepConfig(
                step_id="step_delay",
                node_type=FlowNodeType.DELAY,
                delay_seconds=0.01,
                next_step_id="step_extract",
            ),
            FlowStepConfig(
                step_id="step_extract",
                node_type=FlowNodeType.EXTRACTOR,
                variable_name="points",
                regex=r"Points:\s*(\d+)",
                next_step_id="step_cond",
            ),
            FlowStepConfig(
                step_id="step_cond",
                node_type=FlowNodeType.CONDITION,
                cases=[{"condition": "vars.points == 100", "target_id": "step_bonus"}],
                default_target_id="step_done",
            ),
            FlowStepConfig(
                step_id="step_bonus",
                node_type=FlowNodeType.SUBFLOW,
                subflow_graph={
                    "entry_node_id": "sub_1",
                    "nodes": {
                        "sub_1": {
                            "id": "sub_1",
                            "node_type": "delay",
                            "delay_seconds": 0.01,
                            "next_node_id": "_TERMINAL_COMPLETE",
                        }
                    },
                },
                next_step_id="step_parallel",
            ),
            FlowStepConfig(
                step_id="step_parallel",
                node_type=FlowNodeType.PARALLEL,
                branches=[
                    {
                        "entry_node_id": "p1",
                        "nodes": {
                            "p1": {
                                "id": "p1",
                                "node_type": "delay",
                                "delay_seconds": 0.01,
                                "next_node_id": "_TERMINAL_COMPLETE",
                            }
                        },
                    },
                    {
                        "entry_node_id": "p2",
                        "nodes": {
                            "p2": {
                                "id": "p2",
                                "node_type": "delay",
                                "delay_seconds": 0.01,
                                "next_node_id": "_TERMINAL_COMPLETE",
                            }
                        },
                    },
                ],
                next_step_id="step_done",
            ),
            FlowStepConfig(
                step_id="step_done",
                node_type=FlowNodeType.DELAY,
                delay_seconds=0.01,
                next_step_id="_TERMINAL_COMPLETE",
            ),
        ],
    )

    # 1. 编译并校验图
    graph = GraphNormalizer.from_chat(chat)
    GraphNormalizer.validate_graph(graph)

    # 2. 模拟 Runner 与 Executor
    mock_msg = MagicMock()
    mock_msg.text = "Congratulations! Points: 100 awarded."

    mock_runner = MagicMock()
    mock_runner.wait_for = AsyncMock(return_value=mock_msg)
    mock_runner.context = MagicMock()
    mock_runner.context.last_output = ""
    mock_runner.context.chat_messages = {}
    mock_runner.context.stop_after_current_action = False

    executor = TelegramNodeExecutor(mock_runner, chat, graph)
    engine = PulseFlowEngine()
    ctx = ScopedFlowContext()

    # 3. 运行 PulseFlowEngine
    result = await engine.run(graph, ctx, executor)

    # 4. 验证运行断言
    assert result["status"] == "success"
    # 验证提取出的变量
    assert ctx.get_var("points") == "100"
    # 验证执行路径覆盖分支：action -> delay -> extract -> cond -> bonus -> parallel -> done
    assert "step_action" in result["path"]
    assert "step_delay" in result["path"]
    assert "step_extract" in result["path"]
    assert "step_cond" in result["path"]
    assert "step_bonus" in result["path"]
    assert "step_parallel" in result["path"]
    assert "step_done" in result["path"]


@pytest.mark.asyncio
async def test_flow_wait_event_node_with_event_bus():
    """验证 WaitEventNode 在真实调度中自动注入 chat_id 并通过事件总线顺利恢复"""
    chat_id = 556677
    chat = SignChatV3(
        chat_id=chat_id,
        steps=[
            FlowStepConfig(
                step_id="w1",
                node_type=FlowNodeType.WAIT_EVENT,
                timeout_seconds=2,
                next_step_id="_TERMINAL_COMPLETE",
            )
        ],
    )

    graph = GraphNormalizer.from_chat(chat)
    assert graph.nodes["w1"].metadata.get("chat_id") == chat_id

    mock_runner = MagicMock()
    mock_runner.wait_for = AsyncMock(return_value=True)
    mock_runner.context = MagicMock()
    mock_runner.context.last_output = ""
    mock_runner.context.chat_messages = {}
    mock_runner.context.stop_after_current_action = False
    executor = TelegramNodeExecutor(mock_runner, chat, graph)

    bus = TelegramEventBus(buffer_size=10, buffer_ttl_seconds=300)
    engine = PulseFlowEngine(event_bus=bus)
    ctx = ScopedFlowContext()

    async def _emit_event_delayed():
        await asyncio.sleep(0.05)
        ev = TelegramMessageEvent(
            event_id="ev_test",
            chat_id=chat_id,
            message_thread_id=None,
            message_id=101,
            sender_id=888,
            event_type="NEW_MESSAGE",
            text="verification code arrived",
            occurred_at=time.time(),
        )
        await bus.publish(ev)

    task = asyncio.create_task(_emit_event_delayed())
    result = await engine.run(graph, ctx, executor, event_bus=bus)
    await task

    assert result["status"] == "success"
    assert result["path"] == ["w1"]


@pytest.mark.asyncio
async def test_legacy_actions_backward_compatibility_100_percent():
    """验证历史动作（actions）在全新架构下 100% 正常运行，零功能倒退"""
    chat = SignChatV3(
        chat_id=123,
        actions=[
            SendTextAction(text="/sign"),
        ],
    )
    graph = GraphNormalizer.from_chat(chat)
    mock_runner = MagicMock()
    mock_runner.wait_for = AsyncMock(return_value=True)
    mock_runner.context = MagicMock()
    mock_runner.context.last_output = ""
    mock_runner.context.chat_messages = {}
    mock_runner.context.stop_after_current_action = False

    executor = TelegramNodeExecutor(mock_runner, chat, graph)
    engine = PulseFlowEngine()
    ctx = ScopedFlowContext()

    result = await engine.run(graph, ctx, executor)
    assert result["status"] == "success"
    assert result["path"] == ["step_0"]
    assert mock_runner.wait_for.call_count == 1

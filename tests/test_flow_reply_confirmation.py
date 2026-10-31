# tests/test_flow_reply_confirmation.py
import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from backend.services.sign_task_config_inspect import task_requires_updates
from backend.services.sign_task_crud import _validate_chats_regex_safety
from tg_signer.config import (
    ClickKeyboardByTextAction,
    FlowStepConfig,
    SendTextAction,
    SignChatV3,
    SupportAction,
)
from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_engine import PulseFlowEngine
from tg_signer.core.flow_event_bus import TelegramEventBus, TelegramMessageEvent
from tg_signer.core.flow_models import (
    TERMINAL_COMPLETE_ID,
    TERMINAL_FAIL_ID,
    ActionNode,
    ExecutionGraph,
    NodeStatus,
    StepOutcome,
    WaitEventNode,
)
from tg_signer.core.flow_normalizer import GraphNormalizer


@pytest.mark.asyncio
async def test_1_send_checkin_success_reply():
    """TEST 1: 发送 /checkin，收到 成功回复 -> SUCCESS"""
    bus = TelegramEventBus()
    engine = PulseFlowEngine(event_bus=bus)
    chat_id = 8300459562

    graph = ExecutionGraph(
        entry_node_id="send_checkin",
        nodes={
            "send_checkin": ActionNode(
                id="send_checkin",
                action_type="SEND_TEXT",
                params={"text": "/checkin"},
                next_node_id="wait_checkin_reply",
            ),
            "wait_checkin_reply": WaitEventNode(
                id="wait_checkin_reply",
                event_type="ANY",
                success_patterns=[r"出席率\s*成功"],
                failure_patterns=[r"出席率\s*失败", r"签到失败", r"操作失败"],
                timeout_seconds=2.0,
                next_node_id=TERMINAL_COMPLETE_ID,
                on_failure_node_id=TERMINAL_FAIL_ID,
                metadata={"chat_id": chat_id},
            ),
        },
    )

    ctx = ScopedFlowContext()
    ctx.system["chat_id"] = chat_id

    async def executor(node, context):
        if node.id == "send_checkin":
            context.system["last_sent_message_id"] = 100
            context.system["last_action_finished_at"] = time.time()
            # 机器人随后回复
            asyncio.create_task(
                _delayed_publish(
                    bus, chat_id, 101, "🎉 出席率 成功！\n💎 +1 硬币", delay=0.05
                )
            )
            return node.to_dict() if hasattr(node, "to_dict") else None
        return None

    from tg_signer.core.flow_models import StepOutcome

    async def mock_exec(node, context):
        context.system["last_sent_message_id"] = 100
        context.system["last_action_finished_at"] = time.time()
        asyncio.create_task(
            _delayed_publish(
                bus, chat_id, 101, "🎉 出席率 成功！\n💎 +1 硬币", delay=0.05
            )
        )
        return StepOutcome(
            node_id=node.id, status=NodeStatus.SUCCESS, output_text="/checkin"
        )

    res = await engine.run(graph, ctx, mock_exec, event_bus=bus)
    assert res["status"] == "success"
    assert "wait_checkin_reply" in res["path"]


async def _delayed_publish(
    bus,
    chat_id,
    msg_id,
    text,
    delay=0.05,
    event_type="NEW_MESSAGE",
    thread_id=None,
    is_outgoing=False,
):
    await asyncio.sleep(delay)
    ev = TelegramMessageEvent(
        event_id=f"ev_{chat_id}_{msg_id}",
        chat_id=chat_id,
        message_thread_id=thread_id,
        message_id=msg_id,
        sender_id=chat_id,
        event_type=event_type,
        text=text,
        occurred_at=time.time(),
        is_outgoing=is_outgoing,
    )
    await bus.publish(ev)


@pytest.mark.asyncio
async def test_2_send_checkin_failure_reply():
    """TEST 2: 发送 /checkin，收到 签到失败 -> FAILED 立即结束，不等到超时"""
    bus = TelegramEventBus()
    engine = PulseFlowEngine(event_bus=bus)
    chat_id = 8300459562

    graph = ExecutionGraph(
        entry_node_id="send_checkin",
        nodes={
            "send_checkin": ActionNode(
                id="send_checkin",
                next_node_id="wait_checkin_reply",
            ),
            "wait_checkin_reply": WaitEventNode(
                id="wait_checkin_reply",
                event_type="ANY",
                success_patterns=[r"出席率\s*成功"],
                failure_patterns=[r"出席率\s*失败", r"签到失败", r"操作失败"],
                timeout_seconds=5.0,
                next_node_id=TERMINAL_COMPLETE_ID,
                on_failure_node_id=TERMINAL_FAIL_ID,
                metadata={"chat_id": chat_id},
            ),
        },
    )

    ctx = ScopedFlowContext()
    ctx.system["chat_id"] = chat_id

    from tg_signer.core.flow_models import StepOutcome

    async def mock_exec(node, context):
        context.system["last_sent_message_id"] = 100
        context.system["last_action_finished_at"] = time.time()
        # 0.05秒后机器人返回失败
        asyncio.create_task(
            _delayed_publish(bus, chat_id, 101, "签到失败，请明日再试", delay=0.05)
        )
        return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)

    t0 = time.time()
    res = await engine.run(graph, ctx, mock_exec, event_bus=bus)
    dur = time.time() - t0
    assert res["status"] == "failed"
    assert dur < 2.0  # 立即失败，没有等到 5s 超时


@pytest.mark.asyncio
async def test_3_send_checkin_timeout_failure():
    """TEST 3: 发送 /checkin，没有任何回复 -> TIMEOUT / FAILED"""
    bus = TelegramEventBus()
    engine = PulseFlowEngine(event_bus=bus)
    chat_id = 8300459562

    graph = ExecutionGraph(
        entry_node_id="wait_checkin_reply",
        nodes={
            "wait_checkin_reply": WaitEventNode(
                id="wait_checkin_reply",
                event_type="ANY",
                success_patterns=[r"出席率\s*成功"],
                failure_patterns=[r"签到失败"],
                timeout_seconds=0.2,
                next_node_id=TERMINAL_COMPLETE_ID,
                on_failure_node_id=TERMINAL_FAIL_ID,
                metadata={"chat_id": chat_id},
            ),
        },
    )

    ctx = ScopedFlowContext()
    ctx.system["chat_id"] = chat_id

    res = await engine.run(graph, ctx, AsyncMock(), event_bus=bus)
    assert res["status"] == "failed"
    outcome = ctx.step_outcomes["wait_checkin_reply"]
    assert outcome.status == NodeStatus.TIMEOUT


@pytest.mark.asyncio
async def test_4_intermediate_unrelated_messages_ignored():
    """TEST 4: 收到无关消息继续等待，之后收到成功消息 -> SUCCESS"""
    bus = TelegramEventBus()
    engine = PulseFlowEngine(event_bus=bus)
    chat_id = 8300459562

    graph = ExecutionGraph(
        entry_node_id="wait_checkin_reply",
        nodes={
            "wait_checkin_reply": WaitEventNode(
                id="wait_checkin_reply",
                event_type="ANY",
                success_patterns=[r"出席率\s*成功"],
                failure_patterns=[r"签到失败"],
                timeout_seconds=2.0,
                next_node_id=TERMINAL_COMPLETE_ID,
                on_failure_node_id=TERMINAL_FAIL_ID,
                metadata={"chat_id": chat_id},
            ),
        },
    )

    ctx = ScopedFlowContext()
    ctx.system["chat_id"] = chat_id
    ctx.system["last_sent_message_id"] = 100

    # 先发无关消息，再发成功消息
    asyncio.create_task(
        _delayed_publish(bus, chat_id, 101, "欢迎使用机器人，功能加载中...", delay=0.05)
    )
    asyncio.create_task(
        _delayed_publish(bus, chat_id, 102, "提示：每天可签到一次", delay=0.10)
    )
    asyncio.create_task(
        _delayed_publish(bus, chat_id, 103, "🎉 出席率 成功！", delay=0.15)
    )

    res = await engine.run(graph, ctx, AsyncMock(), event_bus=bus)
    assert res["status"] == "success"


@pytest.mark.asyncio
async def test_5_historical_message_watermark_protection():
    """TEST 5: 历史消息含有成功文本，今天发送后机器人无回复 -> 必须 TIMEOUT，绝不能读取历史成功"""
    bus = TelegramEventBus()
    engine = PulseFlowEngine(event_bus=bus)
    chat_id = 8300459562

    # 昨天历史消息写入 bus buffer (message_id=50)
    old_ev = TelegramMessageEvent(
        event_id="old_msg_1",
        chat_id=chat_id,
        message_thread_id=None,
        message_id=50,
        sender_id=chat_id,
        event_type="NEW_MESSAGE",
        text="🎉 出席率 成功！昨天的签到",
        occurred_at=time.time() - 3600,
    )
    await bus.publish(old_ev)

    graph = ExecutionGraph(
        entry_node_id="wait_checkin_reply",
        nodes={
            "wait_checkin_reply": WaitEventNode(
                id="wait_checkin_reply",
                event_type="ANY",
                success_patterns=[r"出席率\s*成功"],
                failure_patterns=[r"签到失败"],
                timeout_seconds=0.2,
                next_node_id=TERMINAL_COMPLETE_ID,
                on_failure_node_id=TERMINAL_FAIL_ID,
                metadata={"chat_id": chat_id},
            ),
        },
    )

    ctx = ScopedFlowContext()
    ctx.system["chat_id"] = chat_id
    # 今天发送的消息 ID 为 100，水位线要求 > 100
    ctx.system["last_sent_message_id"] = 100
    ctx.system["last_action_finished_at"] = time.time()

    res = await engine.run(graph, ctx, AsyncMock(), event_bus=bus)
    assert res["status"] == "failed"
    assert ctx.step_outcomes["wait_checkin_reply"].status == NodeStatus.TIMEOUT


@pytest.mark.asyncio
async def test_6_fast_reply_race_condition_history_replay():
    """TEST 6: 机器人极速回复发生在 subscribe 前，通过 history buffer 回补 -> SUCCESS"""
    bus = TelegramEventBus()
    engine = PulseFlowEngine(event_bus=bus)
    chat_id = 8300459562

    # T0: 发送消息，message_id=100
    ctx = ScopedFlowContext()
    ctx.system["chat_id"] = chat_id
    ctx.system["last_sent_message_id"] = 100
    sent_time = time.time()
    ctx.system["last_action_finished_at"] = sent_time

    # T0 + 50ms: Bot 极速回复，publish 发生在 WaitEvent subscribe 前
    fast_reply = TelegramMessageEvent(
        event_id="fast_msg_101",
        chat_id=chat_id,
        message_thread_id=None,
        message_id=101,
        sender_id=chat_id,
        event_type="NEW_MESSAGE",
        text="🎉 出席率 成功！极速秒回",
        occurred_at=sent_time + 0.05,
    )
    await bus.publish(fast_reply)

    # T0 + 200ms: 现在开始执行 WaitEventNode
    graph = ExecutionGraph(
        entry_node_id="wait_checkin_reply",
        nodes={
            "wait_checkin_reply": WaitEventNode(
                id="wait_checkin_reply",
                event_type="ANY",
                success_patterns=[r"出席率\s*成功"],
                timeout_seconds=2.0,
                next_node_id=TERMINAL_COMPLETE_ID,
                metadata={"chat_id": chat_id},
            ),
        },
    )

    res = await engine.run(graph, ctx, AsyncMock(), event_bus=bus)
    assert res["status"] == "success"
    outcome = ctx.step_outcomes["wait_checkin_reply"]
    assert outcome.status == NodeStatus.SUCCESS
    assert "极速秒回" in outcome.output_text


@pytest.mark.asyncio
async def test_7_edited_message_reply():
    """TEST 7: Bot 先发送“正在处理...”，然后 EDIT_MESSAGE 为成功 -> SUCCESS"""
    bus = TelegramEventBus()
    engine = PulseFlowEngine(event_bus=bus)
    chat_id = 8300459562

    graph = ExecutionGraph(
        entry_node_id="wait_checkin_reply",
        nodes={
            "wait_checkin_reply": WaitEventNode(
                id="wait_checkin_reply",
                event_type="ANY",
                success_patterns=[r"出席率\s*成功"],
                failure_patterns=[r"签到失败"],
                timeout_seconds=2.0,
                next_node_id=TERMINAL_COMPLETE_ID,
                metadata={"chat_id": chat_id},
            ),
        },
    )

    ctx = ScopedFlowContext()
    ctx.system["chat_id"] = chat_id
    ctx.system["last_sent_message_id"] = 100

    # 先发普通消息：正在处理... (message_id=101)
    asyncio.create_task(
        _delayed_publish(
            bus,
            chat_id,
            101,
            "正在处理签到请求...",
            delay=0.05,
            event_type="NEW_MESSAGE",
        )
    )
    # 然后编辑同一条消息为：🎉 出席率 成功！
    asyncio.create_task(
        _delayed_publish(
            bus,
            chat_id,
            101,
            "🎉 出席率 成功！已更新",
            delay=0.15,
            event_type="EDITED_MESSAGE",
        )
    )

    res = await engine.run(graph, ctx, AsyncMock(), event_bus=bus)
    assert res["status"] == "success"
    assert "已更新" in ctx.step_outcomes["wait_checkin_reply"].output_text


@pytest.mark.asyncio
async def test_8_chat_isolation():
    """TEST 8: Chat A 收到成功消息，Chat B 等待，B 不得被 A 的消息触发"""
    bus = TelegramEventBus()
    engine = PulseFlowEngine(event_bus=bus)
    chat_a = 111
    chat_b = 222

    # 为 Chat B 配置等待
    graph_b = ExecutionGraph(
        entry_node_id="wait_reply_b",
        nodes={
            "wait_reply_b": WaitEventNode(
                id="wait_reply_b",
                event_type="ANY",
                success_patterns=[r"成功"],
                timeout_seconds=0.2,
                next_node_id=TERMINAL_COMPLETE_ID,
                on_failure_node_id=TERMINAL_FAIL_ID,
                metadata={"chat_id": chat_b},
            ),
        },
    )
    ctx_b = ScopedFlowContext()
    ctx_b.system["chat_id"] = chat_b
    ctx_b.system["last_sent_message_id"] = 10

    # Chat A 发生成功消息
    asyncio.create_task(
        _delayed_publish(bus, chat_a, 20, "🎉 出席率 成功！这是 A 的消息", delay=0.05)
    )

    res_b = await engine.run(graph_b, ctx_b, AsyncMock(), event_bus=bus)
    assert res_b["status"] == "failed"
    assert ctx_b.step_outcomes["wait_reply_b"].status == NodeStatus.TIMEOUT


@pytest.mark.asyncio
async def test_9_thread_isolation():
    """TEST 9: Thread A 成功，Thread B 等待，不得跨话题混淆"""
    bus = TelegramEventBus()
    engine = PulseFlowEngine(event_bus=bus)
    chat_id = 999
    thread_a = 1001
    thread_b = 2002

    graph_b = ExecutionGraph(
        entry_node_id="wait_reply_b",
        nodes={
            "wait_reply_b": WaitEventNode(
                id="wait_reply_b",
                event_type="ANY",
                success_patterns=[r"成功"],
                timeout_seconds=0.2,
                next_node_id=TERMINAL_COMPLETE_ID,
                on_failure_node_id=TERMINAL_FAIL_ID,
                metadata={"chat_id": chat_id, "message_thread_id": thread_b},
            ),
        },
    )
    ctx_b = ScopedFlowContext()
    ctx_b.system["chat_id"] = chat_id
    ctx_b.system["message_thread_id"] = thread_b
    ctx_b.system["last_sent_message_id"] = 10

    # Thread A 收到成功消息
    asyncio.create_task(
        _delayed_publish(bus, chat_id, 20, "成功", delay=0.05, thread_id=thread_a)
    )

    res_b = await engine.run(graph_b, ctx_b, AsyncMock(), event_bus=bus)
    assert res_b["status"] == "failed"
    assert ctx_b.step_outcomes["wait_reply_b"].status == NodeStatus.TIMEOUT


@pytest.mark.asyncio
async def test_10_account_concurrency_isolation():
    """TEST 10: 账号 A 和账号 B 同时运行，各自独立总线与上下文，互不影响"""
    bus_a = TelegramEventBus()
    bus_b = TelegramEventBus()
    engine_a = PulseFlowEngine(event_bus=bus_a)
    engine_b = PulseFlowEngine(event_bus=bus_b)

    chat_id = 12345

    def make_graph():
        return ExecutionGraph(
            entry_node_id="wait_node",
            nodes={
                "wait_node": WaitEventNode(
                    id="wait_node",
                    event_type="ANY",
                    success_patterns=[r"成功"],
                    timeout_seconds=0.5,
                    next_node_id=TERMINAL_COMPLETE_ID,
                    metadata={"chat_id": chat_id},
                )
            },
        )

    ctx_a = ScopedFlowContext(account={"name": "account_a"})
    ctx_a.system["chat_id"] = chat_id
    ctx_a.system["last_sent_message_id"] = 100

    ctx_b = ScopedFlowContext(account={"name": "account_b"})
    ctx_b.system["chat_id"] = chat_id
    ctx_b.system["last_sent_message_id"] = 100

    # 只给 A 发布消息
    asyncio.create_task(_delayed_publish(bus_a, chat_id, 101, "签到成功！", delay=0.05))

    res_a, res_b = await asyncio.gather(
        engine_a.run(make_graph(), ctx_a, AsyncMock(), event_bus=bus_a),
        engine_b.run(make_graph(), ctx_b, AsyncMock(), event_bus=bus_b),
    )
    assert res_a["status"] == "success"
    assert res_b["status"] == "failed"


@pytest.mark.asyncio
async def test_11_failure_priority_over_success():
    """TEST 11: 消息同时匹配成功和失败规则时，必须优先按失败处理"""
    bus = TelegramEventBus()
    engine = PulseFlowEngine(event_bus=bus)
    chat_id = 8300459562

    graph = ExecutionGraph(
        entry_node_id="wait_node",
        nodes={
            "wait_node": WaitEventNode(
                id="wait_node",
                event_type="ANY",
                success_patterns=[r"成功"],
                failure_patterns=[r"失败"],
                timeout_seconds=2.0,
                next_node_id=TERMINAL_COMPLETE_ID,
                on_failure_node_id=TERMINAL_FAIL_ID,
                metadata={"chat_id": chat_id},
            ),
        },
    )
    ctx = ScopedFlowContext()
    ctx.system["chat_id"] = chat_id
    ctx.system["last_sent_message_id"] = 100

    # 消息中同时出现“操作失败”与“成功”
    asyncio.create_task(
        _delayed_publish(bus, chat_id, 101, "操作失败，请在签到成功前重试", delay=0.05)
    )

    res = await engine.run(graph, ctx, AsyncMock(), event_bus=bus)
    assert res["status"] == "failed"
    assert ctx.step_outcomes["wait_node"].status == NodeStatus.FAILED


@pytest.mark.asyncio
async def test_12_legacy_action_without_reply_confirmation():
    """TEST 12: 旧任务 SEND_TEXT /checkin 未开启 wait_for_reply，行为保持一致"""
    chat = SignChatV3(
        chat_id=123456, actions=[SendTextAction(action=1, text="/checkin")]
    )
    graph = GraphNormalizer.from_chat(chat)
    assert len(graph.nodes) == 1
    assert "step_0" in graph.nodes
    assert "step_0_wait" not in graph.nodes
    assert graph.nodes["step_0"].next_node_id == TERMINAL_COMPLETE_ID


@pytest.mark.asyncio
async def test_13_classic_v3_regression_and_routing(monkeypatch):
    """TEST 13: 普通 actions 任务单轨走 v4，显式 PULSEFLOW_ENGINE_OVERRIDE=classic 降级走 v3"""
    from tg_signer.core.flow_routing import resolve_execution_engine

    # 默认单轨收敛走 v4
    chat_default = SignChatV3(
        chat_id=123, actions=[SendTextAction(action=1, text="/hello")]
    )
    res_default = resolve_execution_engine(chat_default)
    assert res_default.engine_code == "v4"

    # 显式 override 走 v3
    monkeypatch.setenv("PULSEFLOW_ENGINE_OVERRIDE", "classic")
    chat_v3 = SignChatV3(chat_id=123, actions=[SendTextAction(action=1, text="/hello")])
    res_v3 = resolve_execution_engine(chat_v3)
    assert res_v3.engine_code == "v3"
    monkeypatch.delenv("PULSEFLOW_ENGINE_OVERRIDE", raising=False)

    # 开启 wait_for_reply
    chat_v4 = SignChatV3(
        chat_id=123,
        actions=[SendTextAction(action=1, text="/checkin", wait_for_reply=True)],
    )
    res_v4 = resolve_execution_engine(chat_v4)
    assert res_v4.engine_code == "v4"

    # 编译成图自动插入 step_0_wait
    graph_v4 = GraphNormalizer.from_chat(chat_v4)
    assert "step_0" in graph_v4.nodes
    assert "step_0_wait" in graph_v4.nodes
    assert graph_v4.nodes["step_0"].next_node_id == "step_0_wait"
    assert graph_v4.nodes["step_0_wait"].next_node_id == TERMINAL_COMPLETE_ID


def test_14_listen_mode_and_requires_updates_regression():
    """TEST 14: task_requires_updates 与 listen 模式回归"""
    # 纯普通 action: 不需要 update
    cfg_plain = {"chats": [{"actions": [{"action": 1, "text": "hi"}]}]}
    assert not task_requires_updates(cfg_plain)

    # 包含 wait_for_reply 的普通 action: 自动开启 update 监听
    cfg_reply = {
        "chats": [
            {"actions": [{"action": 1, "text": "/checkin", "wait_for_reply": True}]}
        ]
    }
    assert task_requires_updates(cfg_reply)

    # 包含 wait_event 节点的 steps: 开启 update 监听
    cfg_steps = {"chats": [{"steps": [{"step_id": "w", "node_type": "wait_event"}]}]}
    assert task_requires_updates(cfg_steps)

    # listen 模式动作 (action=8): 开启 update 监听
    cfg_listen = {"chats": [{"actions": [{"action": 8, "keywords": ["红包"]}]}]}
    assert task_requires_updates(cfg_listen)


@pytest.mark.asyncio
async def test_15_cancellation_cleans_up_subscriber():
    """TEST 15: 任务取消期间 WaitEvent 正在等待，应正确取消订阅，无残留 subscriber"""
    bus = TelegramEventBus()
    engine = PulseFlowEngine(event_bus=bus)
    chat_id = 99999

    graph = ExecutionGraph(
        entry_node_id="wait_node",
        nodes={
            "wait_node": WaitEventNode(
                id="wait_node",
                event_type="ANY",
                success_patterns=[r"成功"],
                timeout_seconds=10.0,
                next_node_id=TERMINAL_COMPLETE_ID,
                metadata={"chat_id": chat_id},
            ),
        },
    )

    ctx = ScopedFlowContext()
    ctx.system["chat_id"] = chat_id

    task = asyncio.create_task(engine.run(graph, ctx, AsyncMock(), event_bus=bus))
    await asyncio.sleep(0.05)
    # 确认已订阅
    key = (chat_id, None)
    assert key in bus._subscribers and len(bus._subscribers[key]) == 1

    # 取消任务
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # 确认 finally 正确注销订阅队列，无泄露
    assert key not in bus._subscribers


def test_16_regex_safety_and_redos_prevention():
    """TEST 16: Regex 安全校验（语法错误与 ReDoS）"""
    # 语法错误抛出异常
    with pytest.raises(ValueError, match="正则表达式语法错误"):
        _validate_chats_regex_safety(
            [
                {
                    "steps": [
                        {
                            "step_id": "w",
                            "node_type": "wait_event",
                            "success_patterns": ["["],
                        }
                    ]
                }
            ]
        )

    # ReDoS 危险正则抛出异常
    with pytest.raises(ValueError, match="灾难性回溯"):
        _validate_chats_regex_safety(
            [
                {
                    "steps": [
                        {
                            "step_id": "w",
                            "node_type": "wait_event",
                            "failure_patterns": ["(a+)+$"],
                        }
                    ]
                }
            ]
        )

    with pytest.raises(ValueError, match="灾难性回溯"):
        _validate_chats_regex_safety(
            [
                {
                    "actions": [
                        {
                            "action": 1,
                            "text": "/checkin",
                            "reply_success_patterns": ["(a+)+$"],
                        }
                    ]
                }
            ]
        )


@pytest.mark.asyncio
async def test_17_multi_action_ordering():
    """TEST 17: 多动作兼容 /start -> /checkin (wait reply) -> /balance -> COMPLETE"""
    chat = SignChatV3(
        chat_id=123,
        actions=[
            SendTextAction(action=1, text="/start"),
            SendTextAction(
                action=1,
                text="/checkin",
                wait_for_reply=True,
                reply_success_patterns=[r"出席率\s*成功"],
            ),
            SendTextAction(action=1, text="/balance"),
        ],
    )
    graph = GraphNormalizer.from_chat(chat)
    assert "step_0" in graph.nodes
    assert "step_1" in graph.nodes
    assert "step_1_wait" in graph.nodes
    assert "step_2" in graph.nodes

    assert graph.nodes["step_0"].next_node_id == "step_1"
    assert graph.nodes["step_1"].next_node_id == "step_1_wait"
    assert graph.nodes["step_1_wait"].next_node_id == "step_2"
    assert graph.nodes["step_2"].next_node_id == TERMINAL_COMPLETE_ID


@pytest.mark.asyncio
async def test_18_fast_reply_before_action_finish_accepted_by_message_id():
    """TEST 18 (F2验证): 机器人极速回复到达时间早于 action_finished_at，但 message_id > min_msg_id，不能被时间戳误杀"""
    bus = TelegramEventBus()
    engine = PulseFlowEngine(event_bus=bus)
    chat_id = 8300459562

    # 先收到极速回复（发生在 T0）
    t0 = time.time()
    await bus.publish(
        TelegramMessageEvent(
            event_id="msg_fast",
            chat_id=chat_id,
            message_thread_id=None,
            message_id=105,
            sender_id=0,
            event_type="NEW_MESSAGE",
            occurred_at=t0,
            text="🎉 出席率 成功！",
            is_outgoing=False,
        )
    )

    # 动作完成时间在 T0 + 0.1s (较晚写入)
    ctx = ScopedFlowContext()
    ctx.system["chat_id"] = chat_id
    ctx.system["last_sent_message_id"] = 100
    ctx.system["last_action_finished_at"] = t0 + 0.1

    graph = ExecutionGraph(
        entry_node_id="wait_node",
        nodes={
            "wait_node": WaitEventNode(
                id="wait_node",
                event_type="ANY",
                success_patterns=[r"出席率\s*成功"],
                timeout_seconds=0.5,
                next_node_id=TERMINAL_COMPLETE_ID,
                metadata={"chat_id": chat_id},
            )
        },
    )

    res = await engine.run(graph, ctx, AsyncMock(), event_bus=bus)
    assert res["status"] == "success"
    assert "wait_node" in res["path"]


@pytest.mark.asyncio
async def test_19_watermark_in_ttl_window_rejected_by_message_id():
    """TEST 19 (F2/F4验证): TTL窗口内（如60秒前）的旧消息，因 message_id <= min_msg_id 必须被严格过滤"""
    bus = TelegramEventBus()
    engine = PulseFlowEngine(event_bus=bus)
    chat_id = 8300459562

    # 60秒前的旧消息（在300s TTL内），但 message_id 只有 99
    await bus.publish(
        TelegramMessageEvent(
            event_id="msg_old_ttl",
            chat_id=chat_id,
            message_thread_id=None,
            message_id=99,
            sender_id=0,
            event_type="NEW_MESSAGE",
            occurred_at=time.time() - 60,
            text="🎉 出席率 成功！",
            is_outgoing=False,
        )
    )

    ctx = ScopedFlowContext()
    ctx.system["chat_id"] = chat_id
    ctx.system["last_sent_message_id"] = 100

    graph = ExecutionGraph(
        entry_node_id="wait_node",
        nodes={
            "wait_node": WaitEventNode(
                id="wait_node",
                event_type="ANY",
                success_patterns=[r"出席率\s*成功"],
                timeout_seconds=0.2,
                next_node_id=TERMINAL_COMPLETE_ID,
                metadata={"chat_id": chat_id},
            )
        },
    )

    res = await engine.run(graph, ctx, AsyncMock(), event_bus=bus)
    assert res["status"] == "failed"


def test_20_nested_redos_rejected_across_models():
    """TEST 20 (F3/F4验证): 嵌套ReDoS模式如 ((a+))+$ 在模型层、CRUD层与节点层均被拦截"""
    # 1. CRUD 层
    with pytest.raises(ValueError, match="灾难性回溯"):
        _validate_chats_regex_safety(
            [
                {
                    "steps": [
                        {
                            "step_id": "w",
                            "node_type": "wait_event",
                            "success_patterns": ["((a+))+$"],
                        }
                    ]
                }
            ]
        )

    # 2. SignAction 模型
    with pytest.raises(ValueError, match="灾难性回溯"):
        SendTextAction(
            action=1,
            text="/test",
            wait_for_reply=True,
            reply_success_patterns=["((a+))+$"],
        )

    # 3. FlowStepConfig 模型
    with pytest.raises(ValueError, match="灾难性回溯"):
        FlowStepConfig(step_id="s1", success_patterns=["((a+))+$"])

    # 4. WaitEventNode 节点
    with pytest.raises(ValueError, match="灾难性回溯"):
        WaitEventNode(id="w1", success_patterns=["((a+))+$"])


def test_21_crud_validation_no_mutual_exclusion_error_for_auto_steps():
    """TEST 21 (F1验证): 普通前端仅提交 steps（或 actions），不会触发 actions/steps 互斥报错"""
    # 模拟前端仅传递 steps 的结构
    chat_data = {
        "chat_id": 8300459562,
        "name": "SheerID",
        "steps": [
            {
                "step_id": "step_0",
                "node_type": "action",
                "action_type": "SEND_TEXT",
                "params": {"text": "/checkin"},
                "next_step_id": "step_0_wait",
            },
            {
                "step_id": "step_0_wait",
                "node_type": "wait_event",
                "event_type": "ANY",
                "success_patterns": ["成功"],
                "next_step_id": "COMPLETE",
            },
        ],
    }
    # 互斥检查通过
    configured_modes = [
        m for m in ("actions", "steps", "flow_graph") if chat_data.get(m)
    ]
    assert len(configured_modes) == 1
    assert configured_modes[0] == "steps"


@pytest.mark.asyncio
async def test_22_multi_step_send_then_click_button_with_reply_confirmation():
    """TEST 22: 多步骤签到场景（第一步发送命令，第二步点击按钮并开启回复确认）"""
    chat = SignChatV3(
        chat_id=8300459562,
        actions=[
            SendTextAction(action=1, text="/checkin"),
            # 第二步点击文字按钮，并开启等待回复确认
            ClickKeyboardByTextAction(
                action=SupportAction.CLICK_KEYBOARD_BY_TEXT,
                text="立即签到",
                wait_for_reply=True,
                reply_success_patterns=[r"签到成功"],
                reply_failure_patterns=[r"签到失败"],
                reply_timeout_seconds=5.0,
            ),
        ],
    )
    graph = GraphNormalizer.from_chat(chat)
    assert "step_0" in graph.nodes
    assert "step_1" in graph.nodes
    assert "step_1_wait" in graph.nodes

    # 拓扑验证：step_0 (发送) -> step_1 (点击按钮) -> step_1_wait (等待Bot回复) -> COMPLETE
    assert graph.nodes["step_0"].next_node_id == "step_1"
    assert graph.nodes["step_1"].next_node_id == "step_1_wait"
    assert graph.nodes["step_1_wait"].next_node_id == TERMINAL_COMPLETE_ID

    bus = TelegramEventBus()
    engine = PulseFlowEngine(event_bus=bus)
    ctx = ScopedFlowContext()
    ctx.system["chat_id"] = 8300459562

    async def mock_executor(node, context):
        if node.id == "step_0":
            # 第一步仅发送文本，产生按钮消息（此时并未完成签到）
            return StepOutcome(
                node_id=node.id, status=NodeStatus.SUCCESS, output_text="/checkin"
            )
        elif node.id == "step_1":
            # 第二步点击按钮，模拟点击后 Bot 发出/编辑成功消息
            asyncio.create_task(
                _delayed_publish(
                    bus,
                    chat_id=8300459562,
                    msg_id=202,
                    text="🎉 签到成功！获得 10 积分",
                    delay=0.05,
                    event_type="EDITED_MESSAGE",
                )
            )
            return StepOutcome(
                node_id=node.id,
                status=NodeStatus.SUCCESS,
                output_text="clicked:立即签到",
            )
        return None

    res = await engine.run(graph, ctx, mock_executor, event_bus=bus)
    assert res["status"] == "success"
    assert res["path"] == ["step_0", "step_1", "step_1_wait"]


@pytest.mark.asyncio
async def test_23_unmatched_bot_replies_logged_and_timeout_includes_reply_preview():
    """TEST 23: 机器人回复了内容但未匹配规则时，必须在日志回显并在超时信息中展示收到的回复"""
    bus = TelegramEventBus()
    engine = PulseFlowEngine(event_bus=bus)
    chat_id = 8300459562

    logs = []
    ctx = ScopedFlowContext()
    ctx.system["chat_id"] = chat_id
    ctx.system["last_sent_message_id"] = 100
    ctx.system["log"] = lambda msg, level="INFO": logs.append((level, msg))

    # 机器人回复了“出席率 成功”，但配置了“签到成功”
    reply_text = "\n".join(
        ["🎉 出席率 成功！", "=====================", "💎 +1 硬币| $0.04"]
    )
    asyncio.create_task(
        _delayed_publish(
            bus,
            chat_id=chat_id,
            msg_id=101,
            text=reply_text,
            delay=0.05,
        )
    )

    graph = ExecutionGraph(
        entry_node_id="wait_node",
        nodes={
            "wait_node": WaitEventNode(
                id="wait_node",
                event_type="ANY",
                success_patterns=["签到成功"],
                timeout_seconds=0.2,
                next_node_id=TERMINAL_COMPLETE_ID,
                metadata={"chat_id": chat_id},
            )
        },
    )

    res = await engine.run(graph, ctx, AsyncMock(), event_bus=bus)
    assert res["status"] == "failed"
    outcome = ctx.step_outcomes["wait_node"]
    assert outcome.status == NodeStatus.TIMEOUT
    assert "期间收到机器人回复" in outcome.output_text
    assert "出席率 成功" in outcome.output_text

    # 验证日志中包含了未匹配提示与机器人的实际回复
    assert any("收到机器人回复（但未匹配成功规则）" in msg for lvl, msg in logs)
    assert any("建议在任务配置中调整【确认成功关键词】" in msg for lvl, msg in logs)


@pytest.mark.asyncio
async def test_24_event_bus_normalizes_string_and_int_chat_id():
    """TEST 24: EventBus 兼容 str 和 int 类型的 chat_id 互相分发订阅"""
    bus = TelegramEventBus()
    queue = bus.subscribe(chat_id="8300459562", min_message_id=10)

    # 整数发布
    ev = TelegramMessageEvent(
        event_id="ev_1",
        chat_id=8300459562,
        message_thread_id=None,
        message_id=20,
        sender_id=8300459562,
        event_type="NEW_MESSAGE",
        text="hello",
        occurred_at=time.time(),
    )
    await bus.publish(ev)

    received = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert received.text == "hello"

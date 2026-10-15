# tests/test_flow_adapter.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

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
    ParallelNode,
    RetryPolicy,
    StepOutcome,
    SubflowNode,
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

    executor = TelegramNodeExecutor(mock_runner, chat, graph)
    engine = PulseFlowEngine()
    result = await engine.run(graph, ctx, executor)

    assert result["status"] == "success"
    assert result["path"] == ["step_0", "step_1"]
    assert mock_runner.wait_for.call_count == 2
    assert (
        mock_runner.wait_for.call_args_list[0].kwargs["next_action"].text == "确认领奖"
    )
    assert mock_runner.wait_for.call_args_list[1].kwargs["next_action"] is None


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


@pytest.mark.asyncio
async def test_adapter_delay_with_range_and_chat_fallback():
    # 验证随机区间延迟 "1-3" 以及 chat.action_interval 回退延迟
    chat = SignChatV3(
        chat_id=777,
        action_interval=2.5,
        actions=[
            SendTextAction(text="/cmd1", delay="1-2"),
            SendTextAction(text="/cmd2"),  # 没有显式 delay，应使用 action_interval
        ],
    )
    graph = GraphNormalizer.from_chat(chat)
    ctx = ScopedFlowContext()

    mock_runner = MagicMock()
    mock_runner.wait_for = AsyncMock(return_value=True)
    mock_runner.context = None

    # 模拟真实 runner._resolve_action_delay 支持 fallback_delay
    def mock_resolve_delay(act, fallback=0.0):
        if getattr(act, "delay", None) is not None:
            raw = str(act.delay)
            if "-" in raw:
                return 1.5
            return float(raw)
        return float(fallback)

    mock_runner._resolve_action_delay = MagicMock(side_effect=mock_resolve_delay)

    executor = TelegramNodeExecutor(mock_runner, chat)
    engine = PulseFlowEngine()

    with patch(
        "tg_signer.core.flow_adapter.asyncio.sleep", new_callable=AsyncMock
    ) as sleep:
        result = await engine.run(graph, ctx, executor)

    assert result["status"] == "success"
    assert sleep.call_count == 2
    delays = [call.args[0] for call in sleep.await_args_list]
    assert delays[0] == 1.5
    assert delays[1] == 2.5


@pytest.mark.asyncio
async def test_issue_13_multi_step_actions_flow_preservation_and_output_propagation():
    """验证 Issue #13 场景：动作1触发「签到成功」终态时，不被底层标记错误截断，且动作2能正常消费动作1的Telegram回复。"""
    chat = SignChatV3(
        chat_id=98765,
        actions=[
            SendTextAction(text="/qd"),  # stop_flow_on_terminal 为 False
            SendTextAction(text="下一动作，收到前一步: {{ prev.output }}"),
        ],
    )
    graph = GraphNormalizer.from_chat(chat)
    ctx = ScopedFlowContext()

    executed_actions = []

    mock_runner = MagicMock()
    mock_runner.context = MagicMock()
    mock_runner.context.chat_messages = {98765: {}}
    mock_runner.context.stop_after_current_action = False
    mock_runner.context.last_output = ""
    mock_runner.context.stop_reason = ""

    async def mock_wait_for(chat_obj, action_obj, next_action=None):
        executed_actions.append(action_obj)
        if action_obj.text == "/qd":
            # 模拟底层 Matcher 检测到「签到成功」并试图通过全局副作用截断
            mock_runner.context.stop_after_current_action = True
            mock_runner.context.stop_reason = "签到成功，获得50积分"
            # 模拟收到 Bot 回复消息
            mock_msg = MagicMock()
            mock_msg.id = 100
            mock_msg.text = "签到成功，获得50积分"
            mock_runner.context.chat_messages[98765][100] = mock_msg
        return True

    mock_runner.wait_for = AsyncMock(side_effect=mock_wait_for)

    executor = TelegramNodeExecutor(mock_runner, chat, graph)
    engine = PulseFlowEngine()
    result = await engine.run(graph, ctx, executor)

    # 1. 确保整个流程没有因动作1的“签到成功”而被丢弃截断
    assert result["status"] == "success"
    assert result["path"] == ["step_0", "step_1"]
    assert len(executed_actions) == 2

    # 2. 确保动作2正确渲染并获取到了动作1从 Telegram 拿到的回复输出
    second_action = executed_actions[1]
    assert "签到成功，获得50积分" in second_action.text


@pytest.mark.asyncio
async def test_issue_13_skip_if_matched_detects_realtime_bot_reply():
    """验证 Issue #13 场景：动作1执行后 Bot 回复“今日已签到”，动作2的 skip_if_matched 能及时感知该更新并顺利跳过。"""
    chat = SignChatV3(
        chat_id=55555,
        actions=[
            SendTextAction(text="/start"),
            SendTextAction(text="/daily_claim", skip_if_matched="今日已签到"),
        ],
    )
    graph = GraphNormalizer.from_chat(chat)
    ctx = ScopedFlowContext()

    mock_runner = MagicMock()
    mock_runner.context = MagicMock()
    mock_runner.context.chat_messages = {55555: {}}
    mock_runner.context.stop_after_current_action = False
    mock_runner.context.last_output = ""

    async def mock_wait_for(chat_obj, action_obj, next_action=None):
        if action_obj.text == "/start":
            # Bot 秒回消息写入 chat_messages
            mock_msg = MagicMock()
            mock_msg.id = 200
            mock_msg.text = "欢迎回来！今日已签到，请明天再来打卡。"
            mock_runner.context.chat_messages[55555][200] = mock_msg
        return True

    mock_runner.wait_for = AsyncMock(side_effect=mock_wait_for)

    executor = TelegramNodeExecutor(mock_runner, chat, graph)
    engine = PulseFlowEngine()
    result = await engine.run(graph, ctx, executor)

    assert result["status"] == "success"
    assert result["path"] == ["step_0", "step_1"]
    # 动作1执行过，动作2由于满足 skip_if_matched 判定被跳过，因此 wait_for 仅调用了一次
    assert mock_runner.wait_for.call_count == 1
    assert ctx.step_outcomes["step_1"].status == NodeStatus.SKIPPED


@pytest.mark.asyncio
async def test_adapter_flood_wait_auto_recovery():
    # 验证 Telegram FloodWait 异常时的自适应休眠与恢复重试
    class MockFloodWait(Exception):
        def __init__(self, value):
            self.value = value
            super().__init__(f"FLOOD_WAIT_{value}")

    node = ActionNode(
        id="flood_node",
        metadata={"raw_action": SendTextAction(text="/flood_cmd")},
    )
    graph = ExecutionGraph(entry_node_id="flood_node", nodes={"flood_node": node})
    ctx = ScopedFlowContext()

    mock_runner = MagicMock()
    # 第一次抛出 FloodWait(2)，第二次成功返回 True
    mock_runner.wait_for = AsyncMock(side_effect=[MockFloodWait(2), True])
    mock_runner.context = None

    chat = SignChatV3(chat_id=123, actions=[])
    executor = TelegramNodeExecutor(mock_runner, chat)
    engine = PulseFlowEngine()

    with patch(
        "tg_signer.core.flow_adapter.asyncio.sleep", new_callable=AsyncMock
    ) as sleep:
        result = await engine.run(graph, ctx, executor)

    assert result["status"] == "success"
    assert mock_runner.wait_for.call_count == 2
    assert any(call.args[0] == 3 for call in sleep.await_args_list)


@pytest.mark.asyncio
async def test_adapter_materialize_pure_action_node():
    """验证纯 ActionNode（无 metadata.raw_action）能正确材质化为强类型 SignAction。"""
    node = ActionNode(
        id="pure_node",
        action_type="SEND_TEXT",
        params={"text": "/pure_start {{ vars.token }}"},
    )
    graph = ExecutionGraph(entry_node_id="pure_node", nodes={"pure_node": node})
    ctx = ScopedFlowContext()
    ctx.set_var("token", "TOK_888")

    mock_runner = MagicMock()
    mock_runner.wait_for = AsyncMock(return_value=True)
    mock_runner.context = MagicMock()

    chat = SignChatV3(chat_id=123, actions=[])
    executor = TelegramNodeExecutor(mock_runner, chat)
    engine = PulseFlowEngine()

    result = await engine.run(graph, ctx, executor)
    assert result["status"] == "success"
    assert mock_runner.wait_for.call_count == 1
    call_action = mock_runner.wait_for.call_args[0][1]
    assert isinstance(call_action, SendTextAction)
    assert call_action.text == "/pure_start TOK_888"


@pytest.mark.asyncio
async def test_adapter_tracks_last_sent_message_id_in_system_context():
    """验证动作执行成功后，返回的 Message ID 被正确同步到 system 上下文供下游 WaitEventNode 使用。"""
    node = ActionNode(
        id="send_node",
        action_type="SEND_TEXT",
        params={"text": "/checkin"},
    )
    graph = ExecutionGraph(entry_node_id="send_node", nodes={"send_node": node})
    ctx = ScopedFlowContext()

    mock_msg = MagicMock()
    mock_msg.id = 10086

    mock_runner = MagicMock()
    mock_runner.wait_for = AsyncMock(return_value=mock_msg)
    mock_runner.context = MagicMock()

    chat = SignChatV3(chat_id=123, actions=[])
    executor = TelegramNodeExecutor(mock_runner, chat)
    engine = PulseFlowEngine()

    result = await engine.run(graph, ctx, executor)
    assert result["status"] == "success"
    assert ctx.system.get("last_sent_message_id") == 10086


# ---------------------------------------------------------------------------
# Lock release and lifecycle tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adapter_lock_release_on_cancellation():
    """验证当动作被外部 asyncio 取消时，_runner_state_lock 在 finally 块中可靠释放。"""
    chat = SignChatV3(chat_id=1234, actions=[SendTextAction(text="/hang")])
    graph = GraphNormalizer.from_chat(chat)
    ctx = ScopedFlowContext()

    entered_wait_for = asyncio.Event()
    release_wait_for = asyncio.Event()

    mock_runner = MagicMock()

    async def hanging_wait_for(chat_obj, action_obj, next_action=None, timeout=None):
        entered_wait_for.set()
        await release_wait_for.wait()
        return True

    mock_runner.wait_for = AsyncMock(side_effect=hanging_wait_for)
    mock_runner.context = MagicMock()

    executor = TelegramNodeExecutor(mock_runner, chat, graph)
    engine = PulseFlowEngine()

    run_task = asyncio.create_task(engine.run(graph, ctx, executor))
    await entered_wait_for.wait()

    # 验证执行中已持有锁
    assert executor._runner_state_lock.locked() is True

    # 外部取消任务
    run_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run_task

    # 核心断言：任务取消后，锁必须被可靠释放
    assert executor._runner_state_lock.locked() is False

    # 验证后续执行能够无死锁正常获取锁
    mock_runner.wait_for = AsyncMock(return_value=True)
    followup_outcome = await executor(graph.nodes["step_0"], ctx)
    assert followup_outcome.status == NodeStatus.SUCCESS
    assert executor._runner_state_lock.locked() is False


@pytest.mark.asyncio
async def test_adapter_lock_release_on_unhandled_exception():
    """验证在抛出未捕获异常时，_runner_state_lock 在 finally 块中可靠释放。"""
    chat = SignChatV3(chat_id=1234, actions=[])
    node = ActionNode(
        id="s_err",
        metadata={"raw_action": SendTextAction(text="/crash")},
    )
    ctx = ScopedFlowContext()

    mock_runner = MagicMock()
    mock_runner.wait_for = AsyncMock(
        side_effect=RuntimeError("Simulated unhandled error")
    )
    mock_runner.context = MagicMock()

    executor = TelegramNodeExecutor(mock_runner, chat)

    with pytest.raises(RuntimeError, match="Simulated unhandled error"):
        await executor(node, ctx)

    # 核心断言：异常抛出后，锁必须被可靠释放
    assert executor._runner_state_lock.locked() is False


@pytest.mark.asyncio
async def test_adapter_lock_release_during_parallel_branches():
    """验证在并行分支执行期间互斥串行化，且在正常完成与异常时均可靠释放锁。"""
    chat = SignChatV3(chat_id=8888, actions=[])
    branch_a = ExecutionGraph(
        entry_node_id="act_a",
        nodes={
            "act_a": ActionNode(
                id="act_a",
                metadata={"raw_action": SendTextAction(text="/a")},
            )
        },
    )
    branch_b = ExecutionGraph(
        entry_node_id="act_b",
        nodes={
            "act_b": ActionNode(
                id="act_b",
                metadata={"raw_action": SendTextAction(text="/b")},
            )
        },
    )
    parallel_node = ParallelNode(
        id="par_node",
        branches=[branch_a, branch_b],
    )
    graph = ExecutionGraph(
        entry_node_id="par_node",
        nodes={"par_node": parallel_node},
    )
    ctx = ScopedFlowContext()

    active_executions = 0
    max_active_executions = 0

    mock_runner = MagicMock()
    mock_runner.context = MagicMock()

    async def concurrent_wait_for(chat_obj, action_obj, next_action=None, timeout=None):
        nonlocal active_executions, max_active_executions
        active_executions += 1
        if active_executions > max_active_executions:
            max_active_executions = active_executions
        await asyncio.sleep(0.01)
        active_executions -= 1
        return True

    mock_runner.wait_for = AsyncMock(side_effect=concurrent_wait_for)

    executor = TelegramNodeExecutor(mock_runner, chat, graph)
    engine = PulseFlowEngine()

    result = await engine.run(graph, ctx, executor)
    assert result["status"] == "success"

    # 由于 _runner_state_lock 的保护，即使两个分支并行启动，对底层 runner 的调用始终是串行的
    assert max_active_executions == 1
    # 核心断言：并行分支结束后锁处于释放状态
    assert executor._runner_state_lock.locked() is False


@pytest.mark.asyncio
async def test_adapter_lock_release_during_subflows():
    """验证子图（SubflowNode）执行及其异常情况下锁的获取与释放生命周期。"""
    chat = SignChatV3(chat_id=9999, actions=[])
    subflow_graph = ExecutionGraph(
        entry_node_id="sub_step1",
        nodes={
            "sub_step1": ActionNode(
                id="sub_step1",
                next_node_id="sub_step2",
                metadata={"raw_action": SendTextAction(text="/sub1")},
            ),
            "sub_step2": ActionNode(
                id="sub_step2",
                metadata={"raw_action": SendTextAction(text="/sub2")},
            ),
        },
    )
    root_node = SubflowNode(
        id="subflow_root",
        subflow_graph=subflow_graph,
    )
    graph = ExecutionGraph(
        entry_node_id="subflow_root",
        nodes={"subflow_root": root_node},
    )
    ctx = ScopedFlowContext()

    mock_runner = MagicMock()
    mock_runner.context = MagicMock()
    mock_runner.wait_for = AsyncMock(return_value=True)

    executor = TelegramNodeExecutor(mock_runner, chat, graph)
    engine = PulseFlowEngine()

    res = await engine.run(graph, ctx, executor)
    assert res["status"] == "success"
    assert mock_runner.wait_for.call_count == 2
    # 核心断言：子图执行完成后锁完全释放
    assert executor._runner_state_lock.locked() is False


@pytest.mark.asyncio
async def test_adapter_action_context_and_side_effects_routed_via_bridge():
    """验证 action context 与 side_effect 标记完整经由 compat bridge 治理，且在异常时可靠清理。"""
    chat = SignChatV3(chat_id=777, actions=[SendTextAction(text="/test_action")])
    graph = GraphNormalizer.from_chat(chat)
    ctx = ScopedFlowContext()

    mock_runner = MagicMock()
    mock_runner.context = MagicMock()
    mock_runner.context.pulseflow_side_effect_started = False
    mock_runner.wait_for = AsyncMock(return_value=MagicMock(id=999, text="ack"))

    executor = TelegramNodeExecutor(mock_runner, chat, graph)
    engine = PulseFlowEngine()

    res = await engine.run(graph, ctx, executor)
    assert res["status"] == "success"

    # 验证 set 与 clear 动作上下文均被调用
    mock_runner._set_current_action_context.assert_called_once()
    mock_runner._clear_current_action_context.assert_called_once()
    # 验证副作用标记被正确更新
    assert mock_runner.context.pulseflow_side_effect_started is True

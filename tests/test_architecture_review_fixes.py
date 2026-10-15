import asyncio
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.sign_task_failure import (
    FAILURE_CATEGORY_TASK_LOOP_EXCEEDED,
    FailureCategory,
    classify_failure,
)
from backend.services.sign_task_history_index import clear_memory_cache
from backend.services.sign_task_history_store import SignTaskHistoryStore
from backend.services.sign_tasks import SignTaskService
from tg_signer.config import (
    SendTextAction,
    SignChatV3,
)
from tg_signer.core.flow_models import (
    FlowSignal,
    NodeStatus,
)
from tg_signer.core.plugin_host import (
    PluginProcessHost,
    get_active_worker_processes,
)
from tg_signer.core.plugin_runtime import (
    PluginRuntime,
    get_plugin_runtime,
)
from tg_signer.core.plugins import PluginContext
from tg_signer.core.signer_runner import SignerRunnerMixin
from tg_signer.core.workflow_engine import (
    WorkflowContext,
    WorkflowDefinition,
    WorkflowEngine,
    WorkflowLoopExceededError,
    WorkflowStep,
)

# ==============================================================================
# 1. Codex HIGH & MEDIUM 1: _CutoverNodeExecutor terminal handling & no monkeypatch
# ==============================================================================


@pytest.mark.asyncio
async def test_cutover_executor_ignores_terminal_when_policy_ignore():
    """验证当 terminal_policy 为 IGNORE 时，即使命中终态文本也不提前中止流程，正常执行后续步骤"""
    chat = SignChatV3(
        chat_id=12345,
        execution_engine="v4",
        actions=[
            SendTextAction(text="/checkin", terminal_keywords=["已签到"]),
            SendTextAction(text="/confirm"),
        ],
    )

    class DummyRunner(SignerRunnerMixin):
        def __init__(self):
            self.context = MagicMock()
            self.context.chat_messages = {}
            self.context.stop_after_current_action = False
            self.context.last_output = ""
            self.context.last_received_text = ""
            self.context.pulseflow_side_effect_started = False
            self.app = MagicMock()
            self.app.get_chat = AsyncMock(return_value=MagicMock(id=12345))
            self.wait_for = AsyncMock(return_value=True)
            self._describe_chat_run = MagicMock(return_value="Running chat")
            self.log = MagicMock()
            self._resolve_action_delay_called = False

        def _resolve_action_delay(self, action, interval=0.0):
            self._resolve_action_delay_called = True
            return 0.0

        def _set_current_action_context(self, idx, tot, act):
            return "running action"

        def _clear_current_action_context(self):
            pass

        def _current_action_step_label(self):
            return "第 1 步"

    runner = DummyRunner()

    async def mock_wait_for(*args, **kwargs):
        runner.context.last_received_text = "今日已签到（终态）"
        runner.context.last_output = "今日已签到（终态）"
        return True

    runner.wait_for = AsyncMock(side_effect=mock_wait_for)

    with patch.dict(os.environ, {"PULSEFLOW_AUTO_FALLBACK": "0"}):
        await runner.sign_a_chat(chat)

    # 两个步骤均应被执行，未被 HALT_SUCCESS 抢先截断
    assert runner.wait_for.call_count == 2
    assert runner.context.workflow_steps == 2
    # 验证没有遗留 monkeypatch
    assert (
        runner._resolve_action_delay.__name__ == "_resolve_action_delay"
        or runner._resolve_action_delay.__qualname__ == "DummyRunner._resolve_action_delay"
    )


@pytest.mark.asyncio
async def test_cutover_executor_failed_action_with_matched_terminal_reports_failure():
    """验证动作失败即使触发 matched_terminal，也绝不能被转换为 HALT_SUCCESS，必须报失败"""
    chat = SignChatV3(
        chat_id=12345,
        execution_engine="v4",
        actions=[
            SendTextAction(text="/checkin", terminal_keywords=["已签到"]),
        ],
    )

    class DummyRunner(SignerRunnerMixin):
        def __init__(self):
            self.context = MagicMock()
            self.context.chat_messages = {}
            self.context.stop_after_current_action = False
            self.context.last_output = ""
            self.context.last_received_text = ""
            self.context.pulseflow_side_effect_started = False
            self.app = MagicMock()
            self.app.get_chat = AsyncMock(return_value=MagicMock(id=12345))
            self._describe_chat_run = MagicMock(return_value="Running chat")
            self.log = MagicMock()

        def _resolve_action_delay(self, action, interval=0.0):
            return 0.0

        def _set_current_action_context(self, idx, tot, act):
            return "running"

        def _clear_current_action_context(self):
            pass

        def _current_action_step_label(self):
            return "第 1 步"

    runner = DummyRunner()

    async def mock_wait_for_fail(*args, **kwargs):
        runner.context.stop_after_current_action = True
        runner.context.last_received_text = "已签到，但发生系统错误"
        runner.context.last_output = "已签到，但发生系统错误"
        return False

    runner.wait_for = AsyncMock(side_effect=mock_wait_for_fail)

    with patch.dict(os.environ, {"PULSEFLOW_AUTO_FALLBACK": "0"}):
        with pytest.raises(RuntimeError) as exc_info:
            await runner.sign_a_chat(chat)
        assert "PulseFlow 执行失败" in str(exc_info.value)
        assert "已签到" in str(exc_info.value) or "returned False" in str(exc_info.value)


@pytest.mark.asyncio
async def test_cutover_executor_stop_after_current_action_branching():
    """验证 _CutoverNodeExecutor 真正调用时，stop_after_current_action 只有在动作成功时才赋予 HALT_SUCCESS，失败赋予 HALT_FAIL"""
    from tg_signer.core.flow_adapter import TelegramNodeExecutor
    from tg_signer.core.flow_models import ExecutionGraph, StepOutcome
    from tg_signer.core.signer_runner import _CutoverNodeExecutor

    chat = SignChatV3(
        chat_id=12345,
        execution_engine="v4",
        actions=[SendTextAction(text="/checkin")],
    )
    graph = ExecutionGraph.compile(chat)
    node = graph.nodes["step_0"]

    runner = MagicMock()
    runner.context = MagicMock()
    flow_ctx = MagicMock()

    executor = _CutoverNodeExecutor(runner, chat, graph)

    # 场景 1：动作失败 + stop_after_current_action=True -> 必须赋 HALT_FAIL
    runner.context.stop_after_current_action = True
    fail_outcome = StepOutcome(
        node_id="step_0",
        status=NodeStatus.FAILED,
        matched_terminal=False,
        output_text="Action failed",
    )
    with patch.object(TelegramNodeExecutor, "_call_unlocked", AsyncMock(return_value=fail_outcome)):
        outcome = await executor(node, flow_ctx)
        assert outcome.signal == FlowSignal.HALT_FAIL
        assert runner.context.stop_after_current_action is False

    # 场景 2：动作成功 + stop_after_current_action=True -> 赋予 HALT_SUCCESS
    runner.context.stop_after_current_action = True
    succ_outcome = StepOutcome(
        node_id="step_0",
        status=NodeStatus.SUCCESS,
        matched_terminal=False,
        output_text="Action success",
    )
    with patch.object(TelegramNodeExecutor, "_call_unlocked", AsyncMock(return_value=succ_outcome)):
        outcome = await executor(node, flow_ctx)
        assert outcome.signal == FlowSignal.HALT_SUCCESS
        assert runner.context.stop_after_current_action is False


# ==============================================================================
# 2. Codex MEDIUM 2: Cross-chat side effect isolation
# ==============================================================================


@pytest.mark.asyncio
async def test_cross_chat_side_effect_started_isolation():
    """验证多 chat 连续执行时，前一 chat 遗留的 side_effect 标记会在 sign_a_chat 入口被彻底清空"""
    chat1 = SignChatV3(chat_id=101, execution_engine="v4", actions=[SendTextAction(text="/one")])

    class DummyRunner(SignerRunnerMixin):
        def __init__(self):
            self.context = MagicMock()
            self.context.chat_messages = {}
            self.context.stop_after_current_action = False
            self.context.last_output = ""
            self.context.last_received_text = ""
            self.context.pulseflow_side_effect_started = True  # 遗留脏状态
            self.app = MagicMock()
            self.app.get_chat = AsyncMock(return_value=MagicMock(id=101))
            self._describe_chat_run = MagicMock(return_value="Running chat")
            self.log = MagicMock()
            self.wait_for = AsyncMock(return_value=True)

        def _resolve_action_delay(self, action, interval=0.0):
            return 0.0

        def _set_current_action_context(self, idx, tot, act):
            return "running"

        def _clear_current_action_context(self):
            pass

        def _current_action_step_label(self):
            return "第 1 步"

    runner = DummyRunner()
    assert runner.context.pulseflow_side_effect_started is True

    observed_flags = []

    async def mock_wait_for(*args, **kwargs):
        # 记录执行动作期间的标记值
        observed_flags.append(runner.context.pulseflow_side_effect_started)
        return True

    runner.wait_for = AsyncMock(side_effect=mock_wait_for)

    await runner.sign_a_chat(chat1)
    # 确认进入 sign_a_chat 顶部时立即被重置为了 False
    assert len(observed_flags) > 0
    assert observed_flags[0] is False


# ==============================================================================
# 3. Codex MEDIUM 3: Worker initialization drain exception in finally
# ==============================================================================


@pytest.mark.asyncio
async def test_worker_init_drain_broken_pipe_cleans_up():
    """验证 worker 进程在 init_payload 写入与 drain 发生 BrokenPipeError 时，仍能被 finally 正确 kill 并注销"""
    mock_ctx = MagicMock()
    mock_ctx.chat_id = 123
    mock_ctx.params = {}
    mock_ctx.message = None
    host = PluginProcessHost(plugin_name="test_plugin", ctx=mock_ctx, timeout=5.0)

    mock_proc = MagicMock()
    mock_proc.pid = 998877
    mock_proc.returncode = None
    mock_proc.wait = AsyncMock(return_value=0)

    mock_stdin = MagicMock()
    mock_stdin.write = MagicMock()
    mock_stdin.drain = AsyncMock(side_effect=BrokenPipeError("Broken pipe on worker init"))
    mock_stdin.close = MagicMock()
    mock_stdin.wait_closed = AsyncMock()

    mock_stdout = MagicMock()
    mock_stderr = MagicMock()

    mock_proc.stdin = mock_stdin
    mock_proc.stdout = mock_stdout
    mock_proc.stderr = mock_stderr

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
        with patch("tg_signer.core.plugin_host.kill_process_tree") as mock_kill_tree:
            with pytest.raises(BrokenPipeError):
                await host.execute()

            # 验证清理逻辑生效：kill_process_tree 被调用，stdin 被关闭，注册表被清空
            mock_kill_tree.assert_called_once_with(mock_proc.pid)
            mock_stdin.close.assert_called_once()
            assert len(get_active_worker_processes()) == 0


@pytest.mark.asyncio
async def test_worker_init_drain_timeout_cleans_up():
    """验证 worker 进程在 init_payload 写入后 drain 挂起时，受配置超时约束自动抛出 TimeoutError，kill 进程并注销"""
    mock_ctx = MagicMock()
    mock_ctx.chat_id = 123
    mock_ctx.params = {}
    mock_ctx.message = None
    host = PluginProcessHost(plugin_name="test_plugin", ctx=mock_ctx, timeout=0.05)

    mock_proc = MagicMock()
    mock_proc.pid = 887766
    mock_proc.returncode = None
    mock_proc.wait = AsyncMock(return_value=0)

    async def hanging_drain():
        await asyncio.sleep(5.0)

    mock_stdin = MagicMock()
    mock_stdin.write = MagicMock()
    mock_stdin.drain = AsyncMock(side_effect=hanging_drain)
    mock_stdin.close = MagicMock()
    mock_stdin.wait_closed = AsyncMock()

    mock_proc.stdin = mock_stdin
    mock_proc.stdout = MagicMock()
    mock_proc.stderr = MagicMock()

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
        with patch("tg_signer.core.plugin_host.kill_process_tree") as mock_kill_tree:
            with pytest.raises(TimeoutError) as exc_info:
                await host.execute()

            assert "timed out during initialization" in str(exc_info.value)
            assert host.process_terminated_by_kill is True
            mock_kill_tree.assert_called_with(mock_proc.pid)
            mock_stdin.close.assert_called_once()
            assert mock_proc not in get_active_worker_processes()


# ==============================================================================
# 4. Codex MEDIUM 4: PluginRuntime production seam
# ==============================================================================


def test_plugin_runtime_production_seam_registered():
    """验证全局 PluginRuntime 正确初始化且为单例生产 seam"""
    runtime = get_plugin_runtime()
    assert isinstance(runtime, PluginRuntime)
    assert get_plugin_runtime() is runtime


# ==============================================================================
# 5. Codex MEDIUM 5: WorkflowEngine delegates to PulseFlowEngine
# ==============================================================================


@pytest.mark.asyncio
async def test_workflow_engine_delegates_to_pulse_flow_engine():
    """验证旧版 WorkflowEngine.run() 完全委托给 PulseFlowEngine，拓扑与步数一致"""
    wf = WorkflowDefinition(
        steps=[
            WorkflowStep(step_id="w1", action_type="send", next_step_id="w2"),
            WorkflowStep(step_id="w2", action_type="send", next_step_id="COMPLETE"),
        ],
        initial_step_id="w1",
    )
    ctx = WorkflowContext(run_id="deleg_1", account_name="test_acc", task_name="test_task")

    executed_nodes = []

    async def mock_step_exec(step, c):
        executed_nodes.append(step.step_id)
        return True

    engine = WorkflowEngine()
    result = await engine.run(wf, ctx, mock_step_exec)

    assert result["status"] == "success"
    assert result["path"] == ["w1", "w2"]
    assert result["steps"] == 2
    assert executed_nodes == ["w1", "w2"]
    assert ctx.total_steps_executed == 2


@pytest.mark.asyncio
async def test_pulse_flow_engine_halt_fail_retains_error():
    """验证 PulseFlowEngine 在收到 HALT_FAIL 信号时，保留失败节点的错误信息并体现在返回的 error 字段中"""
    from tg_signer.core.flow_engine import PulseFlowEngine
    from tg_signer.core.flow_models import (
        ActionNode,
        ExecutionGraph,
        FlowSignal,
        NodeStatus,
        StepOutcome,
    )

    graph = ExecutionGraph(
        entry_node_id="node_1",
        nodes={
            "node_1": ActionNode(id="node_1", action_type="SEND_TEXT", params={"text": "hello"}),
        },
    )
    engine = PulseFlowEngine()
    ctx = MagicMock()
    ctx.variables = {}
    ctx.execution_path = []
    ctx.metrics = {}

    async def mock_executor(node, context):
        return StepOutcome(
            node_id=node.id,
            status=NodeStatus.FAILED,
            signal=FlowSignal.HALT_FAIL,
            output_text="Explicit failure detail from remote bot",
        )

    res = await engine.run(graph, ctx, mock_executor)
    assert res["status"] == "failed"
    assert res.get("error") == "Explicit failure detail from remote bot"


@pytest.mark.asyncio
async def test_workflow_engine_propagates_underlying_res_error():
    """验证 WorkflowEngine 兼容层在底层 PulseFlowEngine 返回失败时，完整透传 res['error']"""
    from tg_signer.core.workflow_engine import (
        WorkflowDefinition,
        WorkflowEngine,
        WorkflowStep,
    )

    wf = WorkflowDefinition(
        initial_step_id="step_1",
        steps=[WorkflowStep(step_id="step_1", action_type="send_text")],
    )
    engine = WorkflowEngine()
    ctx = MagicMock()
    ctx.total_steps_executed = 0
    ctx.max_total_steps = 10
    ctx.execution_path = []
    ctx.current_step_id = "step_1"

    async def failing_step_executor(step, c):
        return False

    res = await engine.run(wf, ctx, failing_step_executor)
    assert res["status"] == "failed"
    assert "error" in res
    assert res["error"] is not None


# ==============================================================================
# 6. Grok Regression 1: Mojibake repair hook restored in history store
# ==============================================================================


def test_history_store_mojibake_repair(tmp_path):
    """验证 SignTaskHistoryStore 默认配置 repair_mojibake，且能真实修复 GBK 乱码样本"""
    from backend.services.sign_task_text import repair_mojibake

    store = SignTaskHistoryStore(history_dir=tmp_path / "history", signs_dir=tmp_path / "signs")
    assert store.repair is repair_mojibake

    # 使用真实 GBK 误读样本测试默认 repair 钩子
    original = "签到任务"
    mojibake_text = original.encode("utf-8").decode("gbk", errors="strict")  # 产生 绛惧埌浠诲姟
    assert mojibake_text != original

    store.record_run(
        account="acc_test",
        task="task_test",
        entry={
            "success": True,
            "message": mojibake_text,
            "flow_logs": [mojibake_text],
        },
    )

    entries = store.query_history(account="acc_test", task="task_test")
    assert len(entries) == 1
    assert entries[0]["message"] == "签到任务"
    assert entries[0]["flow_logs"][0] == "签到任务"

    # 自定义 repair 钩子同样支持
    custom_store = SignTaskHistoryStore(
        history_dir=tmp_path / "history2",
        signs_dir=tmp_path / "signs2",
        repair=lambda s: s.replace("MOJIBAKE", "REPAIRED"),
    )
    custom_store.record_run(
        account="acc_test2",
        task="task_test2",
        entry={
            "success": True,
            "message": "Status: MOJIBAKE",
            "flow_logs": ["Log line: MOJIBAKE"],
        },
    )
    custom_entries = custom_store.query_history(account="acc_test2", task="task_test2")
    assert len(custom_entries) == 1
    assert "REPAIRED" in custom_entries[0]["message"]
    assert "REPAIRED" in custom_entries[0]["flow_logs"][0]


# ==============================================================================
# 7. Grok Regression 2: Account history not truncated to 50 when limit=None
# ==============================================================================


def test_account_history_logs_untruncated(tmp_path):
    """验证账号级历史记录在 limit=None 时读取全部条目（>50 条），不再被静默截断为 50 条"""
    clear_memory_cache()
    service = SignTaskService()
    service.history_store = SignTaskHistoryStore(
        history_dir=tmp_path / "history", signs_dir=tmp_path / "signs", max_entries_per_file=100
    )

    acc = f"my_account_{uuid.uuid4().hex[:8]}"

    # 写入 65 条历史记录
    for i in range(65):
        service.history_store.record_run(
            account=acc,
            task="task_a",
            entry={
                "success": True,
                "message": f"run #{i}",
                "created_at": f"2026-10-15T10:{i:02d}:00Z",
            },
        )

    # 默认调用或显式 limit=None 读取
    full_logs = service.get_account_history_logs(acc, limit=None)
    assert len(full_logs) == 65

    # 显式 limit=10 仍正常截断
    ten_logs = service.get_account_history_logs(acc, limit=10)
    assert len(ten_logs) == 10


# ==============================================================================
# 8. Grok Issue 3: PluginContext write operations trigger side effect marker
# ==============================================================================


@pytest.mark.asyncio
async def test_plugin_context_write_methods_trigger_side_effect():
    """验证 PluginContext 的所有外部网络写方法均会标记 pulseflow_side_effect_started = True"""
    mock_runner = MagicMock()
    mock_runner.context = MagicMock()
    mock_runner.context.pulseflow_side_effect_started = False

    mock_client = MagicMock()
    mock_client.send_message = AsyncMock()
    mock_client.send_photo = AsyncMock()
    mock_client.request_callback_answer = AsyncMock()
    mock_client.send_reaction = AsyncMock()
    mock_client.edit_message_text = AsyncMock()
    mock_client.delete_messages = AsyncMock()
    mock_client.pin_chat_message = AsyncMock()
    mock_client.unpin_chat_message = AsyncMock()
    mock_client.forward_messages = AsyncMock()

    mock_msg = MagicMock()
    mock_msg.click = AsyncMock()

    ctx = PluginContext(
        app=mock_client,
        chat_id=123,
        message=mock_msg,
        logger=mock_runner,
    )
    ctx.runner = mock_runner

    write_calls = [
        lambda: ctx.send_message("hello"),
        lambda: ctx.send_photo("photo.jpg"),
        lambda: ctx.click("btn", message_id=1),
        lambda: ctx.react(message_id=1, emoji="👍"),
        lambda: ctx.edit_message(message_id=1, text="edited"),
        lambda: ctx.delete_message(message_id=1),
        lambda: ctx.pin_message(message_id=1),
        lambda: ctx.unpin_message(message_id=1),
        lambda: ctx.forward_messages(chat_id=456, message_ids=[1]),
    ]

    for call in write_calls:
        mock_runner.context.pulseflow_side_effect_started = False
        res = call()
        if asyncio.iscoroutine(res):
            await res
        assert (
            mock_runner.context.pulseflow_side_effect_started is True
        ), f"Failed to mark side effect for {call}"


# ==============================================================================
# 9. Grok M7: Task loop exceeded classification not masked by proxy output
# ==============================================================================


def test_classify_failure_task_loop_exceeded_not_masked_by_proxy():
    """验证错误信息包含循环熔断且 output 中包含代理连接信息时，准确分类为 TASK_LOOP_EXCEEDED 而非 NETWORK"""
    error = WorkflowLoopExceededError("工作流步骤 step1 执行次数 (4) 超过允许上限 3")
    output = "Proxy connection socks5://127.0.0.1:1080 connected, then looped"

    cat = classify_failure(error=error, output=output, success=False)
    assert cat == FailureCategory.TASK_LOOP_EXCEEDED
    assert cat.value == FAILURE_CATEGORY_TASK_LOOP_EXCEEDED

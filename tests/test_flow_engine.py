# tests/test_flow_engine.py
import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_engine import PulseFlowEngine
from tg_signer.core.flow_event_bus import TelegramEventBus, TelegramMessageEvent
from tg_signer.core.flow_models import (
    TERMINAL_COMPLETE_ID,
    TERMINAL_FAIL_ID,
    ActionNode,
    ConditionNode,
    DelayNode,
    ExecutionGraph,
    ExtractorNode,
    FlowSignal,
    NodeStatus,
    RetryPolicy,
    StepOutcome,
    SubflowNode,
    TerminalPolicy,
    WaitEventNode,
)


@pytest.mark.asyncio
async def test_flow_engine_executes_linear_graph_ignoring_terminal():
    # Issue #13 核心防线：第 1 步收到“签到成功”，但 terminal_policy 为 IGNORE，必须继续执行第 2 步！
    graph = ExecutionGraph(
        entry_node_id="step_1",
        nodes={
            "step_1": ActionNode(
                id="step_1",
                next_node_id="step_2",
                terminal_policy=TerminalPolicy.IGNORE,
            ),
            "step_2": ActionNode(
                id="step_2",
                next_node_id=TERMINAL_COMPLETE_ID,
            ),
        },
    )
    ctx = ScopedFlowContext()
    executed_steps = []

    async def mock_executor(node, context):
        executed_steps.append(node.id)
        if node.id == "step_1":
            return StepOutcome(
                node_id="step_1",
                status=NodeStatus.SUCCESS,
                matched_terminal=True,
                output_text="签到成功",
            )
        return StepOutcome(node_id="step_2", status=NodeStatus.SUCCESS)

    engine = PulseFlowEngine()
    result = await engine.run(graph, ctx, mock_executor)
    assert result["status"] == "success"
    assert executed_steps == ["step_1", "step_2"]
    assert "duration_ms" in result
    assert result["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_terminal_policy_not_triggered_on_action_failure():
    # 动作失败时即使 matched_terminal=True，绝不提前成功退出
    graph = ExecutionGraph(
        entry_node_id="step_failed",
        nodes={
            "step_failed": ActionNode(
                id="step_failed",
                terminal_policy=TerminalPolicy.STOP_FLOW,
                on_failure_node_id=TERMINAL_FAIL_ID,
            ),
        },
    )
    ctx = ScopedFlowContext()

    async def mock_executor(node, context):
        return StepOutcome(
            node_id="step_failed",
            status=NodeStatus.FAILED,
            matched_terminal=True,
        )

    engine = PulseFlowEngine()
    result = await engine.run(graph, ctx, mock_executor)
    assert result["status"] == "failed"


@pytest.mark.asyncio
async def test_extractor_and_condition_nodes_pipeline():
    # 验证 ExtractorNode -> ConditionNode -> 动作管道端到端闭环
    graph = ExecutionGraph(
        entry_node_id="ext_node",
        nodes={
            "ext_node": ExtractorNode(
                id="ext_node",
                regex=r"Token=(?P<token>[A-Z0-9]+)",
                export_vars={"token": "auth_token"},
                next_node_id="cond_node",
            ),
            "cond_node": ConditionNode(
                id="cond_node",
                cases=[
                    {
                        "condition": "'ABC' in vars.auth_token",
                        "target_id": "step_target",
                    },
                ],
                default_target_id=TERMINAL_FAIL_ID,
            ),
            "step_target": ActionNode(
                id="step_target",
                next_node_id=TERMINAL_COMPLETE_ID,
            ),
        },
    )
    ctx = ScopedFlowContext()
    ctx.last_output = "登录响应：Token=ABC889，请查收"
    executed = []

    async def mock_executor(node, context):
        executed.append(node.id)
        return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)

    engine = PulseFlowEngine()
    result = await engine.run(graph, ctx, mock_executor)
    assert result["status"] == "success"
    assert "step_target" in executed
    assert ctx.get_var("auth_token") == "ABC889"


@pytest.mark.asyncio
async def test_extractor_with_custom_source_field():
    # 验证指定 source_field 路径提取变量（而非仅限制于 prev.output）
    graph = ExecutionGraph(
        entry_node_id="ext_custom",
        nodes={
            "ext_custom": ExtractorNode(
                id="ext_custom",
                source_field="steps.first_step.output",
                regex=r"Code: (?P<code>\d+)",
                export_vars={"code": "auth_code"},
                next_node_id=TERMINAL_COMPLETE_ID,
            ),
        },
    )
    ctx = ScopedFlowContext()
    ctx.record_step_outcome(
        StepOutcome(
            node_id="first_step", status=NodeStatus.SUCCESS, output_text="Code: 665544"
        )
    )
    # 设置中间输出覆盖 last_output
    ctx.last_output = "Another step output without code"

    async def mock_executor(node, context):
        return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)

    engine = PulseFlowEngine()
    result = await engine.run(graph, ctx, mock_executor)
    assert result["status"] == "success"
    assert ctx.get_var("auth_code") == "665544"


@pytest.mark.asyncio
async def test_extractor_diagnostic_does_not_replace_user_visible_previous_output():
    graph = ExecutionGraph(
        entry_node_id="extract",
        nodes={
            "extract": ExtractorNode(
                id="extract",
                regex=r"Token=(?P<token>[A-Z0-9]+)",
                export_vars={"token": "auth_token"},
                next_node_id="action",
            ),
            "action": ActionNode(id="action", next_node_id=TERMINAL_COMPLETE_ID),
        },
    )
    ctx = ScopedFlowContext()
    ctx.last_output = "Telegram response: Token=ABC889"
    observed_outputs = []

    async def mock_executor(node, context):
        observed_outputs.append(context.last_output)
        return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)

    result = await PulseFlowEngine().run(graph, ctx, mock_executor)

    assert result["status"] == "success"
    assert observed_outputs == ["Telegram response: Token=ABC889"]
    assert ctx.get_var("auth_token") == "ABC889"


@pytest.mark.asyncio
async def test_retry_signal_uses_exponential_backoff_before_next_attempt():
    graph = ExecutionGraph(
        entry_node_id="retry_step",
        nodes={
            "retry_step": ActionNode(
                id="retry_step",
                next_node_id=TERMINAL_COMPLETE_ID,
                retry_policy=RetryPolicy(
                    max_attempts=3,
                    backoff_seconds=0.1,
                    backoff_multiplier=2.0,
                    max_backoff_seconds=1.0,
                ),
            )
        },
    )
    ctx = ScopedFlowContext()
    outcomes = [
        StepOutcome(
            node_id="retry_step",
            status=NodeStatus.PENDING,
            signal=FlowSignal.RETRY_NODE,
        ),
        StepOutcome(
            node_id="retry_step",
            status=NodeStatus.PENDING,
            signal=FlowSignal.RETRY_NODE,
        ),
        StepOutcome(node_id="retry_step", status=NodeStatus.SUCCESS),
    ]

    async def mock_executor(node, context):
        return outcomes.pop(0)

    with patch(
        "tg_signer.core.flow_engine.asyncio.sleep", new_callable=AsyncMock
    ) as sleep:
        result = await PulseFlowEngine().run(graph, ctx, mock_executor)

    assert result["status"] == "success"
    assert [call.args for call in sleep.await_args_list] == [(0.1,), (0.2,)]


@pytest.mark.asyncio
async def test_delay_node_native_execution():
    graph = ExecutionGraph(
        entry_node_id="delay_1",
        nodes={
            "delay_1": DelayNode(
                id="delay_1",
                seconds=0.01,
                next_node_id="action_done",
            ),
            "action_done": ActionNode(
                id="action_done",
                next_node_id=TERMINAL_COMPLETE_ID,
            ),
        },
    )
    ctx = ScopedFlowContext()
    executed = []

    async def mock_executor(node, context):
        executed.append(node.id)
        return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)

    engine = PulseFlowEngine()
    result = await engine.run(graph, ctx, mock_executor)

    assert result["status"] == "success"
    assert result["path"] == ["delay_1", "action_done"]
    assert executed == ["action_done"]
    delay_outcome = ctx.step_outcomes["delay_1"]
    assert delay_outcome.status == NodeStatus.SUCCESS
    assert "0.01" in delay_outcome.output_text


@pytest.mark.asyncio
async def test_wait_event_node_with_event_bus():
    bus = TelegramEventBus(buffer_size=10, buffer_ttl_seconds=300)
    # 发布消息到总线
    event = TelegramMessageEvent(
        event_id="ev_101",
        chat_id=12345,
        message_thread_id=None,
        message_id=50,
        sender_id=999,
        event_type="NEW_MESSAGE",
        text="验证码: 778899",
        occurred_at=time.time(),
    )
    await bus.publish(event)

    graph = ExecutionGraph(
        entry_node_id="wait_code",
        nodes={
            "wait_code": WaitEventNode(
                id="wait_code",
                filter_patterns=[r"\d{6}"],
                timeout_seconds=2.0,
                metadata={"chat_id": 12345, "min_message_id": 0},
                next_node_id=TERMINAL_COMPLETE_ID,
            )
        },
    )
    ctx = ScopedFlowContext()

    async def mock_executor(node, context):
        return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)

    engine = PulseFlowEngine(event_bus=bus)
    result = await engine.run(graph, ctx, mock_executor)

    assert result["status"] == "success"
    assert ctx.last_output == "验证码: 778899"


@pytest.mark.asyncio
async def test_node_execution_records_duration_and_timeout_status():
    graph = ExecutionGraph(
        entry_node_id="slow_node",
        nodes={
            "slow_node": ActionNode(
                id="slow_node",
                timeout_seconds=0.05,
                next_node_id=TERMINAL_COMPLETE_ID,
                on_failure_node_id=TERMINAL_FAIL_ID,
            )
        },
    )
    ctx = ScopedFlowContext()

    async def mock_executor(node, context):
        await asyncio.sleep(0.2)
        return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)

    engine = PulseFlowEngine()
    result = await engine.run(graph, ctx, mock_executor)

    assert result["status"] == "failed"
    outcome = ctx.step_outcomes["slow_node"]
    assert outcome.status == NodeStatus.TIMEOUT
    assert outcome.duration_ms > 0


@pytest.mark.asyncio
async def test_extractor_numeric_groups_json_and_required():
    # 测试数字索引捕获组
    ext_node = ExtractorNode(
        id="ext_numeric",
        regex=r"User:\s+(\w+)\s+ID:\s+(\d+)",
        export_vars={"0": "full_match", "1": "username", "2": "user_id"},
        next_node_id=TERMINAL_COMPLETE_ID,
    )
    ctx = ScopedFlowContext()
    ctx.last_output = "User: bob ID: 1002"
    engine = PulseFlowEngine()

    outcome = engine._run_extractor_node(ext_node, ctx)
    assert outcome.status == NodeStatus.SUCCESS
    assert outcome.extracted_vars["full_match"] == "User: bob ID: 1002"
    assert outcome.extracted_vars["username"] == "bob"
    assert outcome.extracted_vars["user_id"] == "1002"

    # 测试 JSON 提取
    json_node = ExtractorNode(
        id="ext_json",
        metadata={"extract_json": True},
        export_vars={"profile.score": "score", "token": "token"},
        next_node_id=TERMINAL_COMPLETE_ID,
    )
    ctx.last_output = '{"token": "xyz99", "profile": {"score": 98}}'
    outcome_json = engine._run_extractor_node(json_node, ctx)
    assert outcome_json.status == NodeStatus.SUCCESS
    assert outcome_json.extracted_vars["token"] == "xyz99"
    assert outcome_json.extracted_vars["score"] == 98

    # 测试 required 提取失败
    req_node = ExtractorNode(
        id="ext_req",
        regex=r"MISSING_PATTERN",
        metadata={"required": True},
    )
    outcome_req = engine._run_extractor_node(req_node, ctx)
    assert outcome_req.status == NodeStatus.FAILED


@pytest.mark.asyncio
async def test_condition_node_sentinel_normalization():
    # 验证 ConditionNode 目标为 "COMPLETE" 或 "FAIL" 字符串时自动正规化为 _TERMINAL_COMPLETE / _TERMINAL_FAIL
    graph = ExecutionGraph(
        entry_node_id="cond_sentinel",
        nodes={
            "cond_sentinel": ConditionNode(
                id="cond_sentinel",
                cases=[
                    {"condition": "vars.finish == true", "target_id": "COMPLETE"},
                ],
                default_target_id="FAIL",
            )
        },
    )
    ctx = ScopedFlowContext()
    ctx.set_var("finish", True)

    async def mock_executor(node, context):
        return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)

    engine = PulseFlowEngine()
    result = await engine.run(graph, ctx, mock_executor)
    assert result["status"] == "success"

    ctx.set_var("finish", False)
    result_fail = await engine.run(graph, ctx, mock_executor)
    assert result_fail["status"] == "failed"


@pytest.mark.asyncio
async def test_subflow_node_execution():
    # 验证 SubflowNode 嵌套图执行及父子变量传递
    sub_graph = ExecutionGraph(
        entry_node_id="sub_step",
        nodes={
            "sub_step": ActionNode(
                id="sub_step",
                next_node_id=TERMINAL_COMPLETE_ID,
            )
        },
    )
    graph = ExecutionGraph(
        entry_node_id="call_subflow",
        nodes={
            "call_subflow": SubflowNode(
                id="call_subflow",
                subflow_graph=sub_graph,
                input_vars={"parent_token": "token"},
                output_vars={"inner_res": "out_res"},
                next_node_id=TERMINAL_COMPLETE_ID,
            )
        },
    )
    ctx = ScopedFlowContext()
    ctx.set_var("token", "secret123")
    executed = []

    async def mock_executor(node, context):
        executed.append(node.id)
        if node.id == "sub_step":
            assert context.get_var("parent_token") == "secret123"
            context.set_var("inner_res", "val_xyz")
            return StepOutcome(
                node_id="sub_step",
                status=NodeStatus.SUCCESS,
                output_text="sub finished",
            )
        return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)

    engine = PulseFlowEngine()
    result = await engine.run(graph, ctx, mock_executor)
    assert result["status"] == "success"
    assert "sub_step" in executed
    assert ctx.get_var("out_res") == "val_xyz"


@pytest.mark.asyncio
async def test_extractor_embedded_json_fallback():
    # 验证当文本夹杂其他内容时，通过正则提取嵌入的 JSON 块
    json_node = ExtractorNode(
        id="ext_embed_json",
        metadata={"extract_json": True},
        export_vars={"data.code": "auth_code"},
        next_node_id=TERMINAL_COMPLETE_ID,
    )
    ctx = ScopedFlowContext()
    ctx.last_output = 'Bot response: ```json\n{"data": {"code": 998811}}\n```'
    engine = PulseFlowEngine()

    outcome = engine._run_extractor_node(json_node, ctx)
    assert outcome.status == NodeStatus.SUCCESS
    assert outcome.extracted_vars["auth_code"] == 998811


@pytest.mark.asyncio
async def test_engine_result_contains_trace():
    graph = ExecutionGraph(
        entry_node_id="step_a",
        nodes={
            "step_a": ActionNode(
                id="step_a",
                next_node_id=TERMINAL_COMPLETE_ID,
            )
        },
    )
    ctx = ScopedFlowContext()

    async def mock_executor(node, context):
        return StepOutcome(
            node_id=node.id,
            status=NodeStatus.SUCCESS,
            output_text="Done A",
            extracted_vars={"res": 1},
        )

    engine = PulseFlowEngine()
    result = await engine.run(graph, ctx, mock_executor)
    assert "trace" in result
    assert len(result["trace"]) == 1
    trace_item = result["trace"][0]
    assert trace_item["node_id"] == "step_a"
    assert trace_item["status"] == "success"
    assert trace_item["output_text"] == "Done A"
    assert trace_item["extracted_vars"] == {"res": 1}


@pytest.mark.asyncio
async def test_engine_cancellation_preserves_context():
    graph = ExecutionGraph(
        entry_node_id="cancel_step",
        nodes={
            "cancel_step": ActionNode(
                id="cancel_step",
                next_node_id=TERMINAL_COMPLETE_ID,
            )
        },
    )
    ctx = ScopedFlowContext()

    async def mock_executor(node, context):
        await asyncio.sleep(10)
        return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)

    engine = PulseFlowEngine()
    task = asyncio.create_task(engine.run(graph, ctx, mock_executor))
    await asyncio.sleep(0.01)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_subflow_deepcopy_isolation():
    # 验证子工作流内部修改字典/列表不会污染父工作流
    sub_graph = ExecutionGraph(
        entry_node_id="sub_mod",
        nodes={
            "sub_mod": ActionNode(
                id="sub_mod",
                next_node_id=TERMINAL_COMPLETE_ID,
            )
        },
    )
    graph = ExecutionGraph(
        entry_node_id="call_sub",
        nodes={
            "call_sub": SubflowNode(
                id="call_sub",
                subflow_graph=sub_graph,
                next_node_id=TERMINAL_COMPLETE_ID,
            )
        },
    )
    ctx = ScopedFlowContext()
    ctx.set_var("config", {"timeout": 30, "nested": [1, 2, 3]})

    async def mock_executor(node, context):
        if node.id == "sub_mod":
            sub_cfg = context.get_var("config")
            sub_cfg["timeout"] = 999
            sub_cfg["nested"].append(999)
            return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)
        return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)

    engine = PulseFlowEngine()
    result = await engine.run(graph, ctx, mock_executor)
    assert result["status"] == "success"
    # 父级配置保持未被意外修改
    assert ctx.get_var("config")["timeout"] == 30
    assert ctx.get_var("config")["nested"] == [1, 2, 3]


@pytest.mark.asyncio
async def test_flow_engine_lifecycle_hooks():
    # 验证 on_step_start 和 on_step_finish 钩子被正确调用
    graph = ExecutionGraph(
        entry_node_id="step_1",
        nodes={
            "step_1": ActionNode(
                id="step_1",
                next_node_id="step_2",
            ),
            "step_2": ActionNode(
                id="step_2",
                next_node_id=TERMINAL_COMPLETE_ID,
            ),
        },
    )
    ctx = ScopedFlowContext()
    events = []

    async def on_start(node, context):
        events.append(f"start:{node.id}")

    def on_finish(node, outcome, context):
        events.append(f"finish:{node.id}:{outcome.status.value}")

    async def mock_executor(node, context):
        return StepOutcome(
            node_id=node.id,
            status=NodeStatus.SUCCESS,
            output_text=f"Done {node.id}",
        )

    engine = PulseFlowEngine()
    result = await engine.run(
        graph,
        ctx,
        mock_executor,
        on_step_start=on_start,
        on_step_finish=on_finish,
    )
    assert result["status"] == "success"
    assert events == [
        "start:step_1",
        "finish:step_1:success",
        "start:step_2",
        "finish:step_2:success",
    ]


@pytest.mark.asyncio
async def test_flow_engine_global_error_handler_fallback():
    # 验证当节点失败且无专属 on_failure_node_id 时，自动回退到 graph.error_handler_node_id
    graph = ExecutionGraph(
        entry_node_id="step_error",
        error_handler_node_id="step_cleanup",
        nodes={
            "step_error": ActionNode(
                id="step_error",
                next_node_id=TERMINAL_COMPLETE_ID,
                # 未配置 on_failure_node_id
            ),
            "step_cleanup": ActionNode(
                id="step_cleanup",
                next_node_id=TERMINAL_COMPLETE_ID,
            ),
        },
    )
    ctx = ScopedFlowContext()
    executed = []

    async def mock_executor(node, context):
        executed.append(node.id)
        if node.id == "step_error":
            return StepOutcome(node_id=node.id, status=NodeStatus.FAILED)
        return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)

    engine = PulseFlowEngine()
    result = await engine.run(graph, ctx, mock_executor)
    assert result["status"] == "success"
    assert executed == ["step_error", "step_cleanup"]
    assert result["path"] == ["step_error", "step_cleanup"]

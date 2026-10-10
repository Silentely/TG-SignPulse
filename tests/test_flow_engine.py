# tests/test_flow_engine.py
import pytest
from tg_signer.core.flow_models import (
    TERMINAL_COMPLETE_ID,
    TERMINAL_FAIL_ID,
    ActionNode,
    ConditionNode,
    ExtractorNode,
    ExecutionGraph,
    FlowSignal,
    NodeStatus,
    RetryPolicy,
    StepOutcome,
    TerminalPolicy,
)
from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_engine import PulseFlowEngine, FlowLoopLimitExceededError

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

@pytest.mark.asyncio
async def test_terminal_policy_not_triggered_on_action_failure():
    # 修复 Grok 指出的安全漏洞：动作失败时即使 matched_terminal=True，绝不提前成功退出
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
                    {"condition": "'ABC' in vars.auth_token", "target_id": "step_target"},
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

import asyncio
from unittest.mock import MagicMock

import pytest

from backend.services.sign_task_failure import (
    FAILURE_CATEGORY_TASK_LOOP_EXCEEDED,
    FailureCategory,
    classify_failure,
)
from backend.services.sign_task_runner import _runner_handle_error
from tg_signer.config import SignChatV3, SupportAction, WorkflowStepConfig
from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_engine import FlowLoopLimitExceededError, PulseFlowEngine
from tg_signer.core.flow_models import (
    FlowLoopLimitExceededError as FlowLoopLimitExceededErrorModel,
)
from tg_signer.core.flow_models import (
    NodeStatus,
    StepOutcome,
    TerminalPolicy,
)
from tg_signer.core.flow_normalizer import GraphNormalizer, GraphValidationError
from tg_signer.core.workflow_engine import (
    WorkflowContext,
    WorkflowDefinition,
    WorkflowEngine,
    WorkflowLoopExceededError,
    WorkflowStep,
    WorkflowTopologyError,
)

# ─── Part 1: Failure Classification Tests ───


def test_flow_loop_limit_error_classification_exception_instances():
    """验证 FlowLoopLimitExceededError 与 WorkflowLoopExceededError 异常实例均分类为 TASK_LOOP_EXCEEDED"""
    # 验证从 flow_engine 与 flow_models 导入的同一异常
    assert FlowLoopLimitExceededError is FlowLoopLimitExceededErrorModel

    err_flow = FlowLoopLimitExceededError("Node s1 loop limit exceeded (3/2)")
    assert classify_failure(error=err_flow, success=False) == FailureCategory.TASK_LOOP_EXCEEDED
    assert classify_failure(error=err_flow) == FailureCategory.TASK_LOOP_EXCEEDED
    assert classify_failure(error=err_flow).value == FAILURE_CATEGORY_TASK_LOOP_EXCEEDED

    err_wf = WorkflowLoopExceededError("步骤 s1 执行次数 (3) 超过允许上限 2")
    assert classify_failure(error=err_wf, success=False) == FailureCategory.TASK_LOOP_EXCEEDED
    assert classify_failure(error=err_wf) == FailureCategory.TASK_LOOP_EXCEEDED

    # 显式成功时应为 NONE
    assert classify_failure(error=err_flow, success=True) == FailureCategory.NONE


def test_flow_loop_limit_error_classification_strings():
    """验证各类流程循环/步数超限字符串均准确归类为 task_loop_exceeded"""
    cases = [
        "flow step limit exceeded: 60",
        "Flow step limit exceeded: 30",
        "flowlooplimitexceedederror: loop tripped",
        "Node s1 loop limit exceeded (3/2, path: s1 -> s2 -> s1)",
        "node loop limit exceeded",
        "loop limit exceeded in workflow",
        "Node s1 loop not allowed (visited 2 times)",
        "node loop not allowed",
        "workflowloopexceedederror: 步骤 s1 执行次数 (3) 超过允许上限 2",
        "执行已达最大步数硬上限 25",
        "步骤 s1 执行次数 (3) 超过允许上限 2",
        "检测到未允许的环路: s1 -> s2 -> s1",
        "任务步骤循环熔断",
    ]
    for msg in cases:
        cat = classify_failure(error=msg, success=False)
        assert cat == FailureCategory.TASK_LOOP_EXCEEDED, f"Failed on message: {msg}"
        assert cat.value == FAILURE_CATEGORY_TASK_LOOP_EXCEEDED

    # 通过 output 字段传入
    cat_out = classify_failure(output="Flow step limit exceeded: 60", success=False)
    assert cat_out == FailureCategory.TASK_LOOP_EXCEEDED


@pytest.mark.asyncio
async def test_sign_task_runner_catches_flow_loop_limit_exceeded():
    """验证 sign_task_runner._runner_handle_error 捕获 FlowLoopLimitExceededError 并置为 TASK_LOOP_EXCEEDED"""
    svc = MagicMock()
    svc._is_invalid_session_error.return_value = False
    state = {
        "svc": svc,
        "account_name": "test_account",
        "task_name": "test_task",
        "task_key": "test_account:test_task",
    }
    err = FlowLoopLimitExceededError("Node s1 loop limit exceeded (3/2)")
    await _runner_handle_error(state, err)
    assert state.get("failure_category") == FailureCategory.TASK_LOOP_EXCEEDED.value
    assert state.get("failure_category") == FAILURE_CATEGORY_TASK_LOOP_EXCEEDED


# ─── Part 2: Parity between V3 Step Workflow & PulseFlow ───


@pytest.mark.asyncio
async def test_parity_normal_linear_execution_order():
    """验证 V3 与 PulseFlow 在常规线性执行轨迹上的一致性"""
    chat = SignChatV3(
        chat_id=123,
        name="test_linear",
        initial_step_id="s1",
        steps=[
            WorkflowStepConfig(
                step_id="s1",
                action_type=SupportAction.SEND_TEXT,
                config={"text": "step 1"},
                next_step_id="s2",
            ),
            WorkflowStepConfig(
                step_id="s2",
                action_type=SupportAction.SEND_TEXT,
                config={"text": "step 2"},
                next_step_id="s3",
            ),
            WorkflowStepConfig(
                step_id="s3",
                action_type=SupportAction.SEND_TEXT,
                config={"text": "step 3"},
                next_step_id="COMPLETE",
            ),
        ],
    )

    # 1. V3 WorkflowEngine 执行
    wf_def = WorkflowDefinition(
        steps=[
            WorkflowStep(step_id="s1", action_type=SupportAction.SEND_TEXT, next_step_id="s2"),
            WorkflowStep(step_id="s2", action_type=SupportAction.SEND_TEXT, next_step_id="s3"),
            WorkflowStep(step_id="s3", action_type=SupportAction.SEND_TEXT, next_step_id="COMPLETE"),
        ],
        initial_step_id="s1",
    )
    v3_ctx = WorkflowContext(run_id="run_1", account_name="acc", task_name="task")
    v3_res = await WorkflowEngine().run(wf_def, v3_ctx, lambda s, c: asyncio.sleep(0, result=True))

    # 2. PulseFlowEngine 编译与执行
    graph = GraphNormalizer.compile(chat)
    flow_ctx = ScopedFlowContext()
    async def flow_executor(node, ctx):
        return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)

    flow_res = await PulseFlowEngine().run(graph, flow_ctx, flow_executor)

    # 3. 对比等价性
    assert v3_res["status"] == flow_res["status"] == "success"
    assert v3_res["path"] == flow_res["path"] == ["s1", "s2", "s3"]
    assert v3_res["steps"] == flow_res["steps"] == 3


@pytest.mark.asyncio
async def test_parity_failure_jump_recovery():
    """验证 V3 与 PulseFlow 在失败跳转分支 (on_failure_step_id) 上的轨迹一致性"""
    chat = SignChatV3(
        chat_id=123,
        name="test_failure_jump",
        initial_step_id="s1",
        steps=[
            WorkflowStepConfig(
                step_id="s1",
                action_type=SupportAction.SEND_TEXT,
                config={"text": "try main"},
                next_step_id="s2",
                on_failure_step_id="s_recovery",
            ),
            WorkflowStepConfig(
                step_id="s2",
                action_type=SupportAction.SEND_TEXT,
                config={"text": "normal next"},
                next_step_id="COMPLETE",
            ),
            WorkflowStepConfig(
                step_id="s_recovery",
                action_type=SupportAction.SEND_TEXT,
                config={"text": "recovery fallback"},
                next_step_id="COMPLETE",
            ),
        ],
    )

    # 1. V3 执行：s1 失败，跳到 s_recovery 成功
    wf_def = WorkflowDefinition(
        steps=[
            WorkflowStep(
                step_id="s1",
                action_type=SupportAction.SEND_TEXT,
                next_step_id="s2",
                on_failure_step_id="s_recovery",
            ),
            WorkflowStep(step_id="s2", action_type=SupportAction.SEND_TEXT, next_step_id="COMPLETE"),
            WorkflowStep(step_id="s_recovery", action_type=SupportAction.SEND_TEXT, next_step_id="COMPLETE"),
        ],
        initial_step_id="s1",
    )
    v3_ctx = WorkflowContext(run_id="run_2", account_name="acc", task_name="task")
    async def v3_exec(step, ctx):
        return step.step_id != "s1"
    v3_res = await WorkflowEngine().run(wf_def, v3_ctx, v3_exec)

    # 2. PulseFlow 执行：s1 失败，跳到 s_recovery 成功
    graph = GraphNormalizer.compile(chat)
    flow_ctx = ScopedFlowContext()
    async def flow_exec(node, ctx):
        if node.id == "s1":
            return StepOutcome(node_id=node.id, status=NodeStatus.FAILED, output_text="s1 failed")
        return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)
    flow_res = await PulseFlowEngine().run(graph, flow_ctx, flow_exec)

    # 3. 对比等价性
    assert v3_res["status"] == flow_res["status"] == "success"
    assert v3_res["path"] == flow_res["path"] == ["s1", "s_recovery"]
    assert v3_res["steps"] == flow_res["steps"] == 2


@pytest.mark.asyncio
async def test_parity_failure_jump_terminal_fail():
    """验证 V3 与 PulseFlow 在直接跳入终态失败 (FAIL) 时的轨迹一致性"""
    chat = SignChatV3(
        chat_id=123,
        name="test_fail_terminal",
        initial_step_id="s1",
        steps=[
            WorkflowStepConfig(
                step_id="s1",
                action_type=SupportAction.SEND_TEXT,
                config={"text": "step 1"},
                next_step_id="s2",
                on_failure_step_id="FAIL",
            ),
            WorkflowStepConfig(
                step_id="s2",
                action_type=SupportAction.SEND_TEXT,
                config={"text": "step 2"},
                next_step_id="COMPLETE",
            ),
        ],
    )

    # 1. V3 执行
    wf_def = WorkflowDefinition(
        steps=[
            WorkflowStep(step_id="s1", action_type=SupportAction.SEND_TEXT, next_step_id="s2", on_failure_step_id="FAIL"),
            WorkflowStep(step_id="s2", action_type=SupportAction.SEND_TEXT, next_step_id="COMPLETE"),
        ],
        initial_step_id="s1",
    )
    v3_ctx = WorkflowContext(run_id="run_3", account_name="acc", task_name="task")
    v3_res = await WorkflowEngine().run(wf_def, v3_ctx, lambda s, c: asyncio.sleep(0, result=False))

    # 2. PulseFlow 执行
    graph = GraphNormalizer.compile(chat)
    flow_ctx = ScopedFlowContext()
    async def flow_exec(node, ctx):
        return StepOutcome(node_id=node.id, status=NodeStatus.FAILED, output_text="step failed")
    flow_res = await PulseFlowEngine().run(graph, flow_ctx, flow_exec)

    # 3. 对比等价性
    assert v3_res["status"] == flow_res["status"] == "failed"
    assert v3_res["path"] == flow_res["path"] == ["s1"]
    assert v3_res["steps"] == flow_res["steps"] == 1


@pytest.mark.asyncio
async def test_parity_terminal_stop_condition():
    """验证配置 stop_flow_on_terminal 时，在匹配到终态时提前成功终止的轨迹一致性"""
    chat = SignChatV3(
        chat_id=123,
        name="test_terminal_stop",
        initial_step_id="s1",
        steps=[
            WorkflowStepConfig(
                step_id="s1",
                action_type=SupportAction.SEND_TEXT,
                config={"text": "check status", "stop_flow_on_terminal": True},
                next_step_id="s2",
            ),
            WorkflowStepConfig(
                step_id="s2",
                action_type=SupportAction.SEND_TEXT,
                config={"text": "should be skipped"},
                next_step_id="COMPLETE",
            ),
        ],
    )

    # 1. V3 执行：终态命中时设 current_step_id = 'COMPLETE' 提前结束
    wf_def = WorkflowDefinition(
        steps=[
            WorkflowStep(step_id="s1", action_type=SupportAction.SEND_TEXT, next_step_id="s2"),
            WorkflowStep(step_id="s2", action_type=SupportAction.SEND_TEXT, next_step_id="COMPLETE"),
        ],
        initial_step_id="s1",
    )
    v3_ctx = WorkflowContext(run_id="run_4", account_name="acc", task_name="task")
    async def v3_exec(step, ctx):
        if step.step_id == "s1":
            ctx.current_step_id = "COMPLETE"
            return True
        return True
    v3_res = await WorkflowEngine().run(wf_def, v3_ctx, v3_exec)

    # 2. PulseFlow 编译与执行：验证 compiled node 具有 TerminalPolicy.STOP_FLOW
    graph = GraphNormalizer.compile(chat)
    assert graph.nodes["s1"].terminal_policy == TerminalPolicy.STOP_FLOW

    flow_ctx = ScopedFlowContext()
    async def flow_exec(node, ctx):
        if node.id == "s1":
            return StepOutcome(
                node_id=node.id,
                status=NodeStatus.TERMINAL_EARLY,
                matched_terminal=True,
                output_text="已签到（终态）",
            )
        return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)

    flow_res = await PulseFlowEngine().run(graph, flow_ctx, flow_exec)

    # 3. 对比等价性：两者都在 s1 提前终止，后续 s2 不被执行
    assert v3_res["status"] == flow_res["status"] == "success"
    assert v3_res["path"] == flow_res["path"] == ["s1"]
    assert v3_res["steps"] == flow_res["steps"] == 1


@pytest.mark.asyncio
async def test_parity_loop_limit_detection():
    """验证循环步骤达到 max_retries 上限时的熔断与失败分类等价性"""
    chat = SignChatV3(
        chat_id=123,
        name="test_loop",
        initial_step_id="s1",
        steps=[
            WorkflowStepConfig(
                step_id="s1",
                action_type=SupportAction.SEND_TEXT,
                config={"text": "s1 loop"},
                next_step_id="s2",
                allow_loop=True,
                max_retries=1,
            ),
            WorkflowStepConfig(
                step_id="s2",
                action_type=SupportAction.SEND_TEXT,
                config={"text": "s2 loop"},
                next_step_id="s1",
                allow_loop=True,
                max_retries=1,
            ),
        ],
    )

    # 1. V3 循环熔断
    wf_def = WorkflowDefinition(
        steps=[
            WorkflowStep(step_id="s1", action_type=SupportAction.SEND_TEXT, next_step_id="s2", allow_loop=True, max_retries=1),
            WorkflowStep(step_id="s2", action_type=SupportAction.SEND_TEXT, next_step_id="s1", allow_loop=True, max_retries=1),
        ],
        initial_step_id="s1",
    )
    v3_ctx = WorkflowContext(run_id="run_5", account_name="acc", task_name="task")
    v3_exc = None
    try:
        await WorkflowEngine().run(wf_def, v3_ctx, lambda s, c: asyncio.sleep(0, result=True))
    except WorkflowLoopExceededError as e:
        v3_exc = e

    # 2. PulseFlow 编译与循环熔断
    graph = GraphNormalizer.compile(chat)
    flow_ctx = ScopedFlowContext()
    flow_exc = None
    try:
        await PulseFlowEngine().run(
            graph,
            flow_ctx,
            lambda n, c: asyncio.sleep(0, result=StepOutcome(node_id=n.id, status=NodeStatus.SUCCESS)),
        )
    except FlowLoopLimitExceededError as e:
        flow_exc = e

    assert v3_exc is not None, "V3 should raise WorkflowLoopExceededError"
    assert flow_exc is not None, "PulseFlow should raise FlowLoopLimitExceededError"

    # 3. 验证异常信息与失败分类完全一致
    assert classify_failure(error=v3_exc, success=False) == FailureCategory.TASK_LOOP_EXCEEDED
    assert classify_failure(error=flow_exc, success=False) == FailureCategory.TASK_LOOP_EXCEEDED
    assert classify_failure(error=str(v3_exc), success=False) == FailureCategory.TASK_LOOP_EXCEEDED
    assert classify_failure(error=str(flow_exc), success=False) == FailureCategory.TASK_LOOP_EXCEEDED


def test_parity_topology_cycle_rejection():
    """验证未允许的死循环在拓扑校验阶段两套引擎均准确拦截"""
    wf_def = WorkflowDefinition(
        steps=[
            WorkflowStep(step_id="s1", action_type=SupportAction.SEND_TEXT, next_step_id="s2", allow_loop=False),
            WorkflowStep(step_id="s2", action_type=SupportAction.SEND_TEXT, next_step_id="s1", allow_loop=False),
        ],
        initial_step_id="s1",
    )
    with pytest.raises(WorkflowTopologyError):
        WorkflowEngine.validate_topology(wf_def)

    # 编译到 PulseFlow 亦抛出 GraphValidationError
    from tg_signer.core.flow_models import ActionNode, ExecutionGraph
    unallowed_graph = ExecutionGraph(
        entry_node_id="s1",
        nodes={
            "s1": ActionNode(id="s1", next_node_id="s2"),
            "s2": ActionNode(id="s2", next_node_id="s1"),
        },
    )
    with pytest.raises(GraphValidationError):
        GraphNormalizer.validate_graph(unallowed_graph)


@pytest.mark.asyncio
async def test_parity_step_limit_exceeded():
    """验证总步数上限触发时两套引擎的熔断与分类等价性"""
    # 1. V3 超出 max_total_steps
    wf_def = WorkflowDefinition(
        steps=[
            WorkflowStep(step_id="s1", action_type=SupportAction.SEND_TEXT, next_step_id="s1", allow_loop=True, max_retries=100),
        ],
        initial_step_id="s1",
    )
    v3_ctx = WorkflowContext(run_id="run_6", account_name="acc", task_name="task", max_total_steps=5)
    with pytest.raises(WorkflowLoopExceededError) as exc_v3:
        await WorkflowEngine().run(wf_def, v3_ctx, lambda s, c: asyncio.sleep(0, result=True))
    assert classify_failure(error=exc_v3.value, success=False) == FailureCategory.TASK_LOOP_EXCEEDED

    # 2. PulseFlow 超出 max_total_steps
    from tg_signer.core.flow_models import ActionNode, ExecutionGraph, LoopPolicy
    flow_graph = ExecutionGraph(
        entry_node_id="s1",
        nodes={
            "s1": ActionNode(
                id="s1",
                next_node_id="s1",
                loop_policy=LoopPolicy(allow_loop=True, max_visits=100),
            )
        },
        max_total_steps=5,
    )
    flow_ctx = ScopedFlowContext()
    flow_res = await PulseFlowEngine().run(
        flow_graph,
        flow_ctx,
        lambda n, c: asyncio.sleep(0, result=StepOutcome(node_id=n.id, status=NodeStatus.SUCCESS)),
    )
    assert flow_res["status"] == "failed"
    assert "Flow step limit exceeded" in flow_res.get("error", "")
    assert classify_failure(error=flow_res["error"], success=False) == FailureCategory.TASK_LOOP_EXCEEDED

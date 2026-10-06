from typing import Dict

import pytest

from tg_signer.core.workflow_engine import (
    WorkflowContext,
    WorkflowDefinition,
    WorkflowEngine,
    WorkflowLoopExceededError,
    WorkflowStep,
    WorkflowTopologyError,
)


def test_validate_topology_detects_infinite_cycle():
    # step1 -> step2 -> step1 cycle without allow_loop
    steps = [
        WorkflowStep(step_id="step1", action_type="send", next_step_id="step2"),
        WorkflowStep(step_id="step2", action_type="wait", next_step_id="step1"),
    ]
    wf = WorkflowDefinition(steps=steps, initial_step_id="step1")

    with pytest.raises(WorkflowTopologyError) as exc_info:
        WorkflowEngine.validate_topology(wf)
    assert "检测到" in str(exc_info.value) and "环路" in str(exc_info.value)


def test_validate_topology_valid_dag_with_branches():
    steps = [
        WorkflowStep(
            step_id="step1",
            action_type="send",
            next_step_id="step2",
            on_failure_step_id="step_fail",
        ),
        WorkflowStep(
            step_id="step2",
            action_type="verify",
            next_step_id="COMPLETE",
            on_failure_step_id="FAIL",
        ),
        WorkflowStep(
            step_id="step_fail",
            action_type="notify",
            next_step_id="FAIL",
        ),
    ]
    wf = WorkflowDefinition(steps=steps, initial_step_id="step1")
    WorkflowEngine.validate_topology(wf)  # Should not raise


def test_validate_topology_dangling_edges():
    steps = [
        WorkflowStep(
            step_id="step1",
            action_type="send",
            next_step_id="ghost_step",
        ),
    ]
    wf = WorkflowDefinition(steps=steps, initial_step_id="step1")
    with pytest.raises(WorkflowTopologyError) as exc_info:
        WorkflowEngine.validate_topology(wf)
    assert "不存在" in str(exc_info.value)

    steps2 = [
        WorkflowStep(
            step_id="step1",
            action_type="send",
            next_step_id="COMPLETE",
            on_failure_step_id="ghost_fail",
        ),
    ]
    wf2 = WorkflowDefinition(steps=steps2, initial_step_id="step1")
    with pytest.raises(WorkflowTopologyError) as exc_info:
        WorkflowEngine.validate_topology(wf2)
    assert "不存在" in str(exc_info.value)


def test_validate_topology_declared_cycle_allowed():
    # Declared cycle: both steps declare allow_loop=True and max_retries >= 0
    steps = [
        WorkflowStep(
            step_id="step1",
            action_type="send",
            next_step_id="step2",
            allow_loop=True,
            max_retries=2,
        ),
        WorkflowStep(
            step_id="step2",
            action_type="wait",
            next_step_id="step1",
            allow_loop=True,
            max_retries=2,
        ),
    ]
    wf = WorkflowDefinition(steps=steps, initial_step_id="step1")
    WorkflowEngine.validate_topology(wf)  # Should pass


def test_validate_topology_partially_declared_cycle_rejected():
    # Partial declaration: step1 has allow_loop=True, but step2 does not
    steps = [
        WorkflowStep(
            step_id="step1",
            action_type="send",
            next_step_id="step2",
            allow_loop=True,
            max_retries=2,
        ),
        WorkflowStep(
            step_id="step2",
            action_type="wait",
            next_step_id="step1",
            allow_loop=False,
        ),
    ]
    wf = WorkflowDefinition(steps=steps, initial_step_id="step1")
    with pytest.raises(WorkflowTopologyError):
        WorkflowEngine.validate_topology(wf)


@pytest.mark.asyncio
async def test_runtime_step_count_limit_for_loop():
    engine = WorkflowEngine()
    # allow_loop=True, max_retries=2 allows 3 executions total
    steps = [
        WorkflowStep(
            step_id="step1",
            action_type="noop",
            next_step_id="step1",
            allow_loop=True,
            max_retries=2,
        ),
    ]
    wf = WorkflowDefinition(steps=steps, initial_step_id="step1")
    ctx = WorkflowContext(run_id="run_123", account_name="user", task_name="task")

    with pytest.raises(WorkflowLoopExceededError) as exc_info:
        await engine.run(wf, ctx)
    assert "超过允许上限 3" in str(exc_info.value)
    assert ctx.total_steps_executed == 3


@pytest.mark.asyncio
async def test_runtime_non_loop_visited_twice_raises():
    # step1 is not allow_loop, but loops back to step1 via step2
    steps = [
        WorkflowStep(
            step_id="step1",
            action_type="noop",
            next_step_id="step2",
            allow_loop=False,
        ),
        WorkflowStep(
            step_id="step2",
            action_type="noop",
            next_step_id="step1",
            allow_loop=True,
            max_retries=2,
        ),
    ]
    wf = WorkflowDefinition(steps=steps, initial_step_id="step1")
    ctx = WorkflowContext(run_id="run_123", account_name="user", task_name="task")

    with pytest.raises(WorkflowLoopExceededError) as exc_info:
        # Bypass validate_topology to test runtime safeguard
        step_map = {s.step_id: s for s in wf.steps}
        ctx.current_step_id = wf.initial_step_id
        step_counts: Dict[str, int] = {}
        while ctx.current_step_id and ctx.current_step_id not in {"COMPLETE", "FAIL"}:
            step = step_map[ctx.current_step_id]
            current_count = step_counts.get(ctx.current_step_id, 0)
            limit = (step.max_retries + 1) if (step.allow_loop and step.max_retries is not None) else 1
            if current_count >= limit:
                raise WorkflowLoopExceededError(
                    f"步骤 {step.step_id} 执行次数 ({current_count + 1}) 超过允许上限 {limit}"
                )
            step_counts[step.step_id] = current_count + 1
            ctx.execution_path.append(step.step_id)
            ctx.total_steps_executed += 1
            ctx.current_step_id = step.next_step_id or "COMPLETE"

    assert "超过允许上限 1" in str(exc_info.value)
    assert ctx.execution_path == ["step1", "step2"]


@pytest.mark.asyncio
async def test_runtime_step_executor_branching():
    engine = WorkflowEngine()
    steps = [
        WorkflowStep(
            step_id="step1",
            action_type="check",
            next_step_id="step_success",
            on_failure_step_id="step_failure",
        ),
        WorkflowStep(
            step_id="step_success",
            action_type="noop",
            next_step_id="COMPLETE",
        ),
        WorkflowStep(
            step_id="step_failure",
            action_type="noop",
            next_step_id="FAIL",
        ),
    ]
    wf = WorkflowDefinition(steps=steps, initial_step_id="step1")

    # Case 1: step1 fails -> goes to step_failure -> FAIL
    ctx1 = WorkflowContext(run_id="run_1", account_name="user", task_name="task")
    async def failing_executor(step: WorkflowStep, ctx: WorkflowContext) -> bool:
        if step.step_id == "step1":
            return False
        return True

    res1 = await engine.run(wf, ctx1, step_executor=failing_executor)
    assert res1["status"] == "failed"
    assert ctx1.execution_path == ["step1", "step_failure"]

    # Case 2: step1 succeeds -> goes to step_success -> COMPLETE
    ctx2 = WorkflowContext(run_id="run_2", account_name="user", task_name="task")
    async def passing_executor(step: WorkflowStep, ctx: WorkflowContext) -> bool:
        return True

    res2 = await engine.run(wf, ctx2, step_executor=passing_executor)
    assert res2["status"] == "success"
    assert ctx2.execution_path == ["step1", "step_success"]


@pytest.mark.asyncio
async def test_runtime_enforces_max_25_steps_limit():
    engine = WorkflowEngine()
    # 25 total steps limit
    steps = [
        WorkflowStep(
            step_id="step1",
            action_type="noop",
            next_step_id="step1",
            allow_loop=True,
            max_retries=50,  # Allows up to 51, but hard limit 25 must trigger first
        ),
    ]
    wf = WorkflowDefinition(steps=steps, initial_step_id="step1")
    ctx = WorkflowContext(run_id="run_123", account_name="user", task_name="task")

    with pytest.raises(WorkflowLoopExceededError):
        await engine.run(wf, ctx)
    assert ctx.total_steps_executed == 25

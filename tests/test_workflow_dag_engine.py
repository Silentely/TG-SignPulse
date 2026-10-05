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
    # 构造 step1 -> step2 -> step1 环路
    steps = [
        WorkflowStep(step_id="step1", action_type="send", next_step_id="step2"),
        WorkflowStep(step_id="step2", action_type="wait", next_step_id="step1"),
    ]
    wf = WorkflowDefinition(steps=steps, initial_step_id="step1")

    with pytest.raises(WorkflowTopologyError) as exc_info:
        WorkflowEngine.validate_topology(wf)
    assert "检测到环路" in str(exc_info.value)


@pytest.mark.asyncio
async def test_runtime_enforces_max_25_steps_limit():
    engine = WorkflowEngine()
    # 构造一个单步自循环（声明允许回环但未收敛）
    steps = [
        WorkflowStep(
            step_id="step1",
            action_type="noop",
            next_step_id="step1",
            allow_loop=True,
        ),
    ]
    wf = WorkflowDefinition(steps=steps, initial_step_id="step1")
    ctx = WorkflowContext(run_id="run_123", account_name="user", task_name="task")

    with pytest.raises(WorkflowLoopExceededError):
        await engine.run(wf, ctx)
    assert ctx.total_steps_executed == 25

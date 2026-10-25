import pytest

from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_engine import PulseFlowEngine
from tg_signer.core.flow_models import (
    ActionNode,
    ExecutionGraph,
    NodeStatus,
    ParallelMode,
    ParallelNode,
    StepOutcome,
)


def branch(name):
    return ExecutionGraph(entry_node_id=name, nodes={name: ActionNode(id=name)})


@pytest.mark.asyncio
async def test_all_settled_preserves_partial_business_result():
    node = ParallelNode(
        id="p", branches=[branch("ok"), branch("bad")], mode=ParallelMode.ALL_SETTLED
    )

    async def execute(n, ctx):
        return StepOutcome(
            node_id=n.id,
            status=NodeStatus.FAILED if n.id == "bad" else NodeStatus.SUCCESS,
        )

    result = await PulseFlowEngine().run(
        ExecutionGraph(entry_node_id="p", nodes={"p": node}),
        ScopedFlowContext(),
        execute,
    )
    assert result["status"] == "success"
    assert result["business_status"] == "partial"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "policy,expected",
    [
        ("fail", None),
        ("first_writer", "A"),
        ("last_writer", "B"),
        ("collect", ["A", "B"]),
    ],
)
async def test_parallel_variable_conflicts_have_explicit_policy(policy, expected):
    node = ParallelNode(
        id="p", branches=[branch("A"), branch("B")], variable_conflict_policy=policy
    )

    async def execute(n, ctx):
        ctx.vars["value"] = n.id
        return StepOutcome(node_id=n.id, status=NodeStatus.SUCCESS)

    ctx = ScopedFlowContext()
    ctx.vars["untouched"] = "original"
    result = await PulseFlowEngine().run(
        ExecutionGraph(entry_node_id="p", nodes={"p": node}), ctx, execute
    )
    assert ctx.vars.get("value") == expected
    assert result["status"] == ("failed" if policy == "fail" else "success")
    assert ctx.vars["untouched"] == "original"
    assert ctx.step_outcomes["p"].details["variable_conflicts"] == ["value"]

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from tg_signer.core.flow_models import FlowLoopLimitExceededError
from tg_signer.core.flow_normalizer import GraphValidationError

logger = logging.getLogger("tg_signer.workflow_engine")


class WorkflowTopologyError(GraphValidationError):
    """[已废弃] 工作流拓扑结构不合法或存在非法环路，请改用 GraphValidationError"""


class WorkflowLoopExceededError(FlowLoopLimitExceededError):
    """[已废弃] 工作流执行超过最大步数熔断，请改用 FlowLoopLimitExceededError"""


@dataclass
class WorkflowStep:
    """[已废弃] 旧版工作流步骤定义，请改用 FlowStepConfig 或 FlowNode"""

    step_id: str
    action_type: Any  # SupportAction / str / int
    next_step_id: Optional[str] = None
    on_failure_step_id: Optional[str] = None
    allow_loop: bool = False
    max_retries: Optional[int] = None
    config: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        warnings.warn(
            "WorkflowStep is deprecated, use FlowStepConfig or FlowNode instead",
            DeprecationWarning,
            stacklevel=2,
        )


@dataclass
class WorkflowDefinition:
    """[已废弃] 旧版工作流图定义，请改用 ExecutionGraph"""

    steps: List[WorkflowStep]
    initial_step_id: str

    def __post_init__(self):
        warnings.warn(
            "WorkflowDefinition is deprecated, use ExecutionGraph instead",
            DeprecationWarning,
            stacklevel=2,
        )


@dataclass
class WorkflowContext:
    """[已废弃] 旧版工作流运行上下文，请改用 FlowExecutionContext"""

    run_id: str
    account_name: str
    task_name: str
    current_step_id: str = ""
    execution_path: List[str] = field(default_factory=list)
    total_steps_executed: int = 0
    max_total_steps: int = 25

    def __post_init__(self):
        warnings.warn(
            "WorkflowContext is deprecated, use FlowExecutionContext instead",
            DeprecationWarning,
            stacklevel=2,
        )


class WorkflowEngine:
    """[已废弃] 旧版工作流调度引擎别名兼容层。

    请全面迁移至 tg_signer.core.flow_engine.PulseFlowEngine。
    """

    def __init__(self, *args, **kwargs):
        warnings.warn(
            "WorkflowEngine is deprecated, use PulseFlowEngine instead",
            DeprecationWarning,
            stacklevel=2,
        )

    @classmethod
    def validate_topology(cls, wf: WorkflowDefinition) -> None:
        warnings.warn(
            "WorkflowEngine is deprecated, use PulseFlowEngine instead",
            DeprecationWarning,
            stacklevel=2,
        )
        step_map = {s.step_id: s for s in wf.steps}
        if wf.initial_step_id not in step_map:
            raise WorkflowTopologyError(f"初始步骤 {wf.initial_step_id} 不存在")

        for s in wf.steps:
            if s.next_step_id and s.next_step_id not in {"COMPLETE", "FAIL"}:
                if s.next_step_id not in step_map:
                    raise WorkflowTopologyError(
                        f"步骤 {s.step_id} 指向的后续步骤 {s.next_step_id} 不存在"
                    )
            if s.on_failure_step_id and s.on_failure_step_id not in {
                "COMPLETE",
                "FAIL",
            }:
                if s.on_failure_step_id not in step_map:
                    raise WorkflowTopologyError(
                        f"步骤 {s.step_id} 指向的失败后步骤 {s.on_failure_step_id} 不存在"
                    )

        # 环路检测：DFS
        # rec_stack 记录访问路径，用于在发现环路时检查参与环路的所有步骤是否都声明了 allow_loop=True 且 max_retries >= 0
        visited = set()
        rec_stack: List[str] = []

        def _dfs(step_id: str):
            if step_id in {"COMPLETE", "FAIL"}:
                return

            if step_id in rec_stack:
                # 发现环路
                cycle_start_idx = rec_stack.index(step_id)
                cycle_steps = rec_stack[cycle_start_idx:]
                # 检查环路上的每一个步骤
                for sid in cycle_steps:
                    st = step_map.get(sid)
                    if (
                        not st
                        or not st.allow_loop
                        or st.max_retries is None
                        or st.max_retries < 0
                    ):
                        raise WorkflowTopologyError(
                            f"检测到未允许的环路: {' -> '.join(cycle_steps)} -> {step_id}"
                        )
                # 若环路上所有步骤均已显式声明 allow_loop，则允许该循环，不再深入递归
                return

            if step_id in visited:
                return

            visited.add(step_id)
            rec_stack.append(step_id)

            step = step_map.get(step_id)
            if step:
                # 访问成功分支
                if step.next_step_id:
                    _dfs(step.next_step_id)
                # 访问失败分支
                if step.on_failure_step_id:
                    _dfs(step.on_failure_step_id)

            rec_stack.pop()

        _dfs(wf.initial_step_id)

        # 确保所有步骤即使不可达也没隐匿非法未声明死循环
        for s in wf.steps:
            if s.step_id not in visited:
                _dfs(s.step_id)

    async def run(
        self,
        wf: WorkflowDefinition,
        ctx: WorkflowContext,
        step_executor: Optional[
            Callable[[WorkflowStep, WorkflowContext], Awaitable[bool]]
        ] = None,
    ) -> Dict[str, Any]:
        """向 PulseFlowEngine 委托执行的兼容适配层。"""
        self.validate_topology(wf)
        from tg_signer.core.flow_context import ScopedFlowContext
        from tg_signer.core.flow_engine import PulseFlowEngine
        from tg_signer.core.flow_models import (
            TERMINAL_COMPLETE_ID,
            TERMINAL_FAIL_ID,
            ActionNode,
            ExecutionGraph,
            FlowLoopLimitExceededError,
            LoopPolicy,
            NodeStatus,
            NodeType,
            StepOutcome,
        )

        step_map = {s.step_id: s for s in wf.steps}
        nodes: Dict[str, Any] = {}
        for s in wf.steps:
            next_nid = (
                TERMINAL_COMPLETE_ID
                if s.next_step_id in (None, "COMPLETE")
                else (TERMINAL_FAIL_ID if s.next_step_id == "FAIL" else s.next_step_id)
            )
            on_fail_nid = (
                TERMINAL_FAIL_ID
                if s.on_failure_step_id in (None, "FAIL")
                else (
                    TERMINAL_COMPLETE_ID
                    if s.on_failure_step_id == "COMPLETE"
                    else s.on_failure_step_id
                )
            )
            limit = (
                (s.max_retries + 1)
                if (s.allow_loop and s.max_retries is not None)
                else 1
            )
            nodes[s.step_id] = ActionNode(
                id=s.step_id,
                node_type=NodeType.ACTION,
                next_node_id=next_nid,
                on_failure_node_id=on_fail_nid,
                loop_policy=LoopPolicy(
                    allow_loop=bool(s.allow_loop),
                    max_visits=limit,
                ),
            )

        graph = ExecutionGraph(
            entry_node_id=wf.initial_step_id,
            nodes=nodes,
            max_total_steps=ctx.max_total_steps,
        )

        flow_ctx = ScopedFlowContext()
        engine = PulseFlowEngine()

        from tg_signer.core.flow_models import FlowSignal

        async def _bridge_node_executor(node, _fc: ScopedFlowContext) -> StepOutcome:
            step = step_map[node.id]
            ctx.current_step_id = step.step_id
            ctx.execution_path.append(step.step_id)
            ctx.total_steps_executed += 1

            step_success = True
            if step_executor is not None:
                step_success = await step_executor(step, ctx)

            if ctx.current_step_id == "COMPLETE":
                return StepOutcome(
                    node_id=node.id,
                    status=NodeStatus.SUCCESS,
                    signal=FlowSignal.HALT_SUCCESS,
                )
            elif ctx.current_step_id == "FAIL":
                return StepOutcome(
                    node_id=node.id,
                    status=NodeStatus.FAILED,
                    signal=FlowSignal.HALT_FAIL,
                )
            elif ctx.current_step_id != step.step_id:
                return StepOutcome(
                    node_id=node.id,
                    status=NodeStatus.SUCCESS if step_success else NodeStatus.FAILED,
                    signal=FlowSignal.BRANCH,
                    target_node_id=ctx.current_step_id,
                )

            if step_success:
                return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)
            return StepOutcome(node_id=node.id, status=NodeStatus.FAILED)

        try:
            res = await engine.run(graph, flow_ctx, _bridge_node_executor)
            err_text = str(res.get("error") or "")
            if "Flow step limit exceeded" in err_text or ctx.total_steps_executed >= ctx.max_total_steps:
                raise WorkflowLoopExceededError(
                    f"执行已达最大步数硬上限 {ctx.max_total_steps}"
                )
            status_result = "success" if res.get("status") == "success" else "failed"
            return {
                "status": status_result,
                "path": list(ctx.execution_path),
                "steps": ctx.total_steps_executed,
            }
        except FlowLoopLimitExceededError as err:
            err_msg = str(err)
            if "Max total step limit exceeded" in err_msg or ctx.total_steps_executed >= ctx.max_total_steps:
                raise WorkflowLoopExceededError(
                    f"执行已达最大步数硬上限 {ctx.max_total_steps}: {err_msg}"
                ) from err
            curr_step_id = ctx.current_step_id or wf.initial_step_id
            st = step_map.get(curr_step_id)
            limit = (
                (st.max_retries + 1)
                if (st and st.allow_loop and st.max_retries is not None)
                else 1
            )
            raise WorkflowLoopExceededError(
                f"步骤 {curr_step_id} 执行次数 ({ctx.execution_path.count(curr_step_id) + 1}) 超过允许上限 {limit}: {err_msg}"
            ) from err


__all__ = [
    "WorkflowTopologyError",
    "WorkflowLoopExceededError",
    "WorkflowStep",
    "WorkflowDefinition",
    "WorkflowContext",
    "WorkflowEngine",
]

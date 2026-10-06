from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger("tg_signer.workflow_engine")


class WorkflowTopologyError(ValueError):
    """工作流拓扑结构不合法或存在非法环路"""


class WorkflowLoopExceededError(RuntimeError):
    """工作流执行超过最大步数熔断"""


@dataclass
class WorkflowStep:
    step_id: str
    action_type: Any  # SupportAction / str / int
    next_step_id: Optional[str] = None
    on_failure_step_id: Optional[str] = None
    allow_loop: bool = False
    max_retries: Optional[int] = None
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowDefinition:
    steps: List[WorkflowStep]
    initial_step_id: str


@dataclass
class WorkflowContext:
    run_id: str
    account_name: str
    task_name: str
    current_step_id: str = ""
    execution_path: List[str] = field(default_factory=list)
    total_steps_executed: int = 0
    max_total_steps: int = 25


class WorkflowEngine:
    @classmethod
    def validate_topology(cls, wf: WorkflowDefinition) -> None:
        step_map = {s.step_id: s for s in wf.steps}
        if wf.initial_step_id not in step_map:
            raise WorkflowTopologyError(f"初始步骤 {wf.initial_step_id} 不存在")

        for s in wf.steps:
            if s.next_step_id and s.next_step_id not in {"COMPLETE", "FAIL"}:
                if s.next_step_id not in step_map:
                    raise WorkflowTopologyError(
                        f"步骤 {s.step_id} 指向的后续步骤 {s.next_step_id} 不存在"
                    )
            if s.on_failure_step_id and s.on_failure_step_id not in {"COMPLETE", "FAIL"}:
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
                    if not st or not st.allow_loop or st.max_retries is None or st.max_retries < 0:
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

        # 确保所有步骤即使不可达也没隐藏非法未声明死循环
        for s in wf.steps:
            if s.step_id not in visited:
                _dfs(s.step_id)

    async def run(
        self,
        wf: WorkflowDefinition,
        ctx: WorkflowContext,
        step_executor: Optional[Callable[[WorkflowStep, WorkflowContext], Awaitable[bool]]] = None,
    ) -> Dict[str, Any]:
        self.validate_topology(wf)
        step_map = {s.step_id: s for s in wf.steps}
        ctx.current_step_id = wf.initial_step_id
        step_counts: Dict[str, int] = {}

        while ctx.current_step_id and ctx.current_step_id not in {"COMPLETE", "FAIL"}:
            if ctx.total_steps_executed >= ctx.max_total_steps:
                raise WorkflowLoopExceededError(
                    f"执行已达最大步数硬上限 {ctx.max_total_steps}"
                )

            step = step_map[ctx.current_step_id]
            current_count = step_counts.get(step.step_id, 0)
            limit = (
                (step.max_retries + 1)
                if (step.allow_loop and step.max_retries is not None)
                else 1
            )
            if current_count >= limit:
                raise WorkflowLoopExceededError(
                    f"步骤 {step.step_id} 执行次数 ({current_count + 1}) 超过允许上限 {limit}"
                )

            step_counts[step.step_id] = current_count + 1
            ctx.execution_path.append(step.step_id)
            ctx.total_steps_executed += 1

            step_success = True
            if step_executor is not None:
                step_success = await step_executor(step, ctx)

            if ctx.current_step_id == "COMPLETE":
                break
            elif step_success:
                ctx.current_step_id = step.next_step_id or "COMPLETE"
            else:
                ctx.current_step_id = step.on_failure_step_id or "FAIL"

        status_result = "success" if ctx.current_step_id == "COMPLETE" else "failed"
        return {
            "status": status_result,
            "path": ctx.execution_path,
            "steps": ctx.total_steps_executed,
        }

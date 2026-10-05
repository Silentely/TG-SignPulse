from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("tg_signer.workflow_engine")


class WorkflowTopologyError(Exception):
    """工作流拓扑结构不合法或存在非法环路"""


class WorkflowLoopExceededError(Exception):
    """工作流执行超过最大步数熔断"""


@dataclass
class WorkflowStep:
    step_id: str
    action_type: str
    next_step_id: Optional[str] = None
    allow_loop: bool = False
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

        # DFS 环路检测
        visited = set()
        rec_stack = set()

        def _dfs(step_id: str):
            if step_id in rec_stack:
                raise WorkflowTopologyError(f"检测到环路: {step_id}")
            if step_id in visited or step_id in {"COMPLETE", "FAIL"}:
                return

            visited.add(step_id)
            rec_stack.add(step_id)
            step = step_map.get(step_id)
            if step and step.next_step_id and not step.allow_loop:
                _dfs(step.next_step_id)
            rec_stack.remove(step_id)

        _dfs(wf.initial_step_id)

    async def run(self, wf: WorkflowDefinition, ctx: WorkflowContext) -> Dict[str, Any]:
        self.validate_topology(wf)
        step_map = {s.step_id: s for s in wf.steps}
        ctx.current_step_id = wf.initial_step_id

        while ctx.current_step_id and ctx.current_step_id not in {"COMPLETE", "FAIL"}:
            if ctx.total_steps_executed >= ctx.max_total_steps:
                raise WorkflowLoopExceededError(
                    f"执行已达最大步数硬上限 {ctx.max_total_steps}"
                )

            step = step_map[ctx.current_step_id]
            ctx.execution_path.append(step.step_id)
            ctx.total_steps_executed += 1

            ctx.current_step_id = step.next_step_id or "COMPLETE"

        return {
            "status": "success",
            "path": ctx.execution_path,
            "steps": ctx.total_steps_executed,
        }

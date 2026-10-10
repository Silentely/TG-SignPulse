# tg_signer/core/flow_engine.py
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Awaitable, Callable, Dict, Optional

from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_models import (
    TERMINAL_COMPLETE_ID,
    TERMINAL_FAIL_ID,
    BaseFlowNode,
    ConditionNode,
    ExecutionGraph,
    ExtractorNode,
    FlowSignal,
    NodeStatus,
    StepOutcome,
    TerminalPolicy,
)

logger = logging.getLogger("tg_signer.flow_engine")


class FlowLoopLimitExceededError(RuntimeError):
    """工作流执行步骤超过上限熔断"""


class PulseFlowEngine:
    """下一代无副作用状态机调度引擎"""

    async def run(
        self,
        graph: ExecutionGraph,
        ctx: ScopedFlowContext,
        executor: Callable[[BaseFlowNode, ScopedFlowContext], Awaitable[StepOutcome]],
    ) -> Dict[str, Any]:
        current_id: Optional[str] = graph.entry_node_id
        executed_path = []
        visit_counts: Dict[str, int] = {}
        total_steps = 0

        while current_id not in {TERMINAL_COMPLETE_ID, TERMINAL_FAIL_ID, None}:
            if total_steps >= graph.max_total_steps:
                raise FlowLoopLimitExceededError(
                    f"工作流执行已触发安全硬熔断：超过单次最大步数 {graph.max_total_steps}"
                )

            node = graph.nodes.get(current_id)
            if not node:
                logger.error(f"工作流引用了不存在的步骤: {current_id}")
                return {"status": "failed", "path": executed_path, "error": f"NodeNotFound: {current_id}"}

            visits = visit_counts.get(node.id, 0)
            if visits >= node.loop_policy.max_visits:
                raise FlowLoopLimitExceededError(
                    f"节点 {node.id} 访问次数 ({visits + 1}) 超过允许上限: {node.loop_policy.max_visits}"
                )

            visit_counts[node.id] = visits + 1
            executed_path.append(node.id)
            total_steps += 1

            # 执行具体节点（原生处理 Extractor/Condition，外部委派 Action）
            attempt = 0
            outcome: Optional[StepOutcome] = None
            while attempt < node.retry_policy.max_attempts:
                attempt += 1
                try:
                    if isinstance(node, ExtractorNode):
                        outcome = self._run_extractor_node(node, ctx)
                    elif isinstance(node, ConditionNode):
                        outcome = self._run_condition_node(node, ctx)
                    else:
                        outcome = await asyncio.wait_for(executor(node, ctx), timeout=node.timeout_seconds)

                    if outcome.signal != FlowSignal.RETRY_NODE:
                        break
                except Exception as exc:
                    exc_name = type(exc).__name__
                    allowed = node.retry_policy.retry_on_exceptions
                    if allowed and exc_name not in allowed:
                        outcome = StepOutcome(node_id=node.id, status=NodeStatus.FAILED, error=exc, output_text=str(exc))
                        break

                    if attempt >= node.retry_policy.max_attempts:
                        outcome = StepOutcome(node_id=node.id, status=NodeStatus.FAILED, error=exc, output_text=str(exc))
                        break
                    backoff = min(
                        node.retry_policy.backoff_seconds * (node.retry_policy.backoff_multiplier ** (attempt - 1)),
                        node.retry_policy.max_backoff_seconds,
                    )
                    await asyncio.sleep(backoff)

            # RETRY_NODE 耗尽安全防护
            if outcome and outcome.signal == FlowSignal.RETRY_NODE:
                outcome.status = NodeStatus.FAILED
                outcome.signal = FlowSignal.PROCEED

            if outcome is None:
                outcome = StepOutcome(node_id=node.id, status=NodeStatus.FAILED)

            ctx.record_step_outcome(outcome)

            # 处理显式控制流信号
            if outcome.signal == FlowSignal.HALT_SUCCESS:
                current_id = TERMINAL_COMPLETE_ID
                break
            elif outcome.signal == FlowSignal.HALT_FAIL:
                current_id = TERMINAL_FAIL_ID
                break
            elif outcome.signal == FlowSignal.BRANCH and outcome.target_node_id:
                current_id = outcome.target_node_id
                continue

            # 处理终态拦截策略（安全闸门：必须成功执行动作才允许触发终态成功）
            if outcome.matched_terminal and outcome.status in {NodeStatus.SUCCESS, NodeStatus.TERMINAL_EARLY}:
                if node.terminal_policy == TerminalPolicy.STOP_FLOW:
                    logger.info(f"节点 {node.id} 匹配到终态且配置了 STOP_FLOW，流程成功提前结束")
                    current_id = TERMINAL_COMPLETE_ID
                    break
                elif node.terminal_policy == TerminalPolicy.BRANCH_TO:
                    current_id = node.terminal_branch_target or node.next_node_id or TERMINAL_COMPLETE_ID
                    continue

            # 拓扑推进（SKIPPED 正常推进，严禁失败流入成功终态）
            if outcome.status in {NodeStatus.SUCCESS, NodeStatus.TERMINAL_EARLY, NodeStatus.SKIPPED}:
                current_id = node.next_node_id or TERMINAL_COMPLETE_ID
            else:
                current_id = node.on_failure_node_id or TERMINAL_FAIL_ID

        is_success = (current_id == TERMINAL_COMPLETE_ID)
        return {
            "status": "success" if is_success else "failed",
            "path": executed_path,
            "steps": total_steps,
        }

    def _run_extractor_node(self, node: ExtractorNode, ctx: ScopedFlowContext) -> StepOutcome:
        src_text = ""
        if node.source_field:
            raw_src = ctx._resolve_path(ctx.build_scope_dict(), node.source_field)
            src_text = str(raw_src or "") if raw_src is not None else ""
        if not src_text:
            src_text = ctx.last_output or ""

        extracted = {}
        if node.regex and src_text:
            match = re.search(node.regex, src_text)
            if match:
                group_dict = match.groupdict()
                for k, var_name in node.export_vars.items():
                    if k in group_dict:
                        extracted[var_name] = group_dict[k]
                    elif match.groups():
                        extracted[var_name] = match.group(1)
        return StepOutcome(
            node_id=node.id,
            status=NodeStatus.SUCCESS,
            extracted_vars=extracted,
            output_text=f"Extracted {len(extracted)} vars",
        )

    def _run_condition_node(self, node: ConditionNode, ctx: ScopedFlowContext) -> StepOutcome:
        for case in node.cases:
            cond_expr = case.get("condition", "")
            target_id = case.get("target_id")
            if ctx.eval_condition(cond_expr):
                return StepOutcome(
                    node_id=node.id,
                    status=NodeStatus.SUCCESS,
                    signal=FlowSignal.BRANCH,
                    target_node_id=target_id,
                )
        return StepOutcome(
            node_id=node.id,
            status=NodeStatus.SUCCESS,
            signal=FlowSignal.BRANCH if node.default_target_id else FlowSignal.PROCEED,
            target_node_id=node.default_target_id,
        )

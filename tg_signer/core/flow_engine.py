# tg_signer/core/flow_engine.py
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from functools import lru_cache
from typing import Any, Awaitable, Callable, Dict, Optional

from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_event_bus import TelegramEventBus
from tg_signer.core.flow_models import (
    TERMINAL_COMPLETE_ID,
    TERMINAL_FAIL_ID,
    BaseFlowNode,
    ConditionNode,
    DelayNode,
    ExecutionGraph,
    ExtractorNode,
    FlowSignal,
    NodeStatus,
    StepOutcome,
    TerminalPolicy,
    WaitEventNode,
)

logger = logging.getLogger("tg_signer.flow_engine")


class FlowLoopLimitExceededError(RuntimeError):
    """工作流执行步骤超过上限熔断"""


class PulseFlowEngine:
    """下一代无副作用状态机调度引擎"""

    def __init__(self, event_bus: Optional[TelegramEventBus] = None):
        self.event_bus = event_bus

    async def run(
        self,
        graph: ExecutionGraph,
        ctx: ScopedFlowContext,
        executor: Callable[[BaseFlowNode, ScopedFlowContext], Awaitable[StepOutcome]],
        event_bus: Optional[TelegramEventBus] = None,
    ) -> Dict[str, Any]:
        run_start = time.perf_counter()
        bus = event_bus or self.event_bus
        current_id: Optional[str] = graph.entry_node_id
        executed_path = []
        visit_counts: Dict[str, int] = {}
        total_steps = 0
        last_failure_error: Optional[str] = None

        while current_id not in {TERMINAL_COMPLETE_ID, TERMINAL_FAIL_ID, None}:
            if total_steps >= graph.max_total_steps:
                raise FlowLoopLimitExceededError(
                    f"工作流执行已触发安全硬熔断：超过单次最大步数 {graph.max_total_steps}"
                )

            node = graph.nodes.get(current_id)
            if not node:
                logger.error(f"工作流引用了不存在的步骤: {current_id}")
                return {
                    "status": "failed",
                    "path": executed_path,
                    "error": f"NodeNotFound: {current_id}",
                    "duration_ms": round((time.perf_counter() - run_start) * 1000, 2),
                }

            visits = visit_counts.get(node.id, 0)
            if visits >= node.loop_policy.max_visits:
                raise FlowLoopLimitExceededError(
                    f"节点 {node.id} 访问次数 ({visits + 1}) 超过允许上限: {node.loop_policy.max_visits}"
                )

            visit_counts[node.id] = visits + 1
            executed_path.append(node.id)
            total_steps += 1

            # 执行具体节点（原生处理 Extractor/Condition/Delay/WaitEvent，外部委派 Action）
            attempt = 0
            outcome: Optional[StepOutcome] = None
            while attempt < node.retry_policy.max_attempts:
                attempt += 1
                step_start = time.perf_counter()
                try:
                    if isinstance(node, ExtractorNode):
                        outcome = self._run_extractor_node(node, ctx)
                    elif isinstance(node, ConditionNode):
                        outcome = self._run_condition_node(node, ctx)
                    elif isinstance(node, DelayNode):
                        outcome = await self._run_delay_node(node)
                    elif isinstance(node, WaitEventNode) and bus is not None:
                        outcome = await self._run_wait_event_node(node, ctx, bus)
                    else:
                        outcome = await asyncio.wait_for(
                            executor(node, ctx), timeout=node.timeout_seconds
                        )

                    if outcome.duration_ms <= 0:
                        outcome.duration_ms = round(
                            (time.perf_counter() - step_start) * 1000, 2
                        )

                    if outcome.signal != FlowSignal.RETRY_NODE:
                        break
                    if attempt < node.retry_policy.max_attempts:
                        await self._sleep_before_retry(node, attempt)
                except Exception as exc:
                    step_dur = round((time.perf_counter() - step_start) * 1000, 2)
                    is_timeout = isinstance(exc, (asyncio.TimeoutError, TimeoutError))
                    exc_name = type(exc).__name__
                    allowed = node.retry_policy.retry_on_exceptions
                    if (
                        allowed
                        and exc_name not in allowed
                        and not (is_timeout and "TimeoutError" in allowed)
                    ):
                        outcome = StepOutcome(
                            node_id=node.id,
                            status=NodeStatus.TIMEOUT
                            if is_timeout
                            else NodeStatus.FAILED,
                            error=exc,
                            output_text=str(exc)
                            or ("TimeoutError" if is_timeout else "Execution error"),
                            duration_ms=step_dur,
                        )
                        break

                    if attempt >= node.retry_policy.max_attempts:
                        outcome = StepOutcome(
                            node_id=node.id,
                            status=NodeStatus.TIMEOUT
                            if is_timeout
                            else NodeStatus.FAILED,
                            error=exc,
                            output_text=str(exc)
                            or ("TimeoutError" if is_timeout else "Execution error"),
                            duration_ms=step_dur,
                        )
                        break
                    await self._sleep_before_retry(node, attempt)

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
                current_id = self._normalize_target(outcome.target_node_id)
                continue

            # 处理终态拦截策略（安全闸门：必须成功执行动作才允许触发终态成功）
            if outcome.matched_terminal and outcome.status in {
                NodeStatus.SUCCESS,
                NodeStatus.TERMINAL_EARLY,
            }:
                if node.terminal_policy == TerminalPolicy.STOP_FLOW:
                    logger.info(
                        f"节点 {node.id} 匹配到终态且配置了 STOP_FLOW，流程成功提前结束"
                    )
                    current_id = TERMINAL_COMPLETE_ID
                    break
                elif node.terminal_policy == TerminalPolicy.BRANCH_TO:
                    current_id = self._normalize_target(
                        node.terminal_branch_target
                        or node.next_node_id
                        or TERMINAL_COMPLETE_ID
                    )
                    continue

            # 拓扑推进（SKIPPED 正常推进，严禁失败流入成功终态）
            if outcome.status in {
                NodeStatus.SUCCESS,
                NodeStatus.TERMINAL_EARLY,
                NodeStatus.SKIPPED,
            }:
                current_id = self._normalize_target(
                    node.next_node_id or TERMINAL_COMPLETE_ID
                )
            else:
                last_failure_error = (
                    outcome.output_text
                    or (str(outcome.error) if outcome.error else None)
                    or f"Node {node.id} failed"
                )
                current_id = self._normalize_target(
                    node.on_failure_node_id or TERMINAL_FAIL_ID
                )

        is_success = current_id == TERMINAL_COMPLETE_ID
        res = {
            "status": "success" if is_success else "failed",
            "path": executed_path,
            "steps": total_steps,
            "duration_ms": round((time.perf_counter() - run_start) * 1000, 2),
        }
        if not is_success and last_failure_error:
            res["error"] = last_failure_error
        return res

    def _run_extractor_node(
        self, node: ExtractorNode, ctx: ScopedFlowContext
    ) -> StepOutcome:
        src_text = ""
        if node.source_field:
            raw_src = ctx._resolve_path(ctx.build_scope_dict(), node.source_field)
            src_text = str(raw_src or "") if raw_src is not None else ""
        if not src_text:
            src_text = ctx.last_output or ""

        extracted = {}
        matched = False
        if node.regex and src_text:
            match = self._compile_regex(node.regex).search(src_text)
            if match:
                matched = True
                group_dict = match.groupdict()
                for k, var_name in node.export_vars.items():
                    if k in group_dict:
                        extracted[var_name] = group_dict[k]
                    elif k.isdigit():
                        idx = int(k)
                        if 0 <= idx <= len(match.groups()):
                            extracted[var_name] = match.group(idx)
                    elif match.groups():
                        extracted[var_name] = match.group(1)

        # 结构化 JSON 提取增强
        if node.metadata.get("extract_json") and src_text:
            try:
                data = json.loads(src_text)
                for k, var_name in node.export_vars.items():
                    val = ctx._resolve_path(data, k)
                    if val is not None:
                        extracted[var_name] = val
                        matched = True
            except Exception:
                pass

        is_required = bool(node.metadata.get("required", False))
        if is_required and (not matched or not extracted):
            return StepOutcome(
                node_id=node.id,
                status=NodeStatus.FAILED,
                output_text=f"Required extraction failed for node {node.id}",
                updates_last_output=False,
            )

        return StepOutcome(
            node_id=node.id,
            status=NodeStatus.SUCCESS,
            extracted_vars=extracted,
            output_text=f"Extracted {len(extracted)} vars",
            updates_last_output=False,
        )

    def _run_condition_node(
        self, node: ConditionNode, ctx: ScopedFlowContext
    ) -> StepOutcome:
        for case in node.cases:
            cond_expr = case.get("condition", "")
            target_id = self._normalize_target(case.get("target_id"))
            if ctx.eval_condition(cond_expr):
                return StepOutcome(
                    node_id=node.id,
                    status=NodeStatus.SUCCESS,
                    signal=FlowSignal.BRANCH,
                    target_node_id=target_id,
                    updates_last_output=False,
                )
        default_target = self._normalize_target(node.default_target_id)
        return StepOutcome(
            node_id=node.id,
            status=NodeStatus.SUCCESS,
            signal=FlowSignal.BRANCH if default_target else FlowSignal.PROCEED,
            target_node_id=default_target,
            updates_last_output=False,
        )

    @staticmethod
    async def _run_delay_node(node: DelayNode) -> StepOutcome:
        if node.seconds > 0:
            await asyncio.sleep(node.seconds)
        return StepOutcome(
            node_id=node.id,
            status=NodeStatus.SUCCESS,
            output_text=f"Delayed for {node.seconds:g}s",
            updates_last_output=False,
        )

    @staticmethod
    async def _run_wait_event_node(
        node: WaitEventNode,
        ctx: ScopedFlowContext,
        bus: TelegramEventBus,
    ) -> StepOutcome:
        chat_id = int(
            node.metadata.get("chat_id")
            or ctx.system.get("chat_id")
            or ctx.account.get("chat_id")
            or 0
        )
        thread_id = node.metadata.get("message_thread_id")
        min_msg_id = node.metadata.get("min_message_id")
        queue = bus.subscribe(
            chat_id=chat_id,
            message_thread_id=thread_id,
            min_message_id=min_msg_id,
        )
        try:
            deadline = time.time() + node.timeout_seconds
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return StepOutcome(
                        node_id=node.id,
                        status=NodeStatus.TIMEOUT,
                        output_text=f"Timeout waiting for event on chat {chat_id}",
                    )
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=remaining)
                except (asyncio.TimeoutError, TimeoutError):
                    return StepOutcome(
                        node_id=node.id,
                        status=NodeStatus.TIMEOUT,
                        output_text=f"Timeout waiting for event on chat {chat_id}",
                    )

                if node.filter_patterns:
                    matched = any(
                        (pat in event.text or re.search(pat, event.text))
                        for pat in node.filter_patterns
                    )
                    if not matched:
                        continue

                return StepOutcome(
                    node_id=node.id,
                    status=NodeStatus.SUCCESS,
                    output_text=event.text,
                    updates_last_output=True,
                )
        finally:
            bus.unsubscribe(chat_id, thread_id, queue)

    @staticmethod
    def _normalize_target(tid: Optional[str]) -> Optional[str]:
        if not tid:
            return None
        s = tid.strip()
        if s.upper() == "COMPLETE":
            return TERMINAL_COMPLETE_ID
        if s.upper() == "FAIL":
            return TERMINAL_FAIL_ID
        return s

    @staticmethod
    async def _sleep_before_retry(node: BaseFlowNode, attempt: int) -> None:
        """按统一退避策略暂停，覆盖异常和显式 RETRY_NODE 两条路径。"""
        policy = node.retry_policy
        backoff = min(
            policy.backoff_seconds * (policy.backoff_multiplier ** (attempt - 1)),
            policy.max_backoff_seconds,
        )
        if backoff > 0:
            await asyncio.sleep(backoff)

    @staticmethod
    @lru_cache(maxsize=128)
    def _compile_regex(pattern: str) -> re.Pattern[str]:
        """缓存重复循环中使用的提取正则，避免每次访问节点都重新编译。"""
        return re.compile(pattern)

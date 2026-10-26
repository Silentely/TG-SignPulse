# tg_signer/core/flow_engine.py
from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import time
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Dict, Optional, Pattern

from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_event_bus import TelegramEventBus
from tg_signer.core.flow_models import (
    TERMINAL_COMPLETE_ID,
    TERMINAL_FAIL_ID,
    ActionNode,
    BaseFlowNode,
    ConditionNode,
    DelayNode,
    ExecutionGraph,
    ExtractorNode,
    FlowLoopLimitExceededError,
    FlowSignal,
    NodeStatus,
    ParallelMode,
    ParallelNode,
    StepOutcome,
    SubflowNode,
    TerminalPolicy,
    WaitEventNode,
    redact_sensitive_value,
)

logger = logging.getLogger("tg_signer.flow_engine")


def normalize_text_for_matching(text: str) -> str:
    """宽松匹配预处理：转小写，去除空白与中英文标点符号。"""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"\s+", "", text)
    import unicodedata

    return "".join(
        c for c in text if not unicodedata.category(c).startswith(("P", "S"))
    )


def matches_retry_keyword(text: str, keywords: Any) -> Optional[str]:
    """检查文本是否命中重试关键词表（宽松包含匹配，忽略标点与大小写，优先匹配更长更具体的词）。"""
    if not text or not keywords:
        return None
    norm_text = normalize_text_for_matching(text)
    if not norm_text:
        return None
    sorted_kws = sorted(
        [k for k in keywords if k and str(k).strip()],
        key=lambda k: len(str(k)),
        reverse=True,
    )
    for kw in sorted_kws:
        norm_kw = normalize_text_for_matching(str(kw))
        if norm_kw and norm_kw in norm_text:
            return str(kw).strip()
    return None


def _redact_trace_text(value: str) -> str:
    """Mask credential-like key/value pairs without masking ordinary Telegram text."""
    if not value:
        return value
    return re.sub(
        r"(?i)\b(token|password|secret|api[_-]?key|session|credential)\b\s*[:=]\s*([^\s,;]+)",
        lambda m: f"{m.group(1)}=***",
        str(value),
    )


class PulseFlowEngine:
    """下一代执行引擎 (PulseFlow v4)

    支持：
    - 有向图 (DAG / 拓扑循环) 调度
    - 运行时表达式条件判定与安全求值
    - 声明式变量提取与动态注入
    - 自适应指数退避重试 (Exponential Backoff)
    - 响应式事件驱动与水位线回补 (TelegramEventBus)
    - 子工作流 (SubflowNode) 嵌套调度
    - 并发分支与聚拢调度 (ParallelNode Fork-Join)
    - 生命周期事件监听器 (on_step_start / on_step_finish)
    - 全局错误处理器降级 (graph.error_handler_node_id)
    - 节点级条件守卫 (node.run_if / node.skip_if)
    - 断点恢复执行 (graph.resume_from_node_id)
    - 全局节点异步超时保护与连续失败熔断 (consecutive_failure_limit)
    - 敏感变量与凭据自动脱敏输出
    - 结构化执行性能与健康度指标度量 (metrics)
    """

    def __init__(self, event_bus: Optional[TelegramEventBus] = None):
        self._compiled_regexes: OrderedDict[str, Pattern] = OrderedDict()
        self._event_bus = event_bus

    def _compile_regex(self, pattern: str) -> Pattern:
        if pattern not in self._compiled_regexes:
            self._compiled_regexes[pattern] = re.compile(pattern)
            if len(self._compiled_regexes) > 256:
                self._compiled_regexes.popitem(last=False)
        else:
            self._compiled_regexes.move_to_end(pattern)
        return self._compiled_regexes[pattern]

    async def _execute_node(
        self,
        node: BaseFlowNode,
        ctx: ScopedFlowContext,
        executor: Callable[[BaseFlowNode, ScopedFlowContext], Awaitable[StepOutcome]],
        bus: Optional[TelegramEventBus] = None,
        on_step_start: Optional[
            Callable[[BaseFlowNode, ScopedFlowContext], Any]
        ] = None,
        on_step_finish: Optional[
            Callable[[BaseFlowNode, StepOutcome, ScopedFlowContext], Any]
        ] = None,
        graph: Optional[ExecutionGraph] = None,
    ) -> StepOutcome:
        """派发单节点多态执行"""
        if isinstance(node, ActionNode):
            ctx.system["last_action_node"] = node
            return await executor(node, ctx)
        elif isinstance(node, ConditionNode):
            return self._run_condition_node(node, ctx)
        elif isinstance(node, ExtractorNode):
            return self._run_extractor_node(node, ctx)
        elif isinstance(node, DelayNode):
            return await self._run_delay_node(node)
        elif isinstance(node, SubflowNode):
            return await self._run_subflow_node(
                node,
                ctx,
                executor,
                bus,
                on_step_start,
                on_step_finish,
            )
        elif isinstance(node, ParallelNode):
            return await self._run_parallel_node(
                node,
                ctx,
                executor,
                bus,
                on_step_start,
                on_step_finish,
            )
        elif isinstance(node, WaitEventNode):
            if bus is not None:
                return await self._run_wait_event_node(
                    node, ctx, bus, executor=executor, graph=graph
                )
            return StepOutcome(
                node_id=node.id,
                status=NodeStatus.FAILED,
                output_text=f"WaitEventNode {node.id} 执行失败: 未提供事件总线 (TelegramEventBus)，无法监听事件",
                updates_last_output=False,
            )
        else:
            return await executor(node, ctx)

    async def run(
        self,
        graph: ExecutionGraph,
        ctx: ScopedFlowContext,
        executor: Callable[[BaseFlowNode, ScopedFlowContext], Awaitable[StepOutcome]],
        event_bus: Optional[TelegramEventBus] = None,
        on_step_start: Optional[
            Callable[[BaseFlowNode, ScopedFlowContext], Any]
        ] = None,
        on_step_finish: Optional[
            Callable[[BaseFlowNode, StepOutcome, ScopedFlowContext], Any]
        ] = None,
    ) -> Dict[str, Any]:
        """运行执行图"""
        bus = event_bus or self._event_bus
        current_id: Optional[str] = graph.resume_from_node_id or graph.entry_node_id
        executed_path: list[str] = []
        node_visit_counts: Dict[str, int] = {}
        total_steps = 0
        consecutive_failures = 0
        run_start = time.perf_counter()
        last_failure_error: Optional[str] = None
        last_failure_code: Optional[str] = None
        last_failure_category: Optional[str] = None
        last_non_retryable: bool = False
        last_semantic_disposition: Optional[str] = None

        try:
            while current_id and current_id not in {
                TERMINAL_COMPLETE_ID,
                TERMINAL_FAIL_ID,
            }:
                if total_steps >= graph.max_total_steps:
                    logger.error(f"工作流总步数超过最大限制: {graph.max_total_steps}")
                    current_id = TERMINAL_FAIL_ID
                    last_failure_error = (
                        f"Flow step limit exceeded: {graph.max_total_steps}"
                    )
                    break

                node = graph.nodes.get(current_id)
                if not node:
                    logger.error(f"节点未找到: {current_id}")
                    current_id = TERMINAL_FAIL_ID
                    last_failure_error = f"Node not found: {current_id}"
                    break

                total_steps += 1
                executed_path.append(node.id)

                # 循环防死锁检测
                visit_count = node_visit_counts.get(node.id, 0) + 1
                node_visit_counts[node.id] = visit_count
                if not node.loop_policy.allow_loop and visit_count > 1:
                    logger.error(
                        f"节点 {node.id} 不允许循环访问，当前访问次数: {visit_count}"
                    )
                    raise FlowLoopLimitExceededError(
                        f"Node {node.id} loop not allowed (visited {visit_count} times, path: {' -> '.join(executed_path)})"
                    )
                if (
                    node.loop_policy.allow_loop
                    and visit_count > node.loop_policy.max_visits
                ):
                    logger.error(
                        f"节点 {node.id} 访问次数 {visit_count} 超过最大允许 {node.loop_policy.max_visits}"
                    )
                    raise FlowLoopLimitExceededError(
                        f"Node {node.id} loop limit exceeded ({visit_count}/{node.loop_policy.max_visits}, path: {' -> '.join(executed_path)})"
                    )

                # 生命周期前置钩子
                if on_step_start is not None:
                    try:
                        hook_res = on_step_start(node, ctx)
                        if asyncio.iscoroutine(hook_res):
                            await hook_res
                    except Exception as hook_err:
                        logger.warning(
                            f"on_step_start 钩子执行异常 ({node.id}): {hook_err}"
                        )

                # 节点级条件守卫 (skip_if / run_if)
                should_skip = False
                skip_reason = ""
                if node.skip_if and ctx.evaluate_condition(node.skip_if):
                    should_skip = True
                    skip_reason = (
                        f"Condition skip_if '{node.skip_if}' evaluated to True"
                    )
                elif node.run_if and not ctx.evaluate_condition(node.run_if):
                    should_skip = True
                    skip_reason = f"Condition run_if '{node.run_if}' evaluated to False"

                if should_skip:
                    logger.info(f"节点 {node.id} 命中守卫条件跳过: {skip_reason}")
                    outcome = StepOutcome(
                        node_id=node.id,
                        status=NodeStatus.SKIPPED,
                        output_text=skip_reason,
                        updates_last_output=False,
                    )
                    ctx.record_step_outcome(outcome)
                    if on_step_finish is not None:
                        try:
                            hook_res = on_step_finish(node, outcome, ctx)
                            if asyncio.iscoroutine(hook_res):
                                await hook_res
                        except Exception as hook_err:
                            logger.warning(
                                f"on_step_finish 钩子执行异常 ({node.id}): {hook_err}"
                            )
                    current_id = self._normalize_target(
                        node.next_node_id or TERMINAL_COMPLETE_ID
                    )
                    continue

                # 节点执行与重试循环
                attempt = 0
                outcome: Optional[StepOutcome] = None

                while attempt < node.retry_policy.max_attempts:
                    attempt += 1
                    step_start = time.perf_counter()
                    try:
                        timeout_sec = (
                            float(node.timeout_seconds)
                            if node.timeout_seconds and node.timeout_seconds > 0
                            else 25.0
                        )
                        wait_for_timeout = timeout_sec
                        if isinstance(node, WaitEventNode):
                            action = graph.nodes.get(
                                node.action_node_id
                            ) or ctx.system.get("last_action_node")
                            resend_timeout = (
                                float(action.timeout_seconds or 25.0)
                                if action
                                else 25.0
                            )
                            # 每次重试均有独立回复窗口，另预留发送和间隔时间。
                            wait_for_timeout = (
                                timeout_sec * (1 + node.max_retries)
                                + node.max_retries
                                * (node.retry_interval + resend_timeout)
                                + 3.0
                            )
                        outcome = await asyncio.wait_for(
                            self._execute_node(
                                node,
                                ctx,
                                executor,
                                bus,
                                on_step_start,
                                on_step_finish,
                                graph=graph,
                            ),
                            timeout=wait_for_timeout,
                        )

                        if outcome.signal != FlowSignal.RETRY_NODE:
                            break
                        if attempt < node.retry_policy.max_attempts:
                            await self._sleep_before_retry(node, attempt)
                    except Exception as exc:
                        step_dur = round((time.perf_counter() - step_start) * 1000, 2)
                        is_timeout = isinstance(
                            exc, (asyncio.TimeoutError, TimeoutError)
                        )
                        exc_name = type(exc).__name__
                        allowed = node.retry_policy.retry_on_exceptions
                        has_side_effect = (
                            getattr(ctx, "pulseflow_side_effect_started", False)
                            or getattr(ctx, "side_effect_started", False)
                            or (
                                hasattr(ctx, "system")
                                and isinstance(ctx.system, dict)
                                and ctx.system.get("side_effect_started", False)
                            )
                        )
                        if (
                            getattr(exc, "non_retryable", False)
                            or has_side_effect
                            or (
                                allowed
                                and exc_name not in allowed
                                and not (is_timeout and "TimeoutError" in allowed)
                            )
                        ):
                            outcome = StepOutcome(
                                node_id=node.id,
                                status=NodeStatus.TIMEOUT
                                if is_timeout
                                else NodeStatus.FAILED,
                                error=exc,
                                output_text=str(exc)
                                or (
                                    "TimeoutError" if is_timeout else "Execution error"
                                ),
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
                                or (
                                    "TimeoutError" if is_timeout else "Execution error"
                                ),
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

                # 检查受控终止 (SemanticReviewRequired / SemanticStopRequested / non_retryable)
                err = outcome.error
                is_controlled = False
                if err is not None:
                    f_code = getattr(err, "failure_code", None)
                    s_disp = getattr(err, "semantic_disposition", None)
                    nr = getattr(err, "non_retryable", False)
                    if f_code or s_disp or nr:
                        last_failure_code = f_code
                        last_semantic_disposition = s_disp
                        last_non_retryable = nr or True
                        is_controlled = True
                if outcome.details and isinstance(outcome.details, dict):
                    f_cat = outcome.details.get("failure_category")
                    if f_cat:
                        last_failure_category = str(f_cat)
                        if f_cat == "retry_exhausted":
                            last_non_retryable = True
                    s_disp = outcome.details.get("semantic_disposition")
                    if s_disp in {"review", "stop"}:
                        last_semantic_disposition = s_disp
                        last_non_retryable = True
                        if s_disp == "review":
                            last_failure_code = "semantic_review_required"
                        elif s_disp == "stop":
                            last_failure_code = "semantic_stop_requested"
                        is_controlled = True

                if is_controlled:
                    current_id = TERMINAL_FAIL_ID
                    last_failure_error = (
                        outcome.output_text
                        or (str(outcome.error) if outcome.error else None)
                        or f"Node {node.id} controlled termination: {last_failure_code or last_semantic_disposition}"
                    )
                    break

                # 统计连续失败与熔断检测
                if outcome.status in {NodeStatus.SUCCESS, NodeStatus.TERMINAL_EARLY}:
                    consecutive_failures = 0
                elif outcome.status in {NodeStatus.FAILED, NodeStatus.TIMEOUT}:
                    consecutive_failures += 1
                    if (
                        graph.consecutive_failure_limit is not None
                        and consecutive_failures >= graph.consecutive_failure_limit
                    ):
                        logger.error(
                            f"工作流触发连续失败熔断: 连续失败 {consecutive_failures} 次 (上限 {graph.consecutive_failure_limit})"
                        )
                        current_id = TERMINAL_FAIL_ID
                        last_failure_error = f"Circuit breaker triggered: consecutive failures reached {graph.consecutive_failure_limit}"
                        break

                # 生命周期后置钩子
                if on_step_finish is not None:
                    try:
                        hook_res = on_step_finish(node, outcome, ctx)
                        if asyncio.iscoroutine(hook_res):
                            await hook_res
                    except Exception as hook_err:
                        logger.warning(
                            f"on_step_finish 钩子执行异常 ({node.id}): {hook_err}"
                        )

                # 处理显式控制流信号
                if outcome.signal == FlowSignal.HALT_SUCCESS:
                    current_id = TERMINAL_COMPLETE_ID
                    break
                elif outcome.signal == FlowSignal.HALT_FAIL:
                    current_id = TERMINAL_FAIL_ID
                    last_failure_error = (
                        outcome.output_text
                        or (str(outcome.error) if outcome.error else None)
                        or f"Node {node.id} halted with failure"
                    )
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
                    # 优先节点 on_failure_node_id，次选全局 error_handler_node_id（避免自身循环错误）
                    fallback_target = node.on_failure_node_id
                    if (
                        not fallback_target
                        and graph.error_handler_node_id
                        and node.id != graph.error_handler_node_id
                    ):
                        fallback_target = graph.error_handler_node_id
                    current_id = self._normalize_target(
                        fallback_target or TERMINAL_FAIL_ID
                    )
        except asyncio.CancelledError:
            logger.warning(
                f"PulseFlowEngine 执行被外部异步取消: current_node={current_id}, path={' -> '.join(executed_path)}"
            )
            raise

        is_success = current_id == TERMINAL_COMPLETE_ID
        total_duration = round((time.perf_counter() - run_start) * 1000, 2)
        res = {
            "status": "success" if is_success else "failed",
            "path": executed_path,
            "steps": total_steps,
            "duration_ms": total_duration,
            "trace": self._build_trace(executed_path, ctx),
            "metrics": self._calculate_metrics(executed_path, ctx, total_duration),
        }
        from tg_signer.core.operation_receipts import OperationAttemptState

        receipts = getattr(ctx, "operation_receipts", [])
        unknown_operation = any(
            r.state == OperationAttemptState.UNKNOWN for r in receipts
        )
        res["business_status"] = (
            "unknown"
            if unknown_operation
            else (
                "confirmed"
                if is_success
                and any(
                    isinstance(graph.nodes.get(so.node_id), WaitEventNode)
                    and so.status == NodeStatus.SUCCESS
                    for so in ctx.step_outcomes.values()
                )
                else ("not_evaluated" if is_success else "failed")
            )
        )
        if is_success and any(
            so.details.get("business_status") == "partial"
            for so in ctx.step_outcomes.values()
        ):
            res["business_status"] = "partial"
        res["operation_receipts"] = [
            {
                "operation_id": r.operation_id,
                "node_id": r.node_id,
                "attempt": r.attempt,
                "kind": r.kind,
                "state": r.state.value,
                "remote_id": r.remote_id,
                "evidence": r.evidence,
            }
            for r in receipts
        ]
        if not is_success:
            if not last_failure_error:
                last_failure_error = (
                    f"Workflow failed at node {current_id or 'unknown'}"
                )
            res["error"] = _redact_trace_text(last_failure_error)
            res["failure_code"] = last_failure_code
            res["failure_category"] = last_failure_category
            res["non_retryable"] = last_non_retryable
            res["semantic_disposition"] = last_semantic_disposition
        return res

    @staticmethod
    def _calculate_metrics(
        executed_path: list[str], ctx: ScopedFlowContext, total_duration_ms: float
    ) -> Dict[str, Any]:
        """计算流程运行的性能与健康度指标摘要"""
        total_steps = len(executed_path)
        visited_nodes = list(dict.fromkeys(executed_path))
        succeeded = 0
        failed = 0
        skipped = 0
        timeouts = 0
        durations = []
        slowest_node = None
        max_dur = -1.0

        outcomes = ctx.step_history or [
            ctx.step_outcomes[nid] for nid in executed_path if nid in ctx.step_outcomes
        ]
        for so in outcomes:
            durations.append(so.duration_ms)
            if so.duration_ms > max_dur:
                max_dur = so.duration_ms
                slowest_node = {"node_id": so.node_id, "duration_ms": so.duration_ms}
            if so.status in {NodeStatus.SUCCESS, NodeStatus.TERMINAL_EARLY}:
                succeeded += 1
            elif so.status == NodeStatus.SKIPPED:
                skipped += 1
            elif so.status == NodeStatus.TIMEOUT:
                timeouts += 1
                failed += 1
            elif so.status == NodeStatus.FAILED:
                failed += 1

        avg_dur = round(sum(durations) / len(durations), 2) if durations else 0.0
        return {
            "total_steps": total_steps,
            "unique_nodes_count": len(visited_nodes),
            "succeeded_steps": succeeded,
            "failed_steps": failed,
            "skipped_steps": skipped,
            "timeout_steps": timeouts,
            "total_duration_ms": total_duration_ms,
            "avg_step_duration_ms": avg_dur,
            "slowest_step": slowest_node,
        }

    @staticmethod
    def _build_trace(
        executed_path: list[str],
        ctx: ScopedFlowContext,
        redact_sensitive: bool = True,
    ) -> list[Dict[str, Any]]:
        """为全流程生成节点级执行快照序列，支持端到端调试与可视化展示"""
        trace = []
        outcomes = ctx.step_history or [
            ctx.step_outcomes[nid] for nid in executed_path if nid in ctx.step_outcomes
        ]
        for so in outcomes:
            if so is not None:
                extracted = (
                    redact_sensitive_value(so.extracted_vars)
                    if redact_sensitive
                    else dict(so.extracted_vars)
                )
                trace.append(
                    {
                        "node_id": so.node_id,
                        "status": so.status.value,
                        "duration_ms": so.duration_ms,
                        "output": _redact_trace_text(so.output_text),
                        "output_text": _redact_trace_text(so.output_text),
                        "extracted_vars": extracted,
                        "matched_terminal": so.matched_terminal,
                        "signal": so.signal.value,
                        "target_node_id": so.target_node_id,
                        "error": _redact_trace_text(str(so.error))
                        if so.error
                        else None,
                        "details": so.details,
                    }
                )
        return trace

    async def _run_subflow_node(
        self,
        node: SubflowNode,
        ctx: ScopedFlowContext,
        executor: Callable[[BaseFlowNode, ScopedFlowContext], Awaitable[StepOutcome]],
        bus: Optional[TelegramEventBus] = None,
        on_step_start: Optional[
            Callable[[BaseFlowNode, ScopedFlowContext], Any]
        ] = None,
        on_step_finish: Optional[
            Callable[[BaseFlowNode, StepOutcome, ScopedFlowContext], Any]
        ] = None,
    ) -> StepOutcome:
        if node.subflow_graph is None:
            return StepOutcome(
                node_id=node.id,
                status=NodeStatus.FAILED,
                output_text="SubflowNode has no subflow_graph",
                updates_last_output=False,
            )
        # 深度隔离子工作流上下文环境，继承父级上下文
        sub_ctx = ScopedFlowContext(
            system=copy.deepcopy(ctx.system),
            account=copy.deepcopy(ctx.account),
        )
        sub_ctx.vars = copy.deepcopy(ctx.vars)
        sub_ctx.last_output = ctx.last_output

        # 映射输入变量 parent -> sub
        if node.input_vars:
            for target_k, src_k in node.input_vars.items():
                if ctx.has_var(src_k):
                    sub_ctx.set_var(target_k, ctx.get_var(src_k))

        sub_res = await self.run(
            node.subflow_graph,
            sub_ctx,
            executor,
            event_bus=bus,
            on_step_start=on_step_start,
            on_step_finish=on_step_finish,
        )
        is_sub_ok = sub_res.get("status") == "success"

        extracted = {}
        if is_sub_ok:
            # 映射输出变量 sub -> parent
            if node.output_vars:
                for sub_k, parent_k in node.output_vars.items():
                    if sub_ctx.has_var(sub_k):
                        val = sub_ctx.get_var(sub_k)
                        extracted[parent_k] = val
                        ctx.set_var(parent_k, val)

            if node.export_vars:
                for k in node.export_vars:
                    if k in sub_ctx.vars:
                        extracted[k] = sub_ctx.vars[k]
                        ctx.set_var(k, sub_ctx.vars[k])

        return StepOutcome(
            node_id=node.id,
            status=NodeStatus.SUCCESS if is_sub_ok else NodeStatus.FAILED,
            output_text=f"Subflow finished with status: {sub_res.get('status')}",
            extracted_vars=extracted,
            updates_last_output=True,
        )

    async def _run_parallel_node(
        self,
        node: ParallelNode,
        ctx: ScopedFlowContext,
        executor: Callable[[BaseFlowNode, ScopedFlowContext], Awaitable[StepOutcome]],
        bus: Optional[TelegramEventBus] = None,
        on_step_start: Optional[
            Callable[[BaseFlowNode, ScopedFlowContext], Any]
        ] = None,
        on_step_finish: Optional[
            Callable[[BaseFlowNode, StepOutcome, ScopedFlowContext], Any]
        ] = None,
    ) -> StepOutcome:
        """并发执行多个子执行图分支 (Fork-Join)"""
        if not node.branches:
            return StepOutcome(
                node_id=node.id,
                status=NodeStatus.SUCCESS,
                output_text="ParallelNode has no branches",
                updates_last_output=False,
            )

        sem = (
            asyncio.Semaphore(node.max_concurrency)
            if node.max_concurrency and node.max_concurrency > 0
            else None
        )

        async def _run_single_branch(
            branch_graph: ExecutionGraph,
        ) -> tuple[Dict[str, Any], ScopedFlowContext]:
            branch_ctx = ScopedFlowContext(
                system=copy.deepcopy(ctx.system),
                account=copy.deepcopy(ctx.account),
            )
            branch_ctx.vars = copy.deepcopy(ctx.vars)
            branch_ctx.last_output = ctx.last_output

            if sem is not None:
                async with sem:
                    res = await self.run(
                        branch_graph,
                        branch_ctx,
                        executor,
                        event_bus=bus,
                        on_step_start=on_step_start,
                        on_step_finish=on_step_finish,
                    )
            else:
                res = await self.run(
                    branch_graph,
                    branch_ctx,
                    executor,
                    event_bus=bus,
                    on_step_start=on_step_start,
                    on_step_finish=on_step_finish,
                )
            return res, branch_ctx

        branch_coros = [_run_single_branch(bg) for bg in node.branches]
        results = await asyncio.gather(*branch_coros, return_exceptions=True)

        merged_vars: Dict[str, Any] = {}
        written_values: Dict[str, list[Any]] = {}
        succeeded_count = 0
        failed_count = 0

        for r in results:
            if isinstance(r, Exception):
                failed_count += 1
                continue
            branch_res, branch_ctx = r
            if branch_res.get("status") == "success":
                succeeded_count += 1
                if node.join_strategy == "merge":
                    for key, value in branch_ctx.vars.items():
                        if key in ctx.vars and value == ctx.vars[key]:
                            continue
                        written_values.setdefault(key, []).append(value)
            else:
                failed_count += 1

        is_overall_success = False
        if node.mode == ParallelMode.ALL:
            is_overall_success = failed_count == 0
        elif node.mode == ParallelMode.ANY:
            is_overall_success = succeeded_count > 0
        elif node.mode == ParallelMode.ALL_SETTLED:
            # ALL_SETTLED reports completion of every branch, including failures.
            is_overall_success = True

        conflicts = [
            k
            for k, values in written_values.items()
            if any(v != values[0] for v in values[1:])
        ]
        policy = node.variable_conflict_policy.value
        for key, values in written_values.items():
            if policy == "collect" and key in conflicts:
                merged_vars[key] = values
            elif policy == "first_writer":
                merged_vars[key] = values[0]
            else:
                merged_vars[key] = values[-1]
        if conflicts and policy == "fail":
            is_overall_success = False
            merged_vars = {}
        if is_overall_success and node.join_strategy == "merge":
            ctx.vars.update(merged_vars)

        branch_details = []
        branch_unknown = False
        for index, result in enumerate(results):
            if isinstance(result, Exception):
                branch_details.append(
                    {"branch_index": index, "status": "failed", "error": str(result)}
                )
                continue
            branch_res, _branch_ctx = result
            branch_receipts = list(_branch_ctx.operation_receipts)
            branch_unknown = branch_unknown or any(
                receipt.state.value == "unknown" for receipt in branch_receipts
            )
            for receipt in branch_receipts:
                receipt.operation_id = f"{node.id}.branch{index}.{receipt.operation_id}"
                ctx.operation_receipts.append(receipt)
            branch_details.append(
                {
                    "branch_index": index,
                    "status": branch_res.get("status"),
                    "path": branch_res.get("path", []),
                    "trace": branch_res.get("trace", []),
                    "metrics": branch_res.get("metrics", {}),
                    "error": branch_res.get("error"),
                    "business_status": branch_res.get("business_status"),
                    "operation_receipts": [
                        {
                            "operation_id": receipt.operation_id,
                            "node_id": receipt.node_id,
                            "attempt": receipt.attempt,
                            "kind": receipt.kind,
                            "state": receipt.state.value,
                            "remote_id": receipt.remote_id,
                            "evidence": receipt.evidence,
                        }
                        for receipt in branch_receipts
                    ],
                }
            )

        return StepOutcome(
            node_id=node.id,
            status=NodeStatus.SUCCESS if is_overall_success else NodeStatus.FAILED,
            output_text=(
                f"ParallelNode branches finished: {succeeded_count} succeeded, "
                f"{failed_count} failed (mode={node.mode.value})"
            ),
            extracted_vars=merged_vars,
            updates_last_output=False,
            details={
                "branches": branch_details,
                "execution_status": "completed",
                "business_status": (
                    "unknown"
                    if branch_unknown
                    else (
                        "partial"
                        if failed_count and succeeded_count
                        else ("failed" if failed_count else "confirmed")
                    )
                ),
                "variable_conflicts": conflicts,
            },
        )

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

        # 结构化 JSON 提取增强（支持直接解析或在文本中正则探测内嵌 JSON）
        if node.metadata.get("extract_json") and src_text:
            data = None
            try:
                data = json.loads(src_text)
            except Exception:
                m = re.search(r"(\{.*\}|\[.*\])", src_text, re.DOTALL)
                if m:
                    try:
                        data = json.loads(m.group(1))
                    except Exception:
                        data = None
            if data is not None:
                for k, var_name in node.export_vars.items():
                    val = ctx._resolve_path(data, k)
                    if val is not None:
                        extracted[var_name] = val
                        matched = True

        for k, v in extracted.items():
            ctx.set_var(k, v)

        is_required = bool(node.metadata.get("required", False))
        if is_required and not matched:
            return StepOutcome(
                node_id=node.id,
                status=NodeStatus.FAILED,
                output_text=f"Extractor {node.id} failed: pattern '{node.regex}' did not match and is required",
                updates_last_output=False,
            )

        return StepOutcome(
            node_id=node.id,
            status=NodeStatus.SUCCESS,
            extracted_vars=extracted,
            output_text=f"Extracted {len(extracted)} variables",
            updates_last_output=False,
        )

    def _run_condition_node(
        self, node: ConditionNode, ctx: ScopedFlowContext
    ) -> StepOutcome:
        for case in node.cases:
            cond_expr = case.get("condition", "")
            target_id = case.get("target_id")
            if not target_id:
                continue

            try:
                if ctx.evaluate_condition(cond_expr):
                    return StepOutcome(
                        node_id=node.id,
                        status=NodeStatus.SUCCESS,
                        signal=FlowSignal.BRANCH,
                        target_node_id=self._normalize_target(target_id),
                        output_text=f"Condition matched: {cond_expr} -> {target_id}",
                        updates_last_output=False,
                    )
            except Exception as e:
                logger.warning(f"条件判定求值异常 '{cond_expr}': {e}")

        default_target = self._normalize_target(
            node.default_target_id or TERMINAL_FAIL_ID
        )
        return StepOutcome(
            node_id=node.id,
            status=NodeStatus.SUCCESS,
            signal=FlowSignal.BRANCH,
            target_node_id=default_target,
            output_text=f"Condition default branch -> {default_target}",
            updates_last_output=False,
        )

    async def _run_delay_node(self, node: DelayNode) -> StepOutcome:
        delay_sec = max(0.0, float(node.seconds))
        if delay_sec > 0:
            await asyncio.sleep(delay_sec)
        return StepOutcome(
            node_id=node.id,
            status=NodeStatus.SUCCESS,
            output_text=f"Delayed for {delay_sec}s",
            updates_last_output=False,
        )

    async def _run_wait_event_node(
        self,
        node: WaitEventNode,
        ctx: ScopedFlowContext,
        bus: TelegramEventBus,
        executor: Optional[
            Callable[[BaseFlowNode, ScopedFlowContext], Awaitable[StepOutcome]]
        ] = None,
        graph: Optional[ExecutionGraph] = None,
    ) -> StepOutcome:
        def _log_msg(msg: str, level: str = "INFO") -> None:
            log_fn = ctx.system.get("log")
            if callable(log_fn):
                try:
                    log_fn(msg, level=level)
                    return
                except TypeError:
                    try:
                        log_fn(msg)
                        return
                    except Exception:
                        pass
            logger.log(getattr(logging, level.upper(), logging.INFO), msg)

        chat_id = node.metadata.get("chat_id")
        if chat_id is None:
            chat_id = ctx.system.get("chat_id") or ctx.get("chat.id")
        if chat_id is None:
            # 订阅键与 publish 的 chat_id 必须一致，缺失时立即失败而不是必然超时。
            return StepOutcome(
                node_id=node.id,
                status=NodeStatus.FAILED,
                output_text=f"WaitEventNode {node.id} 缺少 chat_id 配置，无法订阅消息事件",
                updates_last_output=False,
            )
        thread_id = node.metadata.get("message_thread_id") or ctx.system.get(
            "message_thread_id"
        )
        min_msg_id = node.metadata.get("min_message_id")
        if min_msg_id is None:
            min_msg_id = ctx.system.get("last_sent_message_id") or ctx.system.get(
                "last_message_id"
            )
        since_ts = (
            node.metadata.get("since_timestamp")
            or ctx.system.get("last_action_started_at")
            or ctx.system.get("last_action_finished_at")
        )
        timeout = float(node.timeout_seconds or 90.0)
        retry_count = 0
        max_retries = int(node.max_retries if node.max_retries is not None else 3)
        retry_interval = float(
            node.retry_interval if node.retry_interval is not None else 10.0
        )
        retry_keywords = getattr(node, "retry_keywords", None) or []

        node_desc = node.name or "等待机器人回复"
        _log_msg(f"步骤 [{node.id}] 开始执行：{node_desc}")
        _log_msg(f"等待机器人回复确认，超时 {int(timeout)} 秒")

        unmatched_replies: list[str] = []
        success_rules = (
            node.success_patterns
            if getattr(node, "success_patterns", None)
            else getattr(node, "filter_patterns", None)
        )

        def _handle_timeout() -> StepOutcome:
            rules_disp = f"，当前设定规则: {success_rules}" if success_rules else ""
            if unmatched_replies:
                last_sample = unmatched_replies[-1].strip()[:150]
                out_msg = (
                    f"等待机器人回复确认超时（{int(timeout)} 秒）。"
                    f"期间收到机器人回复（共 {len(unmatched_replies)} 条，但未匹配设定的成功规则{rules_disp}）：\n「{last_sample}」"
                )
                _log_msg(f"等待机器人确认超时（{int(timeout)} 秒）", level="WARNING")
                _log_msg(
                    f"期间收到机器人回复（但未匹配设定的成功规则{rules_disp}）：\n「{last_sample}」",
                    level="WARNING",
                )
                _log_msg(
                    "建议在任务配置中调整【确认成功关键词】为匹配实际回复的关键词",
                    level="WARNING",
                )
            else:
                out_msg = f"等待机器人回复确认超时（{int(timeout)} 秒）。等待期间未收到机器人的任何回复消息。"
                _log_msg(f"等待机器人确认超时（{int(timeout)} 秒）", level="WARNING")
                _log_msg("等待期间未收到机器人的任何回复消息", level="WARNING")
                _log_msg(
                    "建议检查机器人是否正常在线，或适当提高超时时间", level="WARNING"
                )

            _log_msg(f"步骤 [{node.id}] 执行失败", level="WARNING")
            return StepOutcome(
                node_id=node.id,
                status=NodeStatus.TIMEOUT,
                output_text=out_msg,
                updates_last_output=bool(unmatched_replies),
                details={
                    "chat_id": chat_id,
                    "unmatched_count": len(unmatched_replies),
                    "failure_category": "other"
                    if unmatched_replies
                    else "reply_timeout",
                },
            )

        queue = bus.subscribe(
            chat_id=chat_id,
            message_thread_id=thread_id,
            min_message_id=min_msg_id,
            event_type=node.event_type,
            since_timestamp=since_ts,
        )

        def _delivery_gap() -> StepOutcome | None:
            stats = bus.get_delivery_stats(queue)
            if not stats.dropped_events and not stats.history_evicted_events:
                return None
            message = "消息事件传递存在缺口，无法确认机器人回复结果"
            _log_msg(message, level="WARNING")
            return StepOutcome(
                node_id=node.id,
                status=NodeStatus.FAILED,
                output_text=message,
                updates_last_output=False,
                details={
                    "chat_id": chat_id,
                    "failure_category": "event_gap",
                    "result": "unknown",
                    "event_gap": {
                        "dropped_events": stats.dropped_events,
                        "history_evicted_events": stats.history_evicted_events,
                        "oldest_dropped_at": stats.oldest_dropped_at,
                        "newest_dropped_at": stats.newest_dropped_at,
                    },
                },
            )

        try:
            deadline = time.perf_counter() + timeout
            while True:
                gap = _delivery_gap()
                if gap is not None:
                    return gap
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    return _handle_timeout()
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=remaining)
                except asyncio.TimeoutError:
                    return _delivery_gap() or _handle_timeout()

                gap = _delivery_gap()
                if gap is not None:
                    return gap

                # 1. 目标 chat 隔离（兼容 int 与 str 对比）
                if str(event.chat_id) != str(chat_id):
                    continue

                # 2. 目标话题隔离
                if thread_id is not None and event.message_thread_id != thread_id:
                    continue

                # 3. 过滤自身发送的 outgoing 消息（不能把自己的发送当成回复）
                if getattr(event, "is_outgoing", False):
                    continue

                # 4. 事件类型校验（ANY 模式下内部限制为 Telegram 消息类事件）
                if (
                    node.event_type
                    and node.event_type.upper() not in {"ANY", "ALL"}
                    and event.event_type.upper() != node.event_type.upper()
                ):
                    continue
                elif not node.event_type or node.event_type.upper() in {"ANY", "ALL"}:
                    if event.event_type not in {"NEW_MESSAGE", "EDITED_MESSAGE"}:
                        continue

                # 5. 可选发送者过滤
                expected_sender = node.metadata.get("sender_id")
                if expected_sender is not None and event.sender_id != expected_sender:
                    continue

                # 6. 水位线校验：严格忽略旧消息
                # P0 优先级：优先使用 min_message_id；如果 message_id 无法使用，再使用 since_timestamp
                if (
                    min_msg_id is not None
                    and getattr(event, "message_id", None) is not None
                ):
                    try:
                        if int(event.message_id) <= int(min_msg_id):
                            continue
                    except (ValueError, TypeError):
                        if event.message_id <= min_msg_id:
                            continue
                elif since_ts is not None:
                    if event.occurred_at < since_ts:
                        continue

                text = event.text or ""
                details = {
                    "message_id": event.message_id,
                    "sender_id": event.sender_id,
                    "chat_id": event.chat_id,
                    "event_type": event.event_type,
                }

                def _trigger_observe_if_configured(rule_res: str, ev=event, t=text):
                    sem_res = getattr(node, "semantic_result", None)
                    if not sem_res or not isinstance(sem_res, dict):
                        return
                    if sem_res.get("mode") != "observe":
                        return
                    goal = sem_res.get("goal", "")
                    try:
                        from tg_signer.semantic.models import DecisionRequest
                        from tg_signer.semantic.runtime_port import (
                            get_registered_semantic_runtime,
                        )

                        runtime = get_registered_semantic_runtime()
                        if not runtime:
                            return
                        account_name = (
                            getattr(ctx, "account", {}).get("name", "")
                            if hasattr(ctx, "account")
                            else ""
                        )
                        task_name = ctx.system.get("task_name", "")
                        config_rev = ctx.system.get("config_revision", "")
                        s_key = f"{account_name}:{task_name}:{ev.chat_id}:{node.id}"
                        req = DecisionRequest(
                            kind="result",
                            scope=s_key,
                            state={"text": t, "goal": goal},
                            choices={
                                "success": "成功",
                                "already_done": "已完成",
                                "needs_action": "需要操作",
                                "failure": "失败",
                                "unknown": "未知",
                            },
                            instructions=f"判断回复是否达成目标：{goal}",
                            request_key=f"{s_key}:{ev.event_type}:{ev.message_id}:{ev.message_revision}",
                            config_revision=config_rev,
                        )
                        deadline = time.monotonic() + 10.0
                        runtime.enqueue_observation(
                            req,
                            rule_result=rule_res,
                            run_id=ctx.system.get("run_id", ""),
                            deadline=deadline,
                        )
                    except Exception:
                        pass

                # 8. 关键词重试判定（宽松匹配「再试 / 重试 / 稍后 / 人数较多 / 繁忙 / 请 10 秒后」等）
                matched_kw = matches_retry_keyword(text, retry_keywords)
                if matched_kw:
                    from datetime import datetime, timezone

                    now_utc = datetime.now(timezone.utc).strftime(
                        "%Y-%m-%d %H:%M:%S UTC"
                    )
                    clean_reply = text
                    if retry_count < max_retries:
                        remaining_retries = max_retries - (retry_count + 1)
                        _log_msg(
                            f"[{now_utc}] 收到机器人回复命中重试关键词「{matched_kw}」：{clean_reply}。"
                            f"等待 {retry_interval:.1f} 秒后重试签到指令（第 {retry_count + 1}/{max_retries} 次重试，剩余 {remaining_retries} 次）",
                            level="WARNING",
                        )
                        logger.info(
                            f"WaitEventNode {node.id} 命中重试关键词「{matched_kw}」，将在 {retry_interval}s 后重试 (第 {retry_count + 1}/{max_retries} 次)"
                        )
                        await asyncio.sleep(retry_interval)
                        action_node = (
                            graph.nodes.get(node.action_node_id)
                            if (graph and node.action_node_id)
                            else None
                        ) or ctx.system.get("last_action_node")
                        if action_node is None or executor is None:
                            return StepOutcome(
                                node_id=node.id,
                                status=NodeStatus.FAILED,
                                output_text="命中重试关键词，但没有可重发的动作",
                                details={**details, "failure_category": "other"},
                            )
                        # 更新水位线必须早于重发，保留发送期间到达的极速回复。
                        since_ts = time.time()
                        try:
                            retry_outcome = await asyncio.wait_for(
                                executor(action_node, ctx),
                                timeout=float(action_node.timeout_seconds or 25.0),
                            )
                        except Exception as re_err:
                            return StepOutcome(
                                node_id=node.id,
                                status=NodeStatus.FAILED,
                                output_text=f"重新发送指令异常: {re_err}",
                                error=re_err,
                                details={**details, "failure_category": "other"},
                            )
                        if (
                            retry_outcome is None
                            or retry_outcome.status != NodeStatus.SUCCESS
                        ):
                            return StepOutcome(
                                node_id=node.id,
                                status=NodeStatus.FAILED,
                                output_text=f"重新发送指令失败: {getattr(retry_outcome, 'output_text', '')}",
                                details={**details, "failure_category": "other"},
                            )
                        retry_count += 1
                        new_sent_id = ctx.system.get(
                            "last_sent_message_id"
                        ) or ctx.system.get("last_message_id")
                        min_msg_id = new_sent_id
                        deadline = time.perf_counter() + timeout
                        unmatched_replies.clear()
                        continue
                    else:
                        fail_msg = f"关键词要求重试，已重试 {retry_count} 次，最后一次返回：{clean_reply}"
                        _log_msg(
                            f"[{now_utc}] 步骤 [{node.id}] 执行失败: {fail_msg}",
                            level="WARNING",
                        )
                        details["failure_category"] = "retry_exhausted"
                        details["retry_count"] = retry_count
                        details["max_retries"] = max_retries
                        details["last_reply"] = clean_reply
                        return StepOutcome(
                            node_id=node.id,
                            status=NodeStatus.FAILED,
                            output_text=fail_msg,
                            updates_last_output=True,
                            details=details,
                        )

                # 9. failure_patterns 失败判定
                if getattr(node, "failure_patterns", None):
                    for pattern in node.failure_patterns:
                        if self._compile_regex(pattern).search(text):
                            _trigger_observe_if_configured("failure")
                            _log_msg(f"收到机器人回复：\n{text}")
                            _log_msg(f"命中失败规则：\n{pattern}", level="WARNING")
                            _log_msg("机器人明确返回失败结果", level="WARNING")
                            _log_msg(f"步骤 [{node.id}] 执行失败", level="WARNING")
                            return StepOutcome(
                                node_id=node.id,
                                status=NodeStatus.FAILED,
                                output_text=text,
                                updates_last_output=True,
                                details=details,
                            )
                # 7. success_patterns / filter_patterns 优先成功判定
                success_rules = (
                    node.success_patterns
                    if getattr(node, "success_patterns", None)
                    else getattr(node, "filter_patterns", None)
                )
                if success_rules:
                    for pattern in success_rules:
                        if self._compile_regex(pattern).search(text):
                            _trigger_observe_if_configured("success")
                            _log_msg(f"收到机器人回复：\n{text}")
                            _log_msg(f"命中成功规则：\n{pattern}")
                            _log_msg("机器人已确认签到成功")
                            _log_msg(f"步骤 [{node.id}] 执行完成（成功）")
                            return StepOutcome(
                                node_id=node.id,
                                status=NodeStatus.SUCCESS,
                                output_text=text,
                                updates_last_output=True,
                                details=details,
                            )

                    # 未命中任何成功规则，记录到未匹配列表并回显日志
                    _trigger_observe_if_configured("unmatched")
                    unmatched_replies.append(text)

                    # 若配置了 assist 模式，执行语义辅助结果判定
                    sem_res = getattr(node, "semantic_result", None)
                    if isinstance(sem_res, dict) and sem_res.get("mode") == "assist":
                        disp = "wait"
                        decision = None
                        try:
                            from tg_signer.semantic.models import (
                                DecisionRequest,
                                ResultPolicy,
                            )
                            from tg_signer.semantic.policy import result_disposition
                            from tg_signer.semantic.runtime_port import (
                                get_registered_semantic_runtime,
                            )

                            runtime = get_registered_semantic_runtime()
                            if runtime and runtime.service:
                                account_name = (
                                    getattr(ctx, "account", {}).get("name", "")
                                    if hasattr(ctx, "account")
                                    else ""
                                )
                                task_name = ctx.system.get("task_name", "")
                                config_rev = ctx.system.get("config_revision", "")
                                s_key = f"{account_name}:{task_name}:{event.chat_id}:{node.id}"
                                goal = sem_res.get("goal", "")
                                req = DecisionRequest(
                                    kind="result",
                                    scope=s_key,
                                    state={"text": text, "goal": goal},
                                    choices={
                                        "success": "成功",
                                        "already_done": "已完成",
                                        "needs_action": "需要操作",
                                        "failure": "失败",
                                        "unknown": "未知",
                                    },
                                    instructions=f"判断回复是否达成目标：{goal}",
                                    request_key=f"{s_key}:{event.event_type}:{event.message_id}:{event.message_revision}",
                                    config_revision=config_rev,
                                )
                                pol = ResultPolicy(
                                    mode="assist",
                                    goal=goal,
                                    min_probability=float(
                                        sem_res.get("min_probability", 0.97)
                                    ),
                                    min_margin=float(sem_res.get("min_margin", 0.25)),
                                )
                                eval_deadline = min(deadline, time.monotonic() + 10.0)
                                decision = await runtime.service.evaluate(
                                    req,
                                    deadline=eval_deadline,
                                    run_id=ctx.system.get("run_id", ""),
                                )
                                runtime.record_observation(
                                    req,
                                    decision,
                                    rule_result="unmatched",
                                    run_id=ctx.system.get("run_id", ""),
                                )
                                disp = result_disposition(
                                    decision=decision,
                                    policy=pol,
                                    rule_result="unmatched",
                                )
                            if disp == "success":
                                gap = _delivery_gap()
                                if gap is not None:
                                    return gap
                                _log_msg(
                                    f"步骤 [{node.id}] 语义辅助判断确认签到成功: {decision.selected}",
                                    level="INFO",
                                )
                                return StepOutcome(
                                    node_id=node.id,
                                    status=NodeStatus.SUCCESS,
                                    output_text=text,
                                    updates_last_output=True,
                                    details=details,
                                )
                            elif disp == "failure":
                                _log_msg(
                                    f"步骤 [{node.id}] 语义辅助判断确认任务失败: {decision.selected}",
                                    level="WARNING",
                                )
                                return StepOutcome(
                                    node_id=node.id,
                                    status=NodeStatus.FAILED,
                                    output_text=text,
                                    updates_last_output=True,
                                    details=details,
                                )
                            elif decision is not None:
                                err_reason = (
                                    f"，原因: {decision.error_message or decision.reason_code}"
                                    if (decision.error_message or decision.reason_code)
                                    else ""
                                )
                                _log_msg(
                                    f"步骤 [{node.id}] 语义辅助未能确认结果 (disp={disp}, selected={decision.selected}, conf={decision.confidence:.2f}{err_reason})",
                                    level="INFO",
                                )
                            else:
                                _log_msg(
                                    f"步骤 [{node.id}] JEV 语义服务未启用或未就绪，跳过语义辅助判断",
                                    level="DEBUG",
                                )
                        except Exception as sem_err:
                            _log_msg(f"语义辅助判断异常: {sem_err}", level="WARNING")
                    preview = " ".join(text.strip().split())[:100]
                    _log_msg(
                        f"收到机器人回复（但未匹配成功规则）：{preview}",
                        level="WARNING",
                    )
                    logger.debug(
                        f"WaitEventNode {node.id} 收到不匹配消息，继续等待: {text[:60]}"
                    )
                    continue

                # 9. 两者皆空时的原有行为：任意消息即成功
                _log_msg(f"收到机器人回复：\n{text}")
                _log_msg(f"步骤 [{node.id}] 执行完成（成功）")
                return StepOutcome(
                    node_id=node.id,
                    status=NodeStatus.SUCCESS,
                    output_text=text,
                    updates_last_output=True,
                    details=details,
                )
        finally:
            bus.unsubscribe(chat_id=chat_id, message_thread_id=thread_id, queue=queue)

    @staticmethod
    def _normalize_target(target_id: Optional[str]) -> str:
        if not target_id:
            return TERMINAL_COMPLETE_ID
        t = target_id.strip()
        if t.upper() in {"COMPLETE", "SUCCESS", "DONE", TERMINAL_COMPLETE_ID}:
            return TERMINAL_COMPLETE_ID
        if t.upper() in {"FAIL", "FAILED", "ERROR", TERMINAL_FAIL_ID}:
            return TERMINAL_FAIL_ID
        return t

    @staticmethod
    async def _sleep_before_retry(node: BaseFlowNode, attempt: int) -> None:
        policy = node.retry_policy
        delay = min(
            policy.backoff_seconds * (policy.backoff_multiplier ** (attempt - 1)),
            policy.max_backoff_seconds,
        )
        await asyncio.sleep(delay)

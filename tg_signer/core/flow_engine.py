# tg_signer/core/flow_engine.py
from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Pattern

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
    SubflowNode,
    TerminalPolicy,
    WaitEventNode,
    redact_sensitive_value,
)

logger = logging.getLogger("tg_signer.flow_engine")


class FlowLoopLimitExceededError(RuntimeError):
    """节点访问次数超出 loop_policy.max_visits 限制"""


class PulseFlowEngine:
    """下一代执行引擎 (PulseFlow v4)

    支持：
    - 有向图 (DAG / 拓扑循环) 调度
    - 运行时表达式条件判定与安全求值
    - 声明式变量提取与动态注入
    - 自适应指数退避重试 (Exponential Backoff)
    - 响应式事件驱动与水位线回补 (TelegramEventBus)
    - 子工作流 (SubflowNode) 嵌套调度
    - 生命周期事件监听器 (on_step_start / on_step_finish)
    - 全局错误处理器降级 (graph.error_handler_node_id)
    - 节点级条件守卫 (node.run_if / node.skip_if)
    - 断点恢复执行 (graph.resume_from_node_id)
    - 全局节点异步超时保护与连续失败熔断 (consecutive_failure_limit)
    - 敏感变量与凭据自动脱敏输出
    - 结构化执行性能与健康度指标度量 (metrics)
    """

    def __init__(self, event_bus: Optional[TelegramEventBus] = None):
        self._compiled_regexes: Dict[str, Pattern] = {}
        self._event_bus = event_bus

    def _compile_regex(self, pattern: str) -> Pattern:
        if pattern not in self._compiled_regexes:
            self._compiled_regexes[pattern] = re.compile(pattern)
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
    ) -> StepOutcome:
        """派发单节点多态执行"""
        if isinstance(node, ConditionNode):
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
        elif isinstance(node, WaitEventNode) and bus is not None:
            return await self._run_wait_event_node(node, ctx, bus)
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
                        outcome = await asyncio.wait_for(
                            self._execute_node(
                                node,
                                ctx,
                                executor,
                                bus,
                                on_step_start,
                                on_step_finish,
                            ),
                            timeout=timeout_sec,
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
        if not is_success and last_failure_error:
            res["error"] = last_failure_error
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

        for nid in executed_path:
            so = ctx.step_outcomes.get(nid)
            if so is not None:
                durations.append(so.duration_ms)
                if so.duration_ms > max_dur:
                    max_dur = so.duration_ms
                    slowest_node = {"node_id": nid, "duration_ms": so.duration_ms}
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
        for nid in executed_path:
            so = ctx.step_outcomes.get(nid)
            if so is not None:
                extracted = (
                    redact_sensitive_value(so.extracted_vars)
                    if redact_sensitive
                    else dict(so.extracted_vars)
                )
                trace.append(
                    {
                        "node_id": nid,
                        "status": so.status.value,
                        "duration_ms": so.duration_ms,
                        "output": so.output_text,
                        "output_text": so.output_text,
                        "extracted_vars": extracted,
                        "matched_terminal": so.matched_terminal,
                        "signal": so.signal.value,
                        "target_node_id": so.target_node_id,
                        "error": str(so.error) if so.error else None,
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
        self, node: WaitEventNode, ctx: ScopedFlowContext, bus: TelegramEventBus
    ) -> StepOutcome:
        chat_id = node.metadata.get("chat_id")
        thread_id = node.metadata.get("message_thread_id")
        min_msg_id = node.metadata.get("min_message_id")
        timeout = float(node.timeout_seconds or 25.0)

        queue = bus.subscribe(
            chat_id=chat_id,
            message_thread_id=thread_id,
            min_message_id=min_msg_id,
        )
        try:
            deadline = time.perf_counter() + timeout
            while True:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    return StepOutcome(
                        node_id=node.id,
                        status=NodeStatus.TIMEOUT,
                        output_text=f"WaitEventNode {node.id} timed out after {timeout}s",
                        updates_last_output=False,
                    )
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=remaining)
                except asyncio.TimeoutError:
                    return StepOutcome(
                        node_id=node.id,
                        status=NodeStatus.TIMEOUT,
                        output_text=f"WaitEventNode {node.id} timed out after {timeout}s",
                        updates_last_output=False,
                    )

                text = event.text or ""
                if not node.filter_patterns:
                    return StepOutcome(
                        node_id=node.id,
                        status=NodeStatus.SUCCESS,
                        output_text=text,
                        updates_last_output=True,
                    )

                for pattern in node.filter_patterns:
                    if self._compile_regex(pattern).search(text):
                        return StepOutcome(
                            node_id=node.id,
                            status=NodeStatus.SUCCESS,
                            output_text=text,
                            updates_last_output=True,
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

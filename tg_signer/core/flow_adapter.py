# tg_signer/core/flow_adapter.py
from __future__ import annotations

import asyncio
import inspect
import logging
import random
import re
from typing import Any, Optional

from tg_signer.config import (
    ClickKeyboardByTextAction,
    PluginAction,
    SendTextAction,
    SignChatV3,
)
from tg_signer.core.flow_compat import FlowCompatibilityBridge
from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_models import (
    BaseFlowNode,
    NodeStatus,
    StepOutcome,
)
from tg_signer.core.signer_runner import _copy_action_with
from tg_signer.core.template import render_template, render_template_recursive

logger = logging.getLogger("tg_signer.flow_adapter")


class TelegramNodeExecutor:
    """隔离旧系统副作用的动作执行适配器，支持跳过判定、动态模板渲染、延迟与容错重试闭环"""

    def __init__(
        self,
        runner: Any,
        chat: SignChatV3,
        graph: Any = None,
        state_lock: Optional[asyncio.Lock] = None,
    ):
        self.runner = runner
        self.chat = chat
        self.compat = FlowCompatibilityBridge(runner, chat, graph)
        self._runner_state_lock = (
            state_lock if state_lock is not None else asyncio.Lock()
        )

    def _log(self, msg: str, level: str = "INFO") -> None:
        """同时向 runner 日志流（供前端实时查看）和系统标准日志输出"""
        if hasattr(self.runner, "log"):
            try:
                self.runner.log(msg, level=level)
            except Exception:
                pass
        log_fn = getattr(logger, level.lower(), logger.info)
        log_fn(msg)

    @staticmethod
    def _extract_flood_wait_seconds(exc: Exception) -> Optional[int]:
        """提取 FloodWait 异常中的等待秒数"""
        for attr in ("value", "x", "seconds"):
            val = getattr(exc, attr, None)
            if isinstance(val, (int, float)) and val > 0:
                return int(val)
        msg = str(exc)
        exc_type = type(exc).__name__
        m = re.search(r"FLOOD_WAIT_?(\d+)", f"{exc_type} msg", re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except (ValueError, TypeError):
                pass
        m2 = re.search(r"wait(?:ing)?(?:\s+of)?\s+(\d+)\s+seconds", msg, re.IGNORECASE)
        if m2:
            try:
                return int(m2.group(1))
            except (ValueError, TypeError):
                pass
        return None

    @classmethod
    def materialize_action(cls, node: BaseFlowNode) -> Any:
        """从 ActionNode 中材质化还原标准 SignAction 实例，确保 wait_for 调度兼容。"""
        raw_act = node.metadata.get("raw_action")
        if raw_act is not None and not isinstance(raw_act, dict):
            return raw_act

        from tg_signer.config import (
            ACTION_MODEL_MAP,
            SupportAction,
        )

        act_type_str = str(getattr(node, "action_type", "") or "SEND_TEXT").upper()
        support_act = None
        for member in SupportAction:
            if member.name == act_type_str or str(member.value) == act_type_str:
                support_act = member
                break
        if support_act is None and act_type_str in {"PLUGIN", "CUSTOM_PLUGIN"}:
            support_act = SupportAction.CUSTOM_PLUGIN

        params = dict(getattr(node, "params", {}) or {})
        if isinstance(raw_act, dict):
            params.update(raw_act)

        if (
            hasattr(node, "terminal_policy")
            and getattr(node.terminal_policy, "value", "") == "stop_flow"
        ):
            params.setdefault("stop_flow_on_terminal", True)
        if hasattr(node, "skip_if") and node.skip_if:
            params.setdefault("skip_if", node.skip_if)

        if support_act and support_act in ACTION_MODEL_MAP:
            target_cls = ACTION_MODEL_MAP[support_act]
            try:
                params_copy = dict(params)
                params_copy.setdefault("action", support_act)
                inst = target_cls(**params_copy)
                node.metadata["raw_action"] = inst
                return inst
            except Exception:
                pass

        return raw_act or params

    @staticmethod
    def _runner_supports_timeout(fn: Any) -> bool:
        """检测 runner.wait_for（包括 mock 对象的 side_effect）是否支持 timeout 参数"""
        target = getattr(fn, "side_effect", None) or fn
        try:
            sig = inspect.signature(target)
            params = sig.parameters
            return "timeout" in params or any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
            )
        except Exception:
            return True

    async def _runner_wait_for(
        self,
        chat: Any,
        action: Any,
        step_timeout: Optional[float] = None,
        next_action: Any = None,
    ) -> Any:
        wait_for_fn = getattr(self.runner, "wait_for", None)
        if step_timeout is not None and self._runner_supports_timeout(wait_for_fn):
            return await self.runner.wait_for(
                chat,
                action,
                timeout=step_timeout,
                next_action=next_action,
            )
        return await self.runner.wait_for(
            chat,
            action,
            next_action=next_action,
        )

    async def __call__(
        self, node: BaseFlowNode, context: ScopedFlowContext
    ) -> StepOutcome:
        # The legacy runner and Pyrogram client are stateful. Keep the complete
        # action transaction serialized even when graph branches are concurrent.
        await self._runner_state_lock.acquire()
        try:
            return await self._call_unlocked(node, context)
        finally:
            if self._runner_state_lock.locked():
                self._runner_state_lock.release()

    async def _call_unlocked(
        self, node: BaseFlowNode, context: ScopedFlowContext
    ) -> StepOutcome:
        raw_act = self.materialize_action(node)

        # 1. 检查 skip_if_matched 条件跳过
        skip_pat = getattr(raw_act, "skip_if_matched", None)
        if isinstance(raw_act, dict) and skip_pat is None:
            skip_pat = raw_act.get("skip_if_matched")
        if skip_pat:
            skip_pat_str = str(skip_pat).strip()
            match_src = self.compat.skip_match_source(context)
            matched = False
            if skip_pat_str and match_src:
                if skip_pat_str in match_src:
                    matched = True
                else:
                    try:
                        if re.search(skip_pat_str, match_src, re.IGNORECASE):
                            matched = True
                    except re.error:
                        pass
            if matched:
                self._log(
                    f"步骤 {node.id} 满足跳过条件（skip_if_matched='{skip_pat_str}'），跳过此步骤"
                )
                return StepOutcome(
                    node_id=node.id,
                    status=NodeStatus.SKIPPED,
                    output_text=f"Skipped by skip_if_matched: {skip_pat_str}",
                    # 跳过诊断文本属于内部控制信息，不应覆盖后续动作可见的 Telegram 输出。
                    updates_last_output=False,
                )

        # 2. 构建模板上下文并渲染动态变量
        me_user = getattr(self.runner, "me", None)
        tmpl_ctx = self.compat.build_template_context(
            context,
            me_user=me_user,
            account_name=getattr(self.runner, "_account", ""),
        )

        exec_action = raw_act
        if isinstance(raw_act, SendTextAction):
            rendered_text = render_template(raw_act.text, tmpl_ctx)
            if rendered_text != raw_act.text:
                exec_action = _copy_action_with(raw_act, text=rendered_text)
        elif isinstance(raw_act, ClickKeyboardByTextAction):
            rendered_text = render_template(raw_act.text, tmpl_ctx)
            if rendered_text != raw_act.text:
                exec_action = _copy_action_with(raw_act, text=rendered_text)
        elif isinstance(raw_act, PluginAction):
            rendered_params = render_template_recursive(raw_act.params, tmpl_ctx)
            exec_action = _copy_action_with(raw_act, params=rendered_params)
        elif hasattr(raw_act, "ai_prompt") and getattr(raw_act, "ai_prompt", None):
            rendered_prompt = render_template(raw_act.ai_prompt, tmpl_ctx)
            if rendered_prompt != raw_act.ai_prompt:
                exec_action = _copy_action_with(raw_act, ai_prompt=rendered_prompt)
        elif isinstance(raw_act, dict):
            exec_action = render_template_recursive(raw_act, tmpl_ctx)

        # 3. 处理执行延迟 delay（支持固定秒数、随机区间 "1-3" 及 chat.action_interval 兜底）
        action_delay = 0.0
        fallback_delay = 0.0
        if getattr(self.chat, "action_interval", None) is not None:
            try:
                fallback_delay = float(self.chat.action_interval or 0.0)
            except (ValueError, TypeError):
                fallback_delay = 0.0

        if hasattr(self.runner, "_resolve_action_delay"):
            try:
                res_delay = self.runner._resolve_action_delay(
                    exec_action, fallback_delay
                )
                if isinstance(res_delay, (int, float)):
                    action_delay = float(res_delay)
            except TypeError:
                try:
                    res_delay = self.runner._resolve_action_delay(exec_action)
                    if isinstance(res_delay, (int, float)):
                        action_delay = float(res_delay)
                except Exception:
                    action_delay = 0.0
            except Exception:
                action_delay = 0.0
        elif getattr(exec_action, "delay", None) is not None:
            raw_d = str(exec_action.delay).strip()
            if "-" in raw_d:
                try:
                    p1, p2 = raw_d.split("-", 1)
                    action_delay = random.uniform(float(p1), float(p2))
                except Exception:
                    action_delay = 0.0
            else:
                try:
                    action_delay = float(raw_d or 0.0)
                except (ValueError, TypeError):
                    action_delay = 0.0
        elif fallback_delay > 0:
            action_delay = fallback_delay

        if action_delay > 0:
            self._log(f"步骤 {node.id} 将在 {action_delay:g} 秒后执行")
            await asyncio.sleep(action_delay)

        # 4. 严格重置并隔离旧 context 污染
        self.compat.reset_before_action()

        cont_on_error = getattr(exec_action, "continue_on_error", False)
        if isinstance(exec_action, dict) and not cont_on_error:
            cont_on_error = exec_action.get("continue_on_error", False)

        # 5. 调用 runner.wait_for 执行动作
        action_desc = (
            getattr(exec_action, "description", None)
            or getattr(node, "name", "")
            or f"Action-{node.id}"
        )
        self._log(f"步骤 [{node.id}] 开始执行：{action_desc}")

        # 同步 runner 当前动作上下文，保证消息标记去重与进度展示不脱钩
        total_nodes = (
            len(self.compat.graph.nodes)
            if (
                self.compat
                and self.compat.graph
                and getattr(self.compat.graph, "nodes", None)
            )
            else 1
        )
        step_idx = 1
        if node.id.startswith("step_") and node.id[5:].isdigit():
            step_idx = int(node.id[5:]) + 1
        elif node.id.isdigit():
            step_idx = int(node.id)

        self.compat.set_current_action_context(step_idx, total_nodes, exec_action)

        try:
            next_action = self.compat.resolve_next_action(node)
            step_timeout = getattr(node, "timeout_seconds", None)
            res = await self._runner_wait_for(
                self.chat,
                exec_action,
                step_timeout=step_timeout,
                next_action=next_action,
            )
            if res is not False:
                self.compat.mark_side_effect_started()
                msg_id = getattr(res, "id", None)
                if msg_id:
                    context.system["last_sent_message_id"] = msg_id
                    context.system["last_message_id"] = msg_id
                import time as _t

                context.system["last_action_finished_at"] = _t.time()
            matched_term = self.compat.consume_stop_signal()
            output_text = self.compat.output_text(res=res, action=exec_action)

            if res is False:
                self._log(f"步骤 [{node.id}] 执行未达预期/失败", level="WARNING")
                if cont_on_error:
                    self._log(
                        f"步骤 {node.id} 执行返回失败，已配置容错继续（continue_on_error）",
                        level="WARNING",
                    )
                    return StepOutcome(
                        node_id=node.id,
                        status=NodeStatus.SKIPPED,
                        matched_terminal=matched_term,
                        output_text=output_text or "Failed but continue_on_error",
                    )
                return StepOutcome(
                    node_id=node.id,
                    status=NodeStatus.FAILED,
                    matched_terminal=matched_term,
                    output_text=output_text,
                )

            self._log(f"步骤 [{node.id}] 执行完成（成功）", level="INFO")
            return StepOutcome(
                node_id=node.id,
                status=NodeStatus.SUCCESS,
                matched_terminal=matched_term,
                output_text=output_text,
            )
        except Exception as exc:
            flood_sec = self._extract_flood_wait_seconds(exc)
            if flood_sec is not None and flood_sec <= 60:
                self._log(
                    f"步骤 {node.id} 触发 Telegram FloodWait ({flood_sec}s)，自适应休眠后重试...",
                    level="WARNING",
                )
                await asyncio.sleep(flood_sec + 1)
                try:
                    res = await self._runner_wait_for(
                        self.chat,
                        exec_action,
                        step_timeout=step_timeout,
                        next_action=next_action,
                    )
                    if res is not False:
                        self.compat.mark_side_effect_started()
                    matched_term = self.compat.consume_stop_signal()
                    output_text = self.compat.output_text(res=res, action=exec_action)
                    if res is not False:
                        self._log(f"步骤 {node.id} FloodWait 休眠后重试执行成功")
                        return StepOutcome(
                            node_id=node.id,
                            status=NodeStatus.SUCCESS,
                            matched_terminal=matched_term,
                            output_text=output_text,
                        )
                except Exception as retry_exc:
                    exc = retry_exc

            self._log(f"步骤 {node.id} 执行抛出异常: {exc}", level="ERROR")
            if cont_on_error:
                self._log(
                    f"步骤 {node.id} 出现错误，已配置容错继续（continue_on_error）: {exc}",
                    level="WARNING",
                )
                return StepOutcome(
                    node_id=node.id,
                    status=NodeStatus.SKIPPED,
                    error=exc,
                    output_text=str(exc),
                    updates_last_output=False,
                )
            # 未配置 continue_on_error 的异常向上抛出，使 PulseFlowEngine 的 RetryPolicy 重试机制生效
            raise
        finally:
            self.compat.clear_current_action_context()

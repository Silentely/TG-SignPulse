# tg_signer/core/flow_adapter.py
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from tg_signer.config import (
    ClickKeyboardByTextAction,
    PluginAction,
    SendTextAction,
    SignChatV3,
)
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

    def __init__(self, runner: Any, chat: SignChatV3, graph: Any = None):
        self.runner = runner
        self.chat = chat
        self.graph = graph

    def _log(self, msg: str, level: str = "INFO") -> None:
        """同时向 runner 日志流（供前端实时查看）和系统标准日志输出"""
        if hasattr(self.runner, "log"):
            try:
                self.runner.log(msg, level=level)
            except Exception:
                pass
        log_fn = getattr(logger, level.lower(), logger.info)
        log_fn(msg)

    async def __call__(
        self, node: BaseFlowNode, context: ScopedFlowContext
    ) -> StepOutcome:
        raw_act = node.metadata.get("raw_action")
        if raw_act is None:
            raw_act = node.params

        runner_ctx = getattr(self.runner, "context", None)

        # 1. 检查 skip_if_matched 条件跳过
        skip_pat = getattr(raw_act, "skip_if_matched", None)
        if skip_pat:
            skip_pat_str = str(skip_pat).strip()
            legacy_last_out = (
                getattr(runner_ctx, "last_output", "") if runner_ctx else ""
            )
            legacy_last_recv = (
                getattr(runner_ctx, "last_received_text", "") if runner_ctx else ""
            )
            match_src = str(
                context.last_output
                or (isinstance(legacy_last_out, str) and legacy_last_out)
                or (isinstance(legacy_last_recv, str) and legacy_last_recv)
                or ""
            )
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
                )

        # 2. 构建模板上下文并渲染动态变量
        me_user = getattr(self.runner, "me", None)
        step_outs = getattr(runner_ctx, "step_outputs", None) if runner_ctx else None
        legacy_last_recv = (
            getattr(runner_ctx, "last_received_text", "") if runner_ctx else ""
        )
        if not isinstance(legacy_last_recv, str):
            legacy_last_recv = ""

        scope_dict = context.build_scope_dict()
        scoped_steps = scope_dict.get("steps", {})
        if not isinstance(step_outs, dict) or not step_outs:
            step_outs = scoped_steps if isinstance(scoped_steps, dict) else {}
        account_dict = dict(scope_dict.get("account") or {})
        if me_user:
            if getattr(me_user, "phone_number", None):
                account_dict["phone"] = str(me_user.phone_number)
            if getattr(me_user, "username", None):
                account_dict["username"] = str(me_user.username)
            if getattr(me_user, "first_name", None):
                account_dict["first_name"] = str(me_user.first_name)
        if getattr(self.runner, "_account", None):
            account_dict["name"] = str(self.runner._account)

        tmpl_ctx = {
            **scope_dict,
            "account": account_dict,
            "chat": {
                "id": self.chat.chat_id,
                "name": getattr(self.chat, "name", ""),
            },
            "step": step_outs,
            "prev_output": context.last_output or "",
            "prev": {
                "output": context.last_output or "",
            },
            "last_message": legacy_last_recv,
        }

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

        # 3. 处理执行延迟 delay
        action_delay = 0.0
        if hasattr(self.runner, "_resolve_action_delay"):
            try:
                res_delay = self.runner._resolve_action_delay(exec_action)
                if isinstance(res_delay, (int, float)):
                    action_delay = float(res_delay)
            except Exception:
                action_delay = 0.0
        elif getattr(exec_action, "delay", None) is not None:
            try:
                action_delay = float(exec_action.delay or 0.0)
            except (ValueError, TypeError):
                action_delay = 0.0

        if action_delay > 0:
            self._log(f"步骤 {node.id} 将在 {action_delay:g} 秒后执行")
            await asyncio.sleep(action_delay)

        # 4. 严格重置并隔离旧 context 污染
        if runner_ctx is not None:
            try:
                runner_ctx.stop_after_current_action = False
            except Exception:
                pass

        cont_on_error = getattr(exec_action, "continue_on_error", False)

        # 5. 调用 runner.wait_for 执行动作
        try:
            next_action = None
            next_node_id = getattr(node, "next_node_id", None)
            if self.graph is not None and next_node_id:
                next_node = self.graph.nodes.get(next_node_id)
                if next_node is not None:
                    next_action = next_node.metadata.get("raw_action")
            res = await self.runner.wait_for(
                self.chat, exec_action, next_action=next_action
            )
            matched_term = False
            if runner_ctx and getattr(runner_ctx, "stop_after_current_action", False):
                matched_term = True
                runner_ctx.stop_after_current_action = False  # 物理清零，阻止扩散

            legacy_last_out = (
                getattr(runner_ctx, "last_output", "") if runner_ctx else ""
            )
            output_text = str(
                legacy_last_out if isinstance(legacy_last_out, str) else ""
            )

            if res is False:
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

            return StepOutcome(
                node_id=node.id,
                status=NodeStatus.SUCCESS,
                matched_terminal=matched_term,
                output_text=output_text,
            )
        except Exception as exc:
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
                )
            # 未配置 continue_on_error 的异常向上抛出，使 PulseFlowEngine 的 RetryPolicy 重试机制生效
            raise

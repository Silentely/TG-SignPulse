# tg_signer/core/flow_adapter.py
from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import Any

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

    def __init__(self, runner: Any, chat: SignChatV3, graph: Any = None):
        self.runner = runner
        self.chat = chat
        self.compat = FlowCompatibilityBridge(runner, chat, graph)

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

        # 1. 检查 skip_if_matched 条件跳过
        skip_pat = getattr(raw_act, "skip_if_matched", None)
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

        # 5. 调用 runner.wait_for 执行动作
        action_desc = (
            getattr(exec_action, "description", None)
            or getattr(node, "name", "")
            or f"Action-{node.id}"
        )
        self._log(f"步骤 [{node.id}] 开始执行：{action_desc}")

        try:
            next_action = self.compat.resolve_next_action(node)
            res = await self.runner.wait_for(
                self.chat, exec_action, next_action=next_action
            )
            matched_term = self.compat.consume_matched_terminal()
            output_text = self.compat.output_text()

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

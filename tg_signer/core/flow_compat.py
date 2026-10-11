"""PulseFlow 与旧版 UserSigner context 的显式兼容桥。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from tg_signer.config import SignChatV3
from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_models import BaseFlowNode, ExecutionGraph


class FlowCompatibilityBridge:
    """把 legacy runner 状态限制在一个可测试、可替换的边界内。"""

    def __init__(
        self,
        runner: Any,
        chat: SignChatV3,
        graph: Optional[ExecutionGraph] = None,
    ):
        self.runner = runner
        self.chat = chat
        self.graph = graph

    @property
    def runner_context(self) -> Any:
        return getattr(self.runner, "context", None)

    def skip_match_source(self, context: ScopedFlowContext) -> str:
        """从 scoped 上下文、实时消息缓冲与终态原因汇总完整匹配源，杜绝内部漏跟 Telegram 更新。"""
        sources = []
        if context.last_output:
            sources.append(str(context.last_output))

        runner_ctx = self.runner_context
        if runner_ctx is not None:
            last_received = getattr(runner_ctx, "last_received_text", "")
            if isinstance(last_received, str) and last_received:
                sources.append(last_received)

            stop_reason = getattr(runner_ctx, "stop_reason", "")
            if isinstance(stop_reason, str) and stop_reason:
                sources.append(stop_reason)

            last_cb = getattr(runner_ctx, "last_callback_answer", "")
            if isinstance(last_cb, str) and last_cb:
                sources.append(last_cb)

            if hasattr(runner_ctx, "chat_messages"):
                chat_msgs = runner_ctx.chat_messages.get(self.chat.chat_id) or {}
                for msg in reversed(list(chat_msgs.values())):
                    if msg is not None:
                        txt = getattr(msg, "text", None) or getattr(
                            msg, "caption", None
                        )
                        if txt:
                            sources.append(str(txt))
                            break

        return "\n".join(sources)

    def build_template_context(
        self,
        context: ScopedFlowContext,
        me_user: Any = None,
        account_name: str = "",
    ) -> Dict[str, Any]:
        """从 scoped context 生成新旧模板变量的统一视图。"""
        scope_dict = context.build_scope_dict()
        account_dict = dict(scope_dict.get("account") or {})
        if me_user:
            for key in ("phone", "username", "first_name"):
                attr = "phone_number" if key == "phone" else key
                value = getattr(me_user, attr, None)
                if value:
                    account_dict[key] = str(value)
        if account_name:
            account_dict["name"] = str(account_name)

        last_received = getattr(self.runner_context, "last_received_text", "")
        if not isinstance(last_received, str):
            last_received = ""
        scoped_steps = scope_dict.get("steps", {})
        steps = dict(scoped_steps) if isinstance(scoped_steps, dict) else {}
        # 旧版 actions/workflow 模板同时支持 step_id 与 1-based 数字键。
        for index, step_id in enumerate(context.step_outcomes, start=1):
            step_data = steps.get(step_id)
            if step_data is not None:
                steps.setdefault(index, step_data)
                steps.setdefault(str(index), step_data)
        return {
            **scope_dict,
            "account": account_dict,
            "chat": {
                "id": self.chat.chat_id,
                "name": getattr(self.chat, "name", ""),
            },
            # 同时支持 steps 与 step 别名访问
            "steps": steps,
            "step": steps,
            "prev_output": context.last_output or "",
            "prev": {"output": context.last_output or ""},
            "last_message": last_received,
        }

    def reset_before_action(self) -> None:
        """清理一次性终态标记，避免上一步状态扩散到当前动作。"""
        runner_context = self.runner_context
        if runner_context is not None:
            try:
                runner_context.stop_after_current_action = False
            except Exception:
                pass

    def consume_matched_terminal(self) -> bool:
        """读取并消费旧 runner 的终态标记，只允许消费一次。"""
        runner_context = self.runner_context
        if runner_context is None:
            return False
        try:
            matched = bool(getattr(runner_context, "stop_after_current_action", False))
            if matched:
                runner_context.stop_after_current_action = False
            return matched
        except Exception:
            return False

    def output_text(self, res: Any = None, action: Any = None) -> str:
        """多重来源回填 Telegram 输出文本，确保动作响应不丢失、状态跟得上更新。"""
        runner_ctx = self.runner_context

        # 1. 优先读取旧 runner context 中显式设置的 last_output
        output = getattr(runner_ctx, "last_output", "")
        if isinstance(output, str) and output:
            return output

        # 2. 从当前会话收到的最新 Telegram 消息提取文本
        if runner_ctx is not None and hasattr(runner_ctx, "chat_messages"):
            chat_msgs = runner_ctx.chat_messages.get(self.chat.chat_id) or {}
            for msg in reversed(list(chat_msgs.values())):
                if msg is not None:
                    txt = getattr(msg, "text", None) or getattr(msg, "caption", None)
                    if txt:
                        out_str = str(txt)
                        runner_ctx.last_output = out_str
                        return out_str

        # 3. 从终态命中原因或回调通知文本提取
        if runner_ctx is not None:
            stop_reason = getattr(runner_ctx, "stop_reason", "")
            if isinstance(stop_reason, str) and stop_reason:
                runner_ctx.last_output = stop_reason
                return stop_reason

            last_cb = getattr(runner_ctx, "last_callback_answer", "")
            if isinstance(last_cb, str) and last_cb:
                runner_ctx.last_output = last_cb
                return last_cb

            last_recv = getattr(runner_ctx, "last_received_text", "")
            if isinstance(last_recv, str) and last_recv:
                runner_ctx.last_output = last_recv
                return last_recv

        # 4. 从动作返回值提取（如插件返回、计算结果或 Message 对象）
        if isinstance(res, str) and res:
            if runner_ctx is not None:
                runner_ctx.last_output = res
            return res
        if hasattr(res, "text") and getattr(res, "text", None):
            txt = str(res.text)
            if runner_ctx is not None:
                runner_ctx.last_output = txt
            return txt
        if hasattr(res, "caption") and getattr(res, "caption", None):
            txt = str(res.caption)
            if runner_ctx is not None:
                runner_ctx.last_output = txt
            return txt

        return ""

    def resolve_next_action(self, node: BaseFlowNode) -> Any:
        if self.graph is None or not node.next_node_id:
            return None
        next_node = self.graph.nodes.get(node.next_node_id)
        if next_node is None:
            return None
        return next_node.metadata.get("raw_action")

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

    # ---------------------------------------------------------
    # 1. 快照读取操作 (Snapshot Reading)
    # ---------------------------------------------------------

    def get_last_received_text(self) -> str:
        """获取 runner context 中记录的最新接收文本快照。"""
        ctx = self.runner_context
        if ctx is None:
            return ""
        txt = getattr(ctx, "last_received_text", "")
        return str(txt) if isinstance(txt, str) else ""

    def get_chat_messages(self, chat_id: Optional[int] = None) -> Dict[int, Any]:
        """获取指定会话的消息缓冲字典快照（只读视图/浅拷贝）。"""
        ctx = self.runner_context
        if ctx is None or not hasattr(ctx, "chat_messages"):
            return {}
        target_cid = chat_id if chat_id is not None else getattr(self.chat, "chat_id", None)
        chat_dict = ctx.chat_messages
        if not isinstance(chat_dict, dict):
            return {}
        msgs = chat_dict.get(target_cid) or {}
        if isinstance(msgs, dict):
            return dict(msgs)
        return {}

    def get_stop_reason(self) -> str:
        """获取终态命中原因文本快照。"""
        ctx = self.runner_context
        if ctx is None:
            return ""
        val = getattr(ctx, "stop_reason", "")
        return str(val) if isinstance(val, str) else ""

    def get_last_callback_answer(self) -> str:
        """获取最后一次回调通知文本快照。"""
        ctx = self.runner_context
        if ctx is None:
            return ""
        val = getattr(ctx, "last_callback_answer", "")
        return str(val) if isinstance(val, str) else ""

    def get_last_output(self) -> str:
        """获取 runner context 中显式记录的 last_output。"""
        ctx = self.runner_context
        if ctx is None:
            return ""
        val = getattr(ctx, "last_output", "")
        return str(val) if isinstance(val, str) else ""

    # ---------------------------------------------------------
    # 2. 终态信号提交与消费 (Terminal Outcome Operations)
    # ---------------------------------------------------------

    def check_terminal_stop(self) -> bool:
        """只读检查当前是否已触发终态停止标记（不进行消费/重置）。"""
        ctx = self.runner_context
        if ctx is None:
            return False
        return getattr(ctx, "stop_after_current_action", False) is True

    def consume_stop_signal(self) -> bool:
        """读取并消费旧 runner 的终态信号，消费后自动重置为 False。只允许消费一次。"""
        ctx = self.runner_context
        if ctx is None:
            return False
        try:
            matched = getattr(ctx, "stop_after_current_action", False) is True
            if matched:
                ctx.stop_after_current_action = False
            return matched
        except Exception:
            return False

    def consume_matched_terminal(self) -> bool:
        """向后兼容别名：读取并消费旧 runner 的终态标记。"""
        return self.consume_stop_signal()

    # ---------------------------------------------------------
    # 3. 输出提交与副作用标记 (Committing Output & Side Effects)
    # ---------------------------------------------------------

    def mark_side_effect_started(self) -> None:
        """标记当前动作已产生持久化或外部网络副作用。"""
        ctx = self.runner_context
        if ctx is not None:
            try:
                ctx.pulseflow_side_effect_started = True
            except Exception:
                pass

    def set_last_output(self, output: str) -> None:
        """向旧 runner context 提交本次动作产生的输出文本。"""
        ctx = self.runner_context
        if ctx is not None:
            try:
                ctx.last_output = output
                ctx.last_received_text = output
            except Exception:
                pass

    # ---------------------------------------------------------
    # 4. 动作上下文管理 (Managing Action Context)
    # ---------------------------------------------------------

    def set_current_action_context(
        self, step_idx: int, total_nodes: int, action: Any
    ) -> None:
        """设置旧 runner 的动作执行上下文（去重、进度等）。"""
        if hasattr(self.runner, "_set_current_action_context"):
            try:
                self.runner._set_current_action_context(
                    step_idx, total_nodes, action
                )
            except Exception:
                pass

    def clear_current_action_context(self) -> None:
        """清理旧 runner 的当前动作上下文。"""
        if hasattr(self.runner, "_clear_current_action_context"):
            try:
                self.runner._clear_current_action_context()
            except Exception:
                pass

    def reset_before_action(self) -> None:
        """重置上一个动作的旧状态残留。"""
        ctx = self.runner_context
        if ctx is not None:
            try:
                ctx.last_output = ""
                ctx.stop_after_current_action = False
                ctx.stop_reason = ""
            except Exception:
                pass

    # ---------------------------------------------------------
    # 5. 辅助方法 (Helpers)
    # ---------------------------------------------------------

    def resolve_next_action(self, node: BaseFlowNode) -> Any:
        if self.graph is None or not getattr(node, "next_node_id", None):
            return None
        next_node = self.graph.nodes.get(node.next_node_id)
        if next_node is None:
            return None
        return next_node.metadata.get("raw_action")

    def output_text(self, res: Any = None, action: Any = None) -> str:
        """多重来源回填 Telegram 输出文本，确保动作响应不丢失、状态跟得上更新。"""
        # 1. 优先读取旧 runner context 中显式设置的 last_output
        output = self.get_last_output()
        if output:
            return output

        # 2. 从当前会话收到的最新 Telegram 消息提取文本
        chat_msgs = self.get_chat_messages(getattr(self.chat, "chat_id", None))
        for msg in reversed(list(chat_msgs.values())):
            if msg is not None:
                txt = getattr(msg, "text", None) or getattr(msg, "caption", None)
                if txt and isinstance(txt, str):
                    self.set_last_output(txt)
                    return txt

        # 3. 从终态命中原因或回调通知文本提取
        stop_reason = self.get_stop_reason()
        if stop_reason:
            self.set_last_output(stop_reason)
            return stop_reason

        last_cb = self.get_last_callback_answer()
        if last_cb:
            self.set_last_output(last_cb)
            return last_cb

        last_recv = self.get_last_received_text()
        if last_recv:
            self.set_last_output(last_recv)
            return last_recv

        # 4. 从动作返回值提取（如插件返回、计算结果或 Message 对象）
        if isinstance(res, str) and res:
            self.set_last_output(res)
            return res
        if hasattr(res, "text") and getattr(res, "text", None) and isinstance(res.text, str):
            txt = res.text
            self.set_last_output(txt)
            return txt
        if hasattr(res, "caption") and getattr(res, "caption", None) and isinstance(res.caption, str):
            txt = res.caption
            self.set_last_output(txt)
            return txt

        return ""

    def skip_match_source(self, context: ScopedFlowContext) -> str:
        parts = []
        if context.last_output:
            parts.append(str(context.last_output))
        ctx = self.runner_context
        if ctx is not None:
            lr = getattr(ctx, "last_received_text", "")
            if lr and isinstance(lr, str):
                parts.append(lr)
            msgs = self.get_chat_messages()
            if msgs:
                try:
                    recent = sorted(
                        msgs.values(),
                        key=lambda m: getattr(m, "id", 0) or 0,
                        reverse=True,
                    )[:5]
                    for m in recent:
                        t = getattr(m, "text", "")
                        if t and isinstance(t, str):
                            parts.append(t)
                except Exception:
                    pass
        return " ".join(parts)

    def build_template_context(
        self,
        flow_context: ScopedFlowContext,
        me_user: Any = None,
        account_name: str = "",
    ) -> Dict[str, Any]:
        scope_dict = (
            flow_context.build_scope_dict()
            if hasattr(flow_context, "build_scope_dict")
            else {}
        )
        account_dict = dict(scope_dict.get("account") or {})
        if me_user:
            for key in ("phone", "username", "first_name"):
                attr = "phone_number" if key == "phone" else key
                value = getattr(me_user, attr, None)
                if value:
                    account_dict[key] = str(value)
        if account_name:
            account_dict["name"] = str(account_name)

        last_received = self.get_last_received_text()
        steps = dict(scope_dict.get("steps") or {})
        step_aliases = dict(steps)
        for idx, (_k, v) in enumerate(steps.items(), start=1):
            step_aliases[idx] = v
            step_aliases[str(idx)] = v

        result = {
            **scope_dict,
            "account": account_dict,
            "chat": {
                "id": getattr(self.chat, "chat_id", None),
                "name": getattr(self.chat, "name", ""),
            },
            # step 是 legacy 别名，数据源仍然只有 scoped steps。
            "step": step_aliases,
            "prev_output": flow_context.last_output or "",
            "prev": {"output": flow_context.last_output or ""},
            "last_message": last_received,
        }
        user_ctx = result.setdefault("user", {})
        if me_user:
            user_ctx.setdefault("id", getattr(me_user, "id", ""))
            user_ctx.setdefault("username", getattr(me_user, "username", ""))
            user_ctx.setdefault("first_name", getattr(me_user, "first_name", ""))
            user_ctx.setdefault("last_name", getattr(me_user, "last_name", ""))
        user_ctx.setdefault("account", account_name)

        ctx = self.runner_context
        if ctx is not None:
            res_ctx = result.setdefault("res", {})
            cb = getattr(ctx, "last_callback_answer", "")
            if cb and isinstance(cb, str):
                res_ctx.setdefault("callback_answer", cb)
            sr = getattr(ctx, "stop_reason", "")
            if sr and isinstance(sr, str):
                res_ctx.setdefault("stop_reason", sr)
            if not flow_context.last_output:
                lo = getattr(ctx, "last_output", "")
                if lo and isinstance(lo, str):
                    res_ctx["output"] = lo
                    result.setdefault("prev", {})["output"] = lo

        return result

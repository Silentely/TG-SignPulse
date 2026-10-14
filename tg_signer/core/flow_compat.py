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
        return bool(getattr(ctx, "stop_after_current_action", False))

    def consume_stop_signal(self) -> bool:
        """读取并消费旧 runner 的终态信号，消费后自动重置为 False。只允许消费一次。"""
        ctx = self.runner_context
        if ctx is None:
            return False
        try:
            matched = bool(getattr(ctx, "stop_after_current_action", False))
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
        """向 runner context 提交最后执行输出。"""
        ctx = self.runner_context
        if ctx is not None:
            try:
                ctx.last_output = str(output)
            except Exception:
                pass

    # ---------------------------------------------------------
    # 4. 动作上下文管理 (Action Context Governance)
    # ---------------------------------------------------------

    def set_current_action_context(
        self, step_idx: int, total_nodes: int, action: Any
    ) -> None:
        """同步 runner 当前动作上下文，保证日志、进度与消息去重不脱钩。"""
        if hasattr(self.runner, "_set_current_action_context"):
            try:
                self.runner._set_current_action_context(step_idx, total_nodes, action)
            except Exception:
                pass

    def clear_current_action_context(self) -> None:
        """清理 runner 当前动作上下文。"""
        if hasattr(self.runner, "_clear_current_action_context"):
            try:
                self.runner._clear_current_action_context()
            except Exception:
                pass

    # ---------------------------------------------------------
    # 5. 流程辅助逻辑 (Flow Helpers)
    # ---------------------------------------------------------

    def skip_match_source(self, context: ScopedFlowContext) -> str:
        """从 scoped 上下文、实时消息缓冲与终态原因汇总完整匹配源，杜绝内部漏跟 Telegram 更新。"""
        sources = []
        if context.last_output:
            sources.append(str(context.last_output))

        last_received = self.get_last_received_text()
        if last_received:
            sources.append(last_received)

        stop_reason = self.get_stop_reason()
        if stop_reason:
            sources.append(stop_reason)

        last_cb = self.get_last_callback_answer()
        if last_cb:
            sources.append(last_cb)

        chat_msgs = self.get_chat_messages(getattr(self.chat, "chat_id", None))
        for msg in reversed(list(chat_msgs.values())):
            if msg is not None:
                txt = getattr(msg, "text", None) or getattr(msg, "caption", None)
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

        last_received = self.get_last_received_text()
        scoped_steps = scope_dict.get("steps", {})
        steps = dict(scoped_steps) if isinstance(scoped_steps, dict) else {}
        # 旧版 actions/workflow 模板同时支持 step_id 与 1-based 数字键。
        for index, step_id in enumerate(context.step_outcomes, start=1):
            step_data = steps.get(step_id)
            if step_data is not None:
                steps.setdefault(index, step_data)
                steps.setdefault(str(index), step_data)

        curr_output = (
            context.last_output or self.get_last_output() or ""
        )
        return {
            **scope_dict,
            "account": account_dict,
            "chat": {
                "id": getattr(self.chat, "chat_id", None),
                "name": getattr(self.chat, "name", ""),
            },
            # 同时支持 steps 与 step 别名访问
            "steps": steps,
            "step": steps,
            "prev_output": curr_output,
            "prev": {"output": curr_output},
            "last_message": last_received,
        }

    def reset_before_action(self) -> None:
        """清理一次性终态标记与历史输出，避免上一步状态扩散到当前动作。"""
        ctx = self.runner_context
        if ctx is not None:
            try:
                ctx.stop_after_current_action = False
                ctx.last_output = ""
            except Exception:
                pass

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
                if txt:
                    out_str = str(txt)
                    self.set_last_output(out_str)
                    return out_str

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
        if hasattr(res, "text") and getattr(res, "text", None):
            txt = str(res.text)
            self.set_last_output(txt)
            return txt
        if hasattr(res, "caption") and getattr(res, "caption", None):
            txt = str(res.caption)
            self.set_last_output(txt)
            return txt

        return ""

    def resolve_next_action(self, node: BaseFlowNode) -> Any:
        if self.graph is None or not node.next_node_id:
            return None
        next_node = self.graph.nodes.get(node.next_node_id)
        if next_node is None:
            return None
        return next_node.metadata.get("raw_action")

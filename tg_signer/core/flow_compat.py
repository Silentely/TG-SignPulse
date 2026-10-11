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
        """只允许当前 scoped 输出和当前收到的消息参与 skip 判定。"""
        if context.last_output:
            return str(context.last_output)
        last_received = getattr(self.runner_context, "last_received_text", "")
        return last_received if isinstance(last_received, str) else ""

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
            # step 是 legacy 别名，数据源仍然只有 scoped steps。
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

    def output_text(self) -> str:
        """读取旧 runner 产生的 Telegram 输出，作为副作用层的返回值。"""
        output = getattr(self.runner_context, "last_output", "")
        return output if isinstance(output, str) else ""

    def resolve_next_action(self, node: BaseFlowNode) -> Any:
        if self.graph is None or not node.next_node_id:
            return None
        next_node = self.graph.nodes.get(node.next_node_id)
        if next_node is None:
            return None
        return next_node.metadata.get("raw_action")

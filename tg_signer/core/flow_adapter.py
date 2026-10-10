# tg_signer/core/flow_adapter.py
from __future__ import annotations

import logging
from typing import Any

from tg_signer.config import SignChatV3
from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_models import (
    BaseFlowNode,
    NodeStatus,
    StepOutcome,
)

logger = logging.getLogger("tg_signer.flow_adapter")

class TelegramNodeExecutor:
    """隔离旧系统副作用的动作执行适配器"""

    def __init__(self, runner: Any, chat: SignChatV3):
        self.runner = runner
        self.chat = chat

    async def __call__(self, node: BaseFlowNode, context: ScopedFlowContext) -> StepOutcome:
        raw_act = node.metadata.get("raw_action")
        # 严格重置并隔离旧 context 污染
        if hasattr(self.runner, "context") and self.runner.context is not None:
            self.runner.context.stop_after_current_action = False

        try:
            res = await self.runner.wait_for(self.chat, raw_act)
            matched_term = False
            if hasattr(self.runner, "context") and getattr(self.runner.context, "stop_after_current_action", False):
                matched_term = True
                self.runner.context.stop_after_current_action = False # 物理清零，阻止扩散

            return StepOutcome(
                node_id=node.id,
                status=NodeStatus.SUCCESS if res is not False else NodeStatus.FAILED,
                matched_terminal=matched_term,
                output_text=str(getattr(self.runner.context, "last_output", "") or ""),
            )
        except Exception as exc:
            logger.error(f"步骤 {node.id} 执行失败: {exc}")
            return StepOutcome(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error=exc,
                output_text=str(exc),
            )

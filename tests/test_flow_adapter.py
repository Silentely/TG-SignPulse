# tests/test_flow_adapter.py
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_signer.config import ClickKeyboardByTextAction, SendTextAction, SignChatV3
from tg_signer.core.flow_adapter import TelegramNodeExecutor
from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_engine import PulseFlowEngine
from tg_signer.core.flow_normalizer import GraphNormalizer


@pytest.mark.asyncio
async def test_full_pipeline_with_telegram_adapter_barrier():
    chat = SignChatV3(
        chat_id=99999,
        actions=[
            SendTextAction(text="/checkin"),
            ClickKeyboardByTextAction(text="确认领奖"),
        ],
    )
    graph = GraphNormalizer.from_chat(chat)
    ctx = ScopedFlowContext(account={"username": "test_bot"})

    mock_runner = MagicMock()
    # 模拟真实 wait_for 执行成功
    mock_runner.wait_for = AsyncMock(return_value=True)
    mock_runner.context = MagicMock()
    # 模拟旧代码中 Matcher 恶意残留的副作用写入
    mock_runner.context.stop_after_current_action = True

    executor = TelegramNodeExecutor(mock_runner, chat)
    engine = PulseFlowEngine()
    result = await engine.run(graph, ctx, executor)

    assert result["status"] == "success"
    assert result["path"] == ["step_0", "step_1"]
    # 验证真实 wait_for 被调用了 2 次，且旧副作用被隔离清零！
    assert mock_runner.wait_for.call_count == 2

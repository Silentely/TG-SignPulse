from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_signer.config import SendTextAction, SignChatV3
from tg_signer.core.humanize import (
    calculate_typing_delay,
    is_cjk,
    simulate_typing_action,
)
from tg_signer.core.signer_actions import SignerActionsMixin


def test_is_cjk():
    assert is_cjk("你") is True
    assert is_cjk("好") is True
    assert is_cjk("あ") is True  # Hiragana
    assert is_cjk("ア") is True  # Katakana
    assert is_cjk("a") is False
    assert is_cjk("Z") is False
    assert is_cjk("1") is False
    assert is_cjk(" ") is False
    assert is_cjk("!") is False


def test_calculate_typing_delay_distinguishes_cjk_and_latin():
    # 纯中文：20 字，按 120 CPM (0.5s/字) 约 10s，但被 clamp 到 8.0s 上限
    cjk_delay = calculate_typing_delay("这是一段用于测试打字时长的中文文本内容")
    assert 5.0 <= cjk_delay <= 8.0

    # 纯英文短句：10 字母，按 280 CPM 约 2.1s
    latin_delay = calculate_typing_delay("Hello World")
    assert 1.2 <= latin_delay <= 5.0

    # 极短字符必须满足下限 1.2s
    assert calculate_typing_delay("hi") >= 1.2

    # 空文本
    assert calculate_typing_delay("") == 1.2


@pytest.mark.asyncio
async def test_simulate_typing_action_cancels_on_exit():
    mock_client = MagicMock()
    mock_client.send_chat_action = AsyncMock()

    async with simulate_typing_action(
        mock_client, chat_id=12345, text="测试长文本" * 10
    ):
        await asyncio.sleep(0.05)
        assert mock_client.send_chat_action.called
        mock_client.send_chat_action.assert_called_with(12345, "typing")


@pytest.mark.asyncio
async def test_simulate_typing_action_yields_actual_presend_delay():
    """as 拿到的值必须是实际等待的秒数（不超过 max_presend_delay），而非未被限制的理论时长。"""
    mock_client = MagicMock()
    mock_client.send_chat_action = AsyncMock()

    long_text = "这是一段非常长用于测试打字时长的中文文本内容测试打字时长的中文文本内容测试打字时长的中文文本内容"
    async with simulate_typing_action(
        mock_client, chat_id=1, text=long_text, max_presend_delay=1.0
    ) as waited:
        # 长文本理论延迟会被 clamp 到 ~8s，但进入前等待被限制到 1.0s
        assert 0.0 <= waited <= 1.0

    async with simulate_typing_action(
        mock_client, chat_id=1, text=long_text, max_presend_delay=0.0
    ) as waited:
        assert waited == 0.0


@pytest.mark.asyncio
async def test_simulate_typing_action_graceful_degradation():
    # client is None
    async with simulate_typing_action(None, chat_id=12345, text="test"):
        await asyncio.sleep(0.01)

    # client lacks send_chat_action
    async with simulate_typing_action(object(), chat_id=12345, text="test"):
        await asyncio.sleep(0.01)

    # client.send_chat_action raises exception
    failing_client = MagicMock()
    failing_client.send_chat_action = AsyncMock(
        side_effect=RuntimeError("network error")
    )
    async with simulate_typing_action(failing_client, chat_id=12345, text="test"):
        await asyncio.sleep(0.01)


class DummyActionSigner(SignerActionsMixin):
    def __init__(self, app=None):
        self.app = app
        self.log_entries = []

    def log(self, msg, level="INFO"):
        self.log_entries.append((level, msg))

    async def send_message(self, chat_id, text, delete_after=None, **kwargs):
        if self.app and hasattr(self.app, "send_message"):
            return await self.app.send_message(chat_id, text, **kwargs)
        return MagicMock()

    async def _chat_state_snapshot(self, chat, history_limit=12):
        return None

    async def _maybe_stop_after_send(self, chat, before_state=None, history_limit=12):
        pass


@pytest.mark.asyncio
async def test_signer_actions_triggers_typing_action_on_send_text():
    mock_app = MagicMock()
    mock_app.send_chat_action = AsyncMock()
    mock_app.send_message = AsyncMock()

    signer = DummyActionSigner(app=mock_app)
    chat = SignChatV3(chat_id=99999, actions=[])
    action = SendTextAction(text="hello humanized typing")

    await signer.wait_for(chat, action)

    assert mock_app.send_chat_action.called
    mock_app.send_chat_action.assert_called_with(99999, "typing")
    assert mock_app.send_message.called


@pytest.mark.asyncio
async def test_signer_actions_graceful_when_no_app():
    signer = DummyActionSigner(app=None)
    chat = SignChatV3(chat_id=99999, actions=[])
    action = SendTextAction(text="hello no app")

    # Should succeed without exception even when self.app is None
    await signer.wait_for(chat, action)

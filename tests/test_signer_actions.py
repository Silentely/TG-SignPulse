from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_signer.compat import InlineKeyboardMarkup
from tg_signer.config import ClickKeyboardByTextAction, SignChatV3
from tg_signer.core.context import chat_scope_key
from tg_signer.core.signer_actions import SignerActionsMixin


class DummySigner(SignerActionsMixin):
    def __init__(self):
        self.app = MagicMock()
        self.context = SimpleNamespace(
            last_callback_unconfirmed=False,
            last_callback_answer=None,
            chat_messages={},
            waiting_message=None,
        )
        self.logs = []

    def log(self, msg, level="INFO", **kwargs):
        self.logs.append((level, msg))

    def _message_matches_chat_thread(self, message, chat):
        return True

    def _message_is_actionable_target(self, message):
        return True

    def _log_received_target_message(self, message):
        return None

    def _current_action_step_label(self):
        return "第 1 步"


def test_next_click_action_is_available_on_current_menu():
    signer = DummySigner()
    message = MagicMock()
    message.reply_markup = InlineKeyboardMarkup(
        [[SimpleNamespace(text="👤 个人中心"), SimpleNamespace(text="✅ 签到")]]
    )

    assert (
        signer._next_click_action_is_available(
            message, ClickKeyboardByTextAction(text="签到")
        )
        is True
    )
    assert (
        signer._next_click_action_is_available(
            message, ClickKeyboardByTextAction(text="返回主菜单")
        )
        is False
    )


def test_next_click_action_requires_a_click_action():
    signer = DummySigner()
    message = MagicMock()
    message.reply_markup = InlineKeyboardMarkup([[SimpleNamespace(text="签到")]])

    assert signer._next_click_action_is_available(message, None) is False


@pytest.mark.asyncio
async def test_click_action_skips_navigation_when_next_menu_button_is_available():
    signer = DummySigner()
    action = ClickKeyboardByTextAction(text="返回主菜单", continue_on_error=True)
    next_action = ClickKeyboardByTextAction(text="签到")
    chat = SignChatV3(chat_id=100, actions=[action, next_action])
    message = SimpleNamespace(
        id=1,
        chat=SimpleNamespace(id=100),
        text="主菜单",
        caption=None,
        reply_markup=InlineKeyboardMarkup(
            [[SimpleNamespace(text="✅ 签到", callback_data=b"sign")]]
        ),
    )
    signer.context.chat_messages[chat_scope_key(100, None)] = {1: message}

    result = await signer.wait_for(chat, action, timeout=0.2, next_action=next_action)

    assert result is True
    assert any("跳过「返回主菜单」" in msg for _, msg in signer.logs)


@pytest.mark.asyncio
async def test_click_inline_button_delegates_to_unified_text():
    signer = DummySigner()

    btn = SimpleNamespace(callback_data=None, text="Click Here")
    msg = SimpleNamespace(
        chat=SimpleNamespace(id=100),
        id=200,
        click=AsyncMock(return_value=True),
    )

    ok = await signer._click_inline_button(msg, btn)
    assert ok is True
    msg.click.assert_awaited_once_with("Click Here")


@pytest.mark.asyncio
async def test_click_inline_button_prioritizes_text_in_unified():
    signer = DummySigner()

    # When chat or id is missing, _click_inline_button routes to click_inline_button_unified
    btn = SimpleNamespace(callback_data="cb_payload", text="Button Label")
    msg = SimpleNamespace(
        chat=None,
        id=None,
        click=AsyncMock(return_value=True),
    )

    ok = await signer._click_inline_button(msg, btn)
    assert ok is True
    msg.click.assert_awaited_once_with("Button Label")


@pytest.mark.asyncio
async def test_click_inline_button_fallback_to_callback_when_text_empty():
    signer = DummySigner()

    btn = SimpleNamespace(callback_data="cb_payload", text="")
    msg = SimpleNamespace(
        chat=None,
        id=None,
        click=AsyncMock(return_value=True),
    )

    ok = await signer._click_inline_button(msg, btn)
    assert ok is True
    msg.click.assert_awaited_once_with("cb_payload")


@pytest.mark.asyncio
async def test_click_inline_button_failure_logs():
    signer = DummySigner()

    btn = SimpleNamespace(callback_data=None, text="Click Here")
    msg = SimpleNamespace(
        chat=SimpleNamespace(id=100),
        id=200,
        click=AsyncMock(return_value=False),
    )

    ok = await signer._click_inline_button(msg, btn)
    assert ok is False
    assert any("按钮没有可用 callback_data" in log[1] for log in signer.logs)

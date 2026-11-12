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
@pytest.mark.parametrize("accepted", [True, False])
@pytest.mark.parametrize("use_default", [True, False])
async def test_semantic_next_menu_checks_without_clicking(
    monkeypatch, accepted, use_default
):
    from tg_signer.semantic.models import Decision

    signer = DummySigner()
    button = SimpleNamespace(text="每日报到", callback_data=b"daily")
    message = SimpleNamespace(
        id=1,
        chat=SimpleNamespace(id=100),
        text="主菜单",
        caption=None,
        reply_markup=InlineKeyboardMarkup([[button]]),
    )
    action = ClickKeyboardByTextAction(
        text="签到",
        semantic_button=None
        if use_default
        else {"mode": "assist", "goal": "完成每日签到"},
    )
    service = SimpleNamespace(
        evaluate=AsyncMock(
            return_value=Decision(
                status="ok",
                selected="b0_0" if accepted else "none",
                probabilities={
                    "b0_0": 0.99 if accepted else 0.01,
                    "none": 0.01 if accepted else 0.99,
                },
                confidence=0.99,
            )
        )
    )
    runtime = SimpleNamespace(service=service, record_observation=MagicMock())
    monkeypatch.setattr(
        "tg_signer.semantic.runtime_port.get_registered_semantic_runtime",
        lambda: runtime,
    )
    signer._click_inline_button = AsyncMock(return_value=True)

    assert (
        await signer._next_click_action_is_semantically_available(message, action)
        is accepted
    )
    signer._click_inline_button.assert_not_awaited()
    assert not getattr(signer.context, "_action_already_satisfied", False)
    for _ in range(3):
        assert (
            await signer._next_click_action_is_semantically_available(message, action)
            is accepted
        )
    service.evaluate.assert_awaited_once()
    request = service.evaluate.call_args.args[0]
    assert request.state["text"] == "主菜单"
    assert request.state["goal"] == ("签到" if use_default else "完成每日签到")
    assert any(
        "[JEV 按钮] 开始语义判断" in log and "主菜单" in log and "每日报到" in log
        for _, log in signer.logs
    )
    assert any("[JEV 按钮] 判断返回" in log for _, log in signer.logs)
    clicked, matched = await signer._click_keyboard_by_text_result(action, message)
    assert (clicked, matched) == (accepted, accepted)
    assert signer._click_inline_button.await_count == int(accepted)
    service.evaluate.assert_awaited_once()
    assert sum("[JEV 按钮] 开始语义判断" in log for _, log in signer.logs) == 1

    message.text = "主菜单已更新"
    assert (
        await signer._next_click_action_is_semantically_available(message, action)
        is accepted
    )
    assert service.evaluate.await_count == 2
    changed_action = action.copy(
        update={"semantic_button": {"mode": "assist", "goal": "领取今日奖励"}}
    )
    assert (
        await signer._next_click_action_is_semantically_available(
            message, changed_action
        )
        is accepted
    )
    assert service.evaluate.await_count == 3

    runtime.service = None
    assert (
        await signer._next_click_action_is_semantically_available(
            message, changed_action
        )
        is False
    )
    assert service.evaluate.await_count == 3
    runtime.service = SimpleNamespace(
        evaluate=AsyncMock(return_value=service.evaluate.return_value)
    )
    assert (
        await signer._next_click_action_is_semantically_available(
            message, changed_action
        )
        is accepted
    )
    runtime.service.evaluate.assert_awaited_once()


@pytest.mark.asyncio
async def test_unconfigured_jev_logs_once_without_request(monkeypatch):
    signer = DummySigner()
    runtime = SimpleNamespace(service=None)
    monkeypatch.setattr(
        "tg_signer.semantic.runtime_port.get_registered_semantic_runtime",
        lambda: runtime,
    )
    message = SimpleNamespace(
        id=1,
        chat=SimpleNamespace(id=100),
        text="菜单",
        reply_markup=InlineKeyboardMarkup(
            [[SimpleNamespace(text="每日报到", callback_data=b"daily")]]
        ),
    )
    action = ClickKeyboardByTextAction(text="签到")
    for _ in range(4):
        assert await signer._resolve_semantic_button(message, action) is None
    assert sum("[JEV 按钮] 未调用" in log for _, log in signer.logs) == 1
    assert not any("开始语义判断" in log for _, log in signer.logs)


@pytest.mark.asyncio
async def test_semantic_button_off_does_not_request_model(monkeypatch):
    signer = DummySigner()
    provider = MagicMock()
    monkeypatch.setattr(
        "tg_signer.semantic.runtime_port.get_registered_semantic_runtime", provider
    )
    assert (
        await signer._resolve_semantic_button(
            SimpleNamespace(),
            ClickKeyboardByTextAction(text="签到", semantic_button={"mode": "off"}),
        )
        is None
    )
    provider.assert_not_called()


@pytest.mark.asyncio
async def test_semantic_button_rejects_menu_changed_during_judgment(monkeypatch):
    from tg_signer.semantic.models import Decision

    signer = DummySigner()
    button = SimpleNamespace(text="每日报到", callback_data=b"daily")
    message = SimpleNamespace(
        id=1,
        chat=SimpleNamespace(id=100),
        text="主菜单",
        reply_markup=InlineKeyboardMarkup([[button]]),
    )

    async def evaluate(*args, **kwargs):
        button.text = "其他操作"
        return Decision(
            status="ok",
            selected="b0_0",
            probabilities={"b0_0": 0.99, "none": 0.01},
            confidence=0.99,
        )

    runtime = SimpleNamespace(
        service=SimpleNamespace(evaluate=evaluate), record_observation=MagicMock()
    )
    monkeypatch.setattr(
        "tg_signer.semantic.runtime_port.get_registered_semantic_runtime",
        lambda: runtime,
    )
    action = ClickKeyboardByTextAction(text="签到", semantic_button={"mode": "assist"})
    assert (
        await signer._next_click_action_is_semantically_available(message, action)
        is False
    )


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

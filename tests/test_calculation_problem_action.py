from __future__ import annotations

from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_signer.compat import InlineKeyboardMarkup, ReplyKeyboardMarkup
from tg_signer.config import (
    ClickButtonByCalculationProblemAction,
    ReplyByCalculationProblemAction,
)
from tg_signer.core.context import UserSignerWorkerContext
from tg_signer.core.signer_actions import (
    SignerActionsMixin,
    _get_message_text,
    _normalize_button_text,
)


class MockButton:
    def __init__(self, text: str, callback_data: str | None = None):
        self.text = text
        self.callback_data = callback_data or text


class DummySigner(SignerActionsMixin):
    def __init__(self):
        self.app = MagicMock()
        self.context = UserSignerWorkerContext(
            sign_chats={},
            chat_messages=defaultdict(dict),
        )
        self.ai_tools = MagicMock()
        self.ai_tools.default_model = "test-ai-model"
        self.logs: list[tuple[str, str]] = []
        self._click_inline_button = AsyncMock(return_value=True)
        self.send_message = AsyncMock(return_value=True)

    def get_ai_tools(self):
        return self.ai_tools

    def log(self, msg: str, level: str = "INFO"):
        self.logs.append((level, msg))

    def _log_received_target_message(self, message):
        pass

    def _normalize_log_text(self, text: str, max_len: int = 220):
        return text[:max_len]

    def _resolve_message_thread_id(self, message):
        return None


def test_get_message_text_prefers_text_and_falls_back_caption():
    # 1. Text and caption present -> text wins
    msg1 = SimpleNamespace(text="  Hello World  ", caption="Caption text")
    assert _get_message_text(msg1) == "Hello World"

    # 2. Text only -> returns text
    msg2 = SimpleNamespace(text="Only text", caption=None)
    assert _get_message_text(msg2) == "Only text"

    # 3. Caption only (text is None) -> returns caption
    msg3 = SimpleNamespace(text=None, caption="  Caption only  ")
    assert _get_message_text(msg3) == "Caption only"

    # 4. Caption only (text is empty string) -> returns caption
    msg4 = SimpleNamespace(text="", caption="Fallback caption")
    assert _get_message_text(msg4) == "Fallback caption"

    # 5. Neither or None message -> returns ""
    assert _get_message_text(None) == ""
    msg5 = SimpleNamespace(text="", caption="")
    assert _get_message_text(msg5) == ""
    msg6 = SimpleNamespace()
    assert _get_message_text(msg6) == ""


def test_normalize_button_text_removes_whitespace_and_lowercases():
    assert _normalize_button_text("  Option  A  ") == "optiona"
    assert _normalize_button_text(" 4 2 ") == "42"
    assert _normalize_button_text("Answer:\tB\n") == "answer:b"
    assert _normalize_button_text("") == ""
    assert _normalize_button_text(None) == ""
    assert _normalize_button_text(123) == "123"


@pytest.mark.asyncio
async def test_click_button_by_calculation_problem_injects_button_options():
    signer = DummySigner()
    chat_id = -100123
    btn1 = MockButton("10")
    btn2 = MockButton("20")
    btn3 = MockButton("30")
    message = SimpleNamespace(
        id=2,
        chat=SimpleNamespace(id=chat_id),
        text="5 + 5 = ?",
        caption=None,
        reply_markup=InlineKeyboardMarkup([[btn1, btn2, btn3]]),
    )

    signer.ai_tools.calculate_problem = AsyncMock(return_value="10")
    action = ClickButtonByCalculationProblemAction()
    ok = await signer._click_button_by_calculation_problem(action, message)

    assert ok is True
    signer.ai_tools.calculate_problem.assert_awaited_once()
    prompt_sent = signer.ai_tools.calculate_problem.call_args[0][0]
    assert "5 + 5 = ?" in prompt_sent
    assert '可选答案：["10", "20", "30"]' in prompt_sent
    assert "请只从可选答案中选择最匹配的一项" in prompt_sent
    signer._click_inline_button.assert_awaited_once()
    assert signer._click_inline_button.call_args[0][1].text == "10"


@pytest.mark.asyncio
async def test_click_button_by_calculation_problem_loose_substring_match():
    """精确匹配失败时应走宽松子串匹配分支（该分支此前不可达）。"""
    signer = DummySigner()
    chat_id = -100123
    btn = MockButton("10 分（正确）")
    message = SimpleNamespace(
        id=21,
        chat=SimpleNamespace(id=chat_id),
        text="请选择 10 分对应的按钮",
        caption=None,
        reply_markup=InlineKeyboardMarkup([[btn]]),
    )

    # 令按文本点击先失败，强制进入宽松匹配兜底
    signer._click_keyboard_by_text = AsyncMock(return_value=False)
    signer.ai_tools.calculate_problem = AsyncMock(return_value="10 分")

    action = ClickButtonByCalculationProblemAction()
    ok = await signer._click_button_by_calculation_problem(action, message)

    assert ok is True
    signer._click_inline_button.assert_awaited_once_with(message, btn)


@pytest.mark.asyncio
async def test_click_button_by_calculation_problem_rejects_numeric_substring_match():
    """答案与按钮均为纯数字且不相等时不得宽松匹配，避免误点其他编号按钮。"""
    signer = DummySigner()
    chat_id = -100123
    btn = MockButton("10")
    message = SimpleNamespace(
        id=22,
        chat=SimpleNamespace(id=chat_id),
        text="1 + 0 = ?",
        caption=None,
        reply_markup=InlineKeyboardMarkup([[btn]]),
    )

    signer._click_keyboard_by_text = AsyncMock(return_value=False)
    signer.ai_tools.calculate_problem = AsyncMock(return_value="1")

    action = ClickButtonByCalculationProblemAction()
    ok = await signer._click_button_by_calculation_problem(action, message)

    assert ok is False
    signer._click_inline_button.assert_not_awaited()


@pytest.mark.asyncio
async def test_click_button_by_calculation_problem_matches_option_with_spaces():
    signer = DummySigner()
    chat_id = -100123
    btn = MockButton("  4 2  ")
    message = SimpleNamespace(
        id=3,
        chat=SimpleNamespace(id=chat_id),
        text="Calculate: 40 + 2",
        caption=None,
        reply_markup=InlineKeyboardMarkup([[btn]]),
    )

    # 模拟 _click_keyboard_by_text 未命中直接返回 False，测试宽松归一化回退逻辑
    signer._click_keyboard_by_text = AsyncMock(return_value=False)
    signer.ai_tools.calculate_problem = AsyncMock(return_value=" 42 ")

    action = ClickButtonByCalculationProblemAction()
    ok = await signer._click_button_by_calculation_problem(action, message)

    assert ok is True
    signer._click_inline_button.assert_awaited_once_with(message, btn)


@pytest.mark.asyncio
async def test_click_button_by_calculation_problem_reply_keyboard_with_spaces():
    signer = DummySigner()
    chat_id = -100123
    btn = MockButton("  4 2  ")
    message = SimpleNamespace(
        id=31,
        chat=SimpleNamespace(id=chat_id),
        text="Calculate: 40 + 2",
        caption=None,
        reply_markup=ReplyKeyboardMarkup([[btn]]),
    )

    signer._click_keyboard_by_text = AsyncMock(return_value=False)
    signer.ai_tools.calculate_problem = AsyncMock(return_value="42")

    action = ClickButtonByCalculationProblemAction()
    ok = await signer._click_button_by_calculation_problem(action, message)

    assert ok is True
    signer.send_message.assert_awaited_once_with(chat_id, "  4 2  ")


@pytest.mark.asyncio
async def test_reply_by_calculation_problem_with_caption():
    signer = DummySigner()
    chat_id = -100123
    message = SimpleNamespace(
        id=4,
        chat=SimpleNamespace(id=chat_id),
        text=None,
        caption="7 + 8 = ?",
    )

    signer.ai_tools.calculate_problem = AsyncMock(return_value="15")
    action = ReplyByCalculationProblemAction()
    ok = await signer._reply_by_calculation_problem(action, message)

    assert ok is True
    signer.ai_tools.calculate_problem.assert_awaited_once()
    assert "7 + 8 = ?" in signer.ai_tools.calculate_problem.call_args[0][0]
    signer.send_message.assert_awaited_once_with(chat_id, "15")


@pytest.mark.asyncio
async def test_calculation_problem_empty_question_returns_false():
    signer = DummySigner()
    chat_id = -100123
    empty_msg = SimpleNamespace(
        id=5,
        chat=SimpleNamespace(id=chat_id),
        text=None,
        caption="",
    )

    reply_action = ReplyByCalculationProblemAction()
    assert await signer._reply_by_calculation_problem(reply_action, empty_msg) is False

    click_action = ClickButtonByCalculationProblemAction()
    assert await signer._click_button_by_calculation_problem(click_action, empty_msg) is False

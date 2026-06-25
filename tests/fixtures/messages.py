"""
消息测试数据 Fixtures

提供 Telegram 消息相关的预构建测试数据，涵盖：
纯文本消息、带按钮的消息、图片消息、签到成功/失败回复等。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from tests.mocks.telegram import (
    MockInlineButton,
    MockInlineKeyboardMarkup,
    MockMessage,
    MockReplyKeyboardMarkup,
    MockUser,
    create_mock_inline_keyboard,
    create_mock_reply_keyboard,
)


# ---------- 基础消息 ----------

def make_text_message(
    message_id: int = 1,
    text: str = "签到",
    chat_id: int = -1001234567890,
    from_user: Optional[MockUser] = None,
    message_thread_id: Optional[int] = None,
) -> MockMessage:
    """生成纯文本消息"""
    return MockMessage(
        message_id=message_id,
        text=text,
        chat_id=chat_id,
        from_user=from_user,
        message_thread_id=message_thread_id,
    )


def make_sign_success_message(
    message_id: int = 10,
    chat_id: int = -1001234567890,
) -> MockMessage:
    """生成签到成功回复消息"""
    return MockMessage(
        message_id=message_id,
        text="签到成功！",
        chat_id=chat_id,
    )


def make_sign_already_done_message(
    message_id: int = 11,
    chat_id: int = -1001234567890,
) -> MockMessage:
    """生成已签到回复消息"""
    return MockMessage(
        message_id=message_id,
        text="今天已经签到过了",
        chat_id=chat_id,
    )


def make_sign_fail_message(
    message_id: int = 12,
    chat_id: int = -1001234567890,
) -> MockMessage:
    """生成签到失败回复消息"""
    return MockMessage(
        message_id=message_id,
        text="签到失败，请重试",
        chat_id=chat_id,
    )


# ---------- 带按钮的消息 ----------

def make_inline_keyboard_message(
    message_id: int = 20,
    text: str = "请选择正确的选项",
    buttons: Optional[List[List[str]]] = None,
    chat_id: int = -1001234567890,
) -> MockMessage:
    """生成带 InlineKeyboard 的消息"""
    if buttons is None:
        buttons = [["选项A", "选项B"], ["选项C", "选项D"]]
    reply_markup = create_mock_inline_keyboard(buttons)
    return MockMessage(
        message_id=message_id,
        text=text,
        chat_id=chat_id,
        reply_markup=reply_markup,
    )


def make_reply_keyboard_message(
    message_id: int = 21,
    text: str = "请选择",
    buttons: Optional[List[List[str]]] = None,
    chat_id: int = -1001234567890,
) -> MockMessage:
    """生成带 ReplyKeyboard 的消息"""
    if buttons is None:
        buttons = [["签到", "查询"], ["帮助"]]
    reply_markup = create_mock_reply_keyboard(buttons)
    return MockMessage(
        message_id=message_id,
        text=text,
        chat_id=chat_id,
        reply_markup=reply_markup,
    )


# ---------- 图片消息 ----------

def make_photo_message(
    message_id: int = 30,
    caption: str = "请根据图片选择正确选项",
    buttons: Optional[List[List[str]]] = None,
    chat_id: int = -1001234567890,
) -> MockMessage:
    """生成带图片的消息"""
    if buttons is None:
        buttons = [["猫", "狗"], ["鸟", "鱼"]]
    reply_markup = create_mock_inline_keyboard(buttons)
    return MockMessage(
        message_id=message_id,
        text="",
        caption=caption,
        chat_id=chat_id,
        reply_markup=reply_markup,
        photo=MockPhoto(),
    )


def make_photo_no_keyboard_message(
    message_id: int = 31,
    caption: str = "请识别图片中的文字",
    chat_id: int = -1001234567890,
) -> MockMessage:
    """生成仅图片无键盘的消息"""
    return MockMessage(
        message_id=message_id,
        text="",
        caption=caption,
        chat_id=chat_id,
        photo=MockPhoto(),
    )


# ---------- 计算题消息 ----------

def make_calculation_message(
    message_id: int = 40,
    text: str = "请计算: 12 + 34 = ?",
    chat_id: int = -1001234567890,
) -> MockMessage:
    """生成计算题消息"""
    return MockMessage(
        message_id=message_id,
        text=text,
        chat_id=chat_id,
    )


def make_calculation_with_buttons_message(
    message_id: int = 41,
    text: str = "请计算: 15 * 3 = ?",
    buttons: Optional[List[List[str]]] = None,
    chat_id: int = -1001234567890,
) -> MockMessage:
    """生成带按钮的计算题消息"""
    if buttons is None:
        buttons = [["35"], ["45"], ["50"], ["60"]]
    reply_markup = create_mock_inline_keyboard(buttons)
    return MockMessage(
        message_id=message_id,
        text=text,
        chat_id=chat_id,
        reply_markup=reply_markup,
    )


# ---------- 辅助类 ----------

class MockPhoto:
    """模拟 Telegram Photo 对象"""

    def __init__(self, width: int = 640, height: int = 480):
        self.width = width
        self.height = height
        self.file_id = "test_photo_file_id"
        self.file_unique_id = "test_photo_unique_id"


# ---------- 预置消息序列 ----------

def make_sign_flow_messages(
    chat_id: int = -1001234567890,
) -> List[MockMessage]:
    """生成完整签到流程的消息序列"""
    return [
        make_text_message(message_id=1, text="签到", chat_id=chat_id),
        make_sign_success_message(message_id=10, chat_id=chat_id),
    ]


def make_sign_with_keyboard_flow_messages(
    chat_id: int = -1001234567890,
) -> List[MockMessage]:
    """生成带键盘确认的签到流程消息序列"""
    return [
        make_text_message(message_id=1, text="签到", chat_id=chat_id),
        make_inline_keyboard_message(
            message_id=20,
            text="请确认签到",
            buttons=[["确认", "取消"]],
            chat_id=chat_id,
        ),
        make_sign_success_message(message_id=10, chat_id=chat_id),
    ]

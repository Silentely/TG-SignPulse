"""
Telegram 客户端 Mock 对象

提供 MockTelegramClient 和相关辅助类，用于在不连接真实 Telegram API 的情况下
测试签到、消息发送、按钮点击等功能。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Union
from unittest.mock import AsyncMock, MagicMock


class MockMessage:
    """模拟 Telegram Message 对象"""

    def __init__(
        self,
        message_id: int = 1,
        text: str = "",
        chat_id: int = -1001234567890,
        from_user: Optional[Any] = None,
        reply_markup: Optional[Any] = None,
        photo: Optional[Any] = None,
        caption: Optional[str] = None,
        message_thread_id: Optional[int] = None,
        edit_date: Optional[int] = None,
    ):
        self.id = message_id
        self.text = text
        self.chat = SimpleNamespace(
            id=chat_id,
            type="supergroup",
            title="Test Chat",
            username="testchat",
        )
        self.from_user = from_user or SimpleNamespace(
            id=111111,
            is_self=False,
            is_bot=False,
            username="testuser",
            first_name="Test",
            last_name="User",
        )
        self.reply_markup = reply_markup
        self.photo = photo
        self.caption = caption
        self.message_thread_id = message_thread_id
        self.edit_date = edit_date
        self.media = None

    async def delete(self):
        """模拟删除消息"""
        return True

    async def click(self, *args, **kwargs):
        """模拟点击按钮"""
        return SimpleNamespace(message_id=self.id + 1)


class MockInlineButton:
    """模拟 InlineKeyboardButton"""

    def __init__(self, text: str, callback_data: Optional[str] = None):
        self.text = text
        self.callback_data = callback_data or text.lower().replace(" ", "_")


class MockInlineKeyboardMarkup:
    """模拟 InlineKeyboardMarkup"""

    def __init__(self, buttons: List[List[MockInlineButton]]):
        self.inline_keyboard = buttons


class MockReplyKeyboardMarkup:
    """模拟 ReplyKeyboardMarkup"""

    def __init__(self, buttons: List[List[str]]):
        self.keyboard = buttons


class MockUser:
    """模拟 Telegram User 对象"""

    def __init__(
        self,
        user_id: int = 111111,
        username: str = "testuser",
        first_name: str = "Test",
        last_name: str = "User",
        is_bot: bool = False,
        is_self: bool = False,
    ):
        self.id = user_id
        self.username = username
        self.first_name = first_name
        self.last_name = last_name
        self.is_bot = is_bot
        self.is_self = is_self


class MockChat:
    """模拟 Telegram Chat 对象"""

    def __init__(
        self,
        chat_id: int = -1001234567890,
        title: str = "Test Chat",
        chat_type: str = "supergroup",
        username: str = "testchat",
    ):
        self.id = chat_id
        self.title = title
        self.type = chat_type
        self.username = username


class MockDialog:
    """模拟 Telegram Dialog 对象"""

    def __init__(self, chat: MockChat):
        self.chat = chat


class MockTelegramClient:
    """
    模拟 Telegram 客户端

    记录所有调用以便断言，支持自定义返回值配置。
    """

    def __init__(self, name: str = "test_account", **kwargs):
        self.name = name
        self.is_connected = False
        self.is_initialized = False
        self.me = MockUser(is_self=True)
        self.loop = asyncio.new_event_loop()
        self.workdir = kwargs.get("workdir", ".")
        self.in_memory = kwargs.get("in_memory", False)
        self.session_string = kwargs.get("session_string", "")

        # 调用记录
        self.sent_messages: List[Dict[str, Any]] = []
        self.sent_dices: List[Dict[str, Any]] = []
        self.deleted_messages: List[int] = []
        self.handlers: List[Any] = []

        # 可配置的返回值
        self._dialogs: List[MockDialog] = []
        self._chat_history: Dict[int, List[MockMessage]] = defaultdict(list)
        self._send_message_response: Optional[MockMessage] = None

    def configure_dialogs(self, dialogs: List[MockDialog]):
        """配置 get_dialogs 返回的对话列表"""
        self._dialogs = dialogs

    def configure_chat_history(self, chat_id: int, messages: List[MockMessage]):
        """配置 get_chat_history 返回的消息列表"""
        self._chat_history[chat_id] = messages

    def configure_send_response(self, message: MockMessage):
        """配置 send_message 返回的消息"""
        self._send_message_response = message

    async def connect(self) -> bool:
        """模拟连接"""
        self.is_connected = True
        return True

    async def disconnect(self):
        """模拟断开连接"""
        self.is_connected = False

    async def start(self):
        """模拟启动"""
        self.is_connected = True
        self.is_initialized = True
        return self

    async def stop(self):
        """模拟停止"""
        self.is_connected = False

    async def initialize(self):
        """模拟初始化"""
        self.is_initialized = True

    async def get_me(self) -> MockUser:
        """获取当前用户"""
        return self.me

    async def get_chat(self, chat_id: Union[int, str]) -> MockChat:
        """获取聊天信息"""
        return MockChat(chat_id=chat_id if isinstance(chat_id, int) else -1001234567890)

    async def get_users(self, user_id: int) -> MockUser:
        """获取用户信息"""
        return MockUser(user_id=user_id)

    async def get_dialogs(self, limit: int = 20):
        """获取对话列表（异步迭代器）"""
        for dialog in self._dialogs[:limit]:
            yield dialog

    async def get_chat_history(self, chat_id: int, limit: int = 20):
        """获取聊天历史（异步迭代器）"""
        messages = self._chat_history.get(chat_id, [])
        for msg in messages[:limit]:
            yield msg

    async def get_chat_members(self, chat_id: Union[int, str], query: str = "", **kwargs):
        """获取聊天成员（异步迭代器）"""
        yield SimpleNamespace(user=MockUser())

    async def send_message(
        self,
        chat_id: Union[int, str],
        text: str,
        **kwargs,
    ) -> MockMessage:
        """发送消息"""
        msg = self._send_message_response or MockMessage(
            message_id=len(self.sent_messages) + 100,
            text=text,
            chat_id=chat_id if isinstance(chat_id, int) else -1001234567890,
        )
        self.sent_messages.append({
            "chat_id": chat_id,
            "text": text,
            "kwargs": kwargs,
        })
        return msg

    async def send_dice(
        self,
        chat_id: Union[int, str],
        emoji: str = "🎲",
        **kwargs,
    ) -> MockMessage:
        """发送骰子"""
        msg = MockMessage(
            message_id=len(self.sent_dices) + 200,
            text=emoji,
            chat_id=chat_id if isinstance(chat_id, int) else -1001234567890,
        )
        self.sent_dices.append({
            "chat_id": chat_id,
            "emoji": emoji,
            "kwargs": kwargs,
        })
        return msg

    async def invoke(self, query, *args, **kwargs):
        """模拟 Telegram API 调用"""
        return SimpleNamespace()

    def add_handler(self, handler, filters=None):
        """添加消息处理器"""
        entry = (handler, filters)
        self.handlers.append(entry)
        return entry

    def remove_handler(self, handler, filters=None):
        """移除消息处理器"""
        try:
            self.handlers.remove((handler, filters))
        except ValueError:
            pass

    async def export_session_string(self) -> str:
        """导出会话字符串"""
        return "test-session-string"

    async def log_out(self):
        """登出"""
        self.is_connected = False


def create_mock_inline_keyboard(
    buttons: List[List[str]],
) -> MockInlineKeyboardMarkup:
    """快捷创建 InlineKeyboardMarkup 的辅助函数"""
    return MockInlineKeyboardMarkup(
        [[MockInlineButton(text) for text in row] for row in buttons]
    )


def create_mock_reply_keyboard(
    buttons: List[List[str]],
) -> MockReplyKeyboardMarkup:
    """快捷创建 ReplyKeyboardMarkup 的辅助函数"""
    return MockReplyKeyboardMarkup(buttons)

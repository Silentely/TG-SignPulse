from __future__ import annotations

import asyncio
import unicodedata
from types import SimpleNamespace
from typing import Any, List, Tuple

from tg_signer.async_utils import compute_backoff

_PYROGRAM_IMPORT_ERROR: Exception | None = None


def _raise_pyrogram_import_error() -> None:
    raise RuntimeError(
        "Telegram runtime dependencies are unavailable. "
        "Use Python 3.10-3.13 with a compatible pyrogram/kurigram install."
    ) from _PYROGRAM_IMPORT_ERROR


try:
    from pyrogram import Client as BaseClient
    from pyrogram import errors, filters, raw
    from pyrogram.enums import ChatMembersFilter, ChatType
    from pyrogram.handlers import EditedMessageHandler, MessageHandler
    from pyrogram.methods.utilities.idle import idle
    from pyrogram.session import Session
    from pyrogram.storage import MemoryStorage
    from pyrogram.types import (
        Chat,
        InlineKeyboardMarkup,
        Message,
        Object,
        ReplyKeyboardMarkup,
        User,
    )
except Exception as exc:  # pragma: no cover - fallback for unsupported runtimes
    _PYROGRAM_IMPORT_ERROR = exc

    class _RPCError(Exception):
        pass

    class _FloodWait(_RPCError):
        def __init__(self, *args, value: int = 0, **kwargs):
            super().__init__(*args)
            self.value = value

    errors = SimpleNamespace(
        RPCError=_RPCError,
        FloodWait=_FloodWait,
        BadRequest=_RPCError,
        Unauthorized=_RPCError,
    )

    class _FilterExpr:
        def __and__(self, other):
            return self

        def __or__(self, other):
            return self

    filters = SimpleNamespace(
        text=_FilterExpr(),
        caption=_FilterExpr(),
        chat=lambda *args, **kwargs: _FilterExpr(),
    )

    raw = SimpleNamespace(
        functions=SimpleNamespace(
            updates=SimpleNamespace(
                GetChannelDifference=type("GetChannelDifference", (), {}),
                GetDifference=type("GetDifference", (), {}),
                GetState=type("GetState", (), {}),
            )
        )
    )

    class ChatMembersFilter:
        SEARCH = "search"
        ADMINISTRATORS = "administrators"

    class ChatType:
        BOT = "bot"
        GROUP = "group"
        SUPERGROUP = "supergroup"
        CHANNEL = "channel"

    class MessageHandler:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class EditedMessageHandler(MessageHandler):
        pass

    async def idle():
        _raise_pyrogram_import_error()

    class Session:
        START_TIMEOUT = 5

    class MemoryStorage:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class BaseClient:
        def __init__(self, *args, **kwargs):
            _raise_pyrogram_import_error()

        async def invoke(self, *args, **kwargs):
            _raise_pyrogram_import_error()

    class Chat:
        pass

    class InlineKeyboardMarkup:
        inline_keyboard = ()

    class Message:
        pass

    class Object:
        @staticmethod
        def default(obj):
            return str(obj)

    class ReplyKeyboardMarkup:
        keyboard = ()

    class User:
        pass
else:
    def _raise_pyrogram_import_error() -> None:
        return None


def clean_text_for_match(text: str) -> str:
    """归一化匹配文本：NFKC + 小写 + 去标点/符号/空白/控制字符。"""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text))
    return "".join(
        ch
        for ch in text.lower()
        if not unicodedata.category(ch).startswith(("P", "S", "Z", "C"))
    )


def button_text_matches(target_text: str, button_text: str) -> bool:
    """判定按钮文本是否命中目标文本（相等或互为子串）。"""
    if not target_text or not button_text:
        return False
    if target_text == button_text or target_text in button_text:
        return True
    return len(button_text) >= 2 and button_text in target_text


def collect_clickable_buttons(message) -> List[Tuple[str, Any, str]]:
    """提取消息可点击按钮：[(kind, button, text), ...]，kind 为 inline/reply。"""
    reply_markup = getattr(message, "reply_markup", None)
    clickable_buttons: List[Tuple[str, Any, str]] = []
    if isinstance(reply_markup, InlineKeyboardMarkup):
        for row in reply_markup.inline_keyboard:
            for button in row:
                button_text = getattr(button, "text", "")
                if button_text:
                    clickable_buttons.append(("inline", button, button_text))
    elif isinstance(reply_markup, ReplyKeyboardMarkup):
        for row in reply_markup.keyboard:
            for button in row:
                button_text = (
                    button if isinstance(button, str) else getattr(button, "text", "")
                )
                if button_text:
                    clickable_buttons.append(("reply", button, button_text))
    return clickable_buttons


async def call_with_retry(
    callback,
    *,
    operation: str,
    max_retries: int = 4,
    log=None,
    reconnect=None,
):
    """统一重试协议：FloodWait 等待 + 瞬态错误指数退避 + 可选重连。

    - log: 可选日志回调 ``log(level: str, message: str)``
    - reconnect: 可选重连协程回调（瞬态失败且未达上限时调用）
    达上限时原样抛出最后一次异常。
    """
    for attempt in range(1, max_retries + 1):
        try:
            return await callback()
        except errors.FloodWait as exc:
            wait_seconds = max(int(getattr(exc, "value", 1) or 1), 1)
            if log:
                log(
                    "WARNING",
                    f"{operation} 触发 FloodWait，{wait_seconds}s 后重试 ({attempt}/{max_retries})",
                )
            if attempt >= max_retries:
                raise
            await asyncio.sleep(wait_seconds)
        except (TimeoutError, asyncio.TimeoutError, OSError, ConnectionError) as exc:
            backoff = compute_backoff(attempt, cap=8)
            if log:
                log(
                    "WARNING",
                    f"{operation} 暂时失败，{backoff}s 后重试 ({attempt}/{max_retries}): {type(exc).__name__}: {exc}",
                )
            if attempt >= max_retries:
                raise
            if reconnect is not None:
                try:
                    await reconnect()
                except Exception as reconnect_exc:
                    if log:
                        log(
                            "WARNING",
                            f"{operation} 重连失败: {type(reconnect_exc).__name__}: {reconnect_exc}",
                        )
            await asyncio.sleep(backoff)

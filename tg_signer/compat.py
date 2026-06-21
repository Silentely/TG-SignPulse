from __future__ import annotations

from types import SimpleNamespace

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

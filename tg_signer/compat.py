from __future__ import annotations

import asyncio
import inspect
import logging
import unicodedata
from types import SimpleNamespace
from typing import Any, List, Tuple

from tg_signer.async_utils import compute_backoff

logger = logging.getLogger(__name__)

_PYROGRAM_IMPORT_ERROR: Exception | None = None


def _raise_pyrogram_import_error() -> None:
    raise RuntimeError(
        "Telegram runtime dependencies are unavailable. "
        "Use Python 3.10-3.13 with a compatible pyrogram/kurigram install."
    ) from _PYROGRAM_IMPORT_ERROR


try:
    from pyrogram import Client as BaseClient
    from pyrogram import errors, filters, raw, types
    from pyrogram.enums import ChatMembersFilter, ChatType
    from pyrogram.handlers import EditedMessageHandler, MessageHandler
    from pyrogram.methods.utilities.idle import idle
    from pyrogram.session import Session
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

    types = SimpleNamespace(
        Animation=type(
            "Animation", (), {"_parse_chat_animation": lambda *a, **k: None}
        ),
        ChatPhoto=type("ChatPhoto", (), {"_parse": lambda *a, **k: None}),
        Chat=Chat,
        InlineKeyboardMarkup=InlineKeyboardMarkup,
        Message=Message,
        Object=Object,
        ReplyKeyboardMarkup=ReplyKeyboardMarkup,
        User=User,
    )

    raw = SimpleNamespace(
        functions=SimpleNamespace(
            updates=SimpleNamespace(
                GetChannelDifference=type("GetChannelDifference", (), {}),
                GetDifference=type("GetDifference", (), {}),
                GetState=type("GetState", (), {}),
            ),
            channels=SimpleNamespace(
                GetForumTopics=type("GetForumTopics", (), {}),
            ),
        ),
        types=SimpleNamespace(
            ForumTopic=type("ForumTopic", (), {}),
            ForumTopicDeleted=type("ForumTopicDeleted", (), {}),
            VideoSizeEmojiMarkup=type("VideoSizeEmojiMarkup", (), {}),
            VideoSizeStickerMarkup=type("VideoSizeStickerMarkup", (), {}),
            Photo=type("Photo", (), {}),
            messages=SimpleNamespace(
                ForumTopics=type("ForumTopics", (), {}),
                ForumTopicsSlice=type("ForumTopicsSlice", (), {}),
            ),
        ),
    )
else:

    def _raise_pyrogram_import_error() -> None:
        return None


# kurigram 2.2.10+ 移除了 pyrogram.storage.MemoryStorage。单独导入该类，
# 避免它的缺失连带让上面整块导入失败、把真实类型静默替换为占位实现
# （表现为各种「X() takes no arguments」的误导性报错）。
_MEMORY_STORAGE_IMPORT_ERROR: Exception | None = None

if _PYROGRAM_IMPORT_ERROR is None:
    try:
        from pyrogram.storage import MemoryStorage
    except (ImportError, AttributeError):
        # kurigram >= 2.2.10 移除了 pyrogram.storage.MemoryStorage。
        # 优先使用原生 MemoryStorage；缺失时若 SQLiteStorage 具备 in_memory 能力则自动适配。
        import inspect
        from pathlib import Path

        try:
            from pyrogram.storage.sqlite_storage import SQLiteStorage

            sig = inspect.signature(SQLiteStorage.__init__)
            if "in_memory" not in sig.parameters:
                # Fail-closed: SQLiteStorage 不具备 2.2.10+ in_memory 能力，无法作为内存存储使用
                raise NotImplementedError(
                    "SQLiteStorage 不支持 in_memory 参数，无法创建有效的 MemoryStorage 适配器"
                )

            class MemoryStorage(SQLiteStorage):  # type: ignore[no-redef]
                """兼容 kurigram >= 2.2.10 的内存存储适配器。"""

                def __init__(
                    self,
                    name: str,
                    session_string: str | None = None,
                    workdir: Path | str | None = None,
                    **kwargs,
                ):
                    super().__init__(
                        name=name,
                        workdir=Path(workdir) if workdir else Path("."),
                        session_string=session_string,
                        in_memory=True,
                    )
        except Exception as inner_exc:
            _MEMORY_STORAGE_IMPORT_ERROR = inner_exc
            MemoryStorage = None
else:
    _MEMORY_STORAGE_IMPORT_ERROR = _PYROGRAM_IMPORT_ERROR


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
    if target_text == button_text:
        return True
    if target_text.isdigit() and button_text.isdigit():
        return False
    if target_text in button_text:
        return len(target_text) >= 2 or not target_text.isdigit()
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


# 会话/授权失效的错误码标记。与账号状态检测共用同一集合，避免同错不同判。
_SESSION_INVALID_MARKERS = (
    "UNAUTHORIZED",
    "AUTH_KEY_UNREGISTERED",
    "AUTH_KEY_INVALID",
    "SESSION_REVOKED",
    "SESSION_EXPIRED",
    "USER_DEACTIVATED",
)


def is_session_invalid_error(err: BaseException | None) -> bool:
    """判定异常是否表示会话/授权失效（全项目唯一判定入口）。

    仅按文本判定，不依赖 pyrogram 异常类，因此在依赖导入降级为占位实现的运行环境
    同样可用。Telegram 错误码以大写形式内嵌在异常文本中（如
    ``[401 AUTH_KEY_UNREGISTERED]``），故统一转大写后匹配。
    """
    if err is None:
        return False
    text = str(err)
    if not text:
        return False
    upper = text.upper()
    return any(marker in upper for marker in _SESSION_INVALID_MARKERS)


def session_check_failure(err: BaseException) -> ConnectionError:
    """把 ``get_me()`` 校验失败区分为「会话失效」与「瞬态/解析故障」。

    只有授权类失败才标记为 ``Session invalid``；网络、超时、库版本不兼容等失败
    必须保持可区分，否则调用方会误判为需要重新登录。
    """
    if is_session_invalid_error(err):
        return ConnectionError(f"Session invalid: {err}")
    return ConnectionError(f"Session check failed ({type(err).__name__}): {err}")


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
    达到上限时原样抛出最后一次异常。
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


_ANIMATED_PHOTO_PATCHED = False


def patch_animated_chat_photo_parser() -> bool:
    """运行时 monkey-patch Pyrogram/Kurigram 的 ChatPhoto/Animation 解析器。

    若当前安装的库版本不存在该缺陷，保证为安全 no-op。
    在解析 video_sizes 时，防御性处理缺少 w/h 的 EmojiMarkup 与 StickerMarkup 实例，设置默认尺寸 0 或跳过。
    """
    global _ANIMATED_PHOTO_PATCHED
    if _ANIMATED_PHOTO_PATCHED:
        return True

    raw_types = getattr(raw, "types", None)
    if raw_types is not None:
        for markup_name in ("VideoSizeEmojiMarkup", "VideoSizeStickerMarkup"):
            cls = getattr(raw_types, markup_name, None)
            if cls is not None:
                if not hasattr(cls, "w"):
                    try:
                        cls.w = 0
                    except Exception:
                        pass
                if not hasattr(cls, "h"):
                    try:
                        cls.h = 0
                    except Exception:
                        pass

    # 针对 Animation._parse_chat_animation 防御缺少 w/h 与仅有 Markup 时的越界/异常崩溃。
    # 包装必须与原函数保持同一同步/异步契约：kurigram >= 2.2.10 起部分解析器改为协程函数，
    # 用同步函数顶替会让短路分支返回的裸 None 被调用方 await 拒收，抛出
    # TypeError: object NoneType can't be used in 'await' expression。
    anim_cls = getattr(types, "Animation", None)
    if anim_cls is not None and hasattr(anim_cls, "_parse_chat_animation"):
        _orig_parse_chat_anim = anim_cls._parse_chat_animation
        _parse_chat_anim_is_async = inspect.iscoroutinefunction(_orig_parse_chat_anim)

        def _guard_chat_animation(video):
            """仅当存在带合法 w/h 的真实 VideoSize 时才允许委托原实现。"""
            if video is None or not isinstance(video, getattr(raw_types, "Photo", ())):
                return False
            video_sizes = getattr(video, "video_sizes", None)
            if not video_sizes:
                return False

            for v in video_sizes:
                if type(v).__name__ in (
                    "VideoSizeEmojiMarkup",
                    "VideoSizeStickerMarkup",
                ):
                    continue
                if getattr(v, "w", 0) > 0 and getattr(v, "h", 0) > 0:
                    return True
            return False

        if _parse_chat_anim_is_async:

            @staticmethod
            async def _safe_parse_chat_animation(client, video, file_name):
                if not _guard_chat_animation(video):
                    return None
                try:
                    return await _orig_parse_chat_anim(client, video, file_name)
                except (IndexError, ValueError, AttributeError):
                    return None

        else:

            @staticmethod
            def _safe_parse_chat_animation(client, video, file_name):
                if not _guard_chat_animation(video):
                    return None
                try:
                    return _orig_parse_chat_anim(client, video, file_name)
                except (IndexError, ValueError, AttributeError):
                    return None

        anim_cls._parse_chat_animation = _safe_parse_chat_animation

    # 针对 ChatPhoto._parse 进行兜底防御（上游对空 sizes 的 Photo 会 IndexError）
    chat_photo_cls = getattr(types, "ChatPhoto", None)
    if chat_photo_cls is not None and hasattr(chat_photo_cls, "_parse"):
        _orig_chat_photo_parse = chat_photo_cls._parse
        _chat_photo_parse_is_async = inspect.iscoroutinefunction(_orig_chat_photo_parse)

        if _chat_photo_parse_is_async:

            @staticmethod
            async def _safe_chat_photo_parse(
                client, chat_photo, peer_id, peer_access_hash=0
            ):
                if chat_photo is None:
                    return None
                try:
                    return await _orig_chat_photo_parse(
                        client, chat_photo, peer_id, peer_access_hash
                    )
                except (AttributeError, ValueError, IndexError):
                    return None

        else:

            @staticmethod
            def _safe_chat_photo_parse(client, chat_photo, peer_id, peer_access_hash=0):
                if chat_photo is None:
                    return None
                try:
                    return _orig_chat_photo_parse(
                        client, chat_photo, peer_id, peer_access_hash
                    )
                except (AttributeError, ValueError, IndexError):
                    return None

        chat_photo_cls._parse = _safe_chat_photo_parse

    _ANIMATED_PHOTO_PATCHED = True
    return True


def patch_kurigram_compat() -> bool:
    """Kurigram 兼容补丁统一入口（幂等）。"""
    return patch_animated_chat_photo_parser()


async def safe_get_forum_topics(
    client: Any, chat_id: int | str, limit: int = 100
) -> list[Any]:
    """安全获取超级群组的论坛话题 (Forum Topics)。

    1. 优先适配 kurigram 2.2.26 的 raw.functions.messages.GetForumTopics(peer=peer, ...)；
    2. 兼容回退旧版 raw.functions.channels.GetForumTopics(channel=peer, ...)；
    3. 防御 ForumTopicDeleted 变体，只保留 ForumTopic 实例；
    4. 兼容 messages.ForumTopics 与 messages.ForumTopicsSlice 双容器；
    5. 若目标群组非 forum（返回 ChatNotModified / TopicIdInvalid / ChannelForumMissing / ForumClosed 等），安全降级返回空列表 []；
    6. 若 client 尚未连接或缺少 raw API，优雅返回 []。
    """
    if client is None:
        return []
    if hasattr(client, "is_connected") and not client.is_connected:
        return []
    if not hasattr(client, "invoke") or not hasattr(client, "resolve_peer"):
        return []

    messages_fn = getattr(getattr(raw, "functions", None), "messages", None)
    channels_fn = getattr(getattr(raw, "functions", None), "channels", None)

    has_messages_rpc = messages_fn is not None and hasattr(messages_fn, "GetForumTopics")
    has_channels_rpc = channels_fn is not None and hasattr(channels_fn, "GetForumTopics")

    if not has_messages_rpc and not has_channels_rpc:
        return []

    if hasattr(client, "get_chat"):
        try:
            chat = await client.get_chat(chat_id)
            if chat is not None and hasattr(chat, "is_forum") and not chat.is_forum:
                return []
        except Exception:
            pass

    try:
        peer = await client.resolve_peer(chat_id)
        if has_messages_rpc:
            req = messages_fn.GetForumTopics(
                peer=peer,
                offset_date=0,
                offset_id=0,
                offset_topic=0,
                limit=limit,
            )
        else:
            req = channels_fn.GetForumTopics(
                channel=peer,
                offset_date=0,
                offset_id=0,
                offset_topic=0,
                limit=limit,
            )
        res = await client.invoke(req)
    except Exception as exc:
        err_type = type(exc).__name__.lower()
        err_msg = str(exc).lower()
        expected_forum_errors = (
            "chatnotmodified",
            "topicidinvalid",
            "channelinvalid",
            "channelforummissing",
            "forumclosed",
        )
        if any(term in err_type for term in expected_forum_errors) or (
            "forum" in err_msg and any(w in err_msg for w in ("not", "closed", "missing", "disabled"))
        ):
            logger.debug("Chat %s is not a forum or topics unavailable: %s", chat_id, exc)
            return []
        logger.warning(
            "Unexpected error fetching forum topics for chat %s (%s: %s)",
            chat_id,
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        return []

    raw_topics = getattr(res, "topics", []) or []
    deleted_type = getattr(getattr(raw, "types", None), "ForumTopicDeleted", None)

    valid_topics = []
    for topic in raw_topics:
        if deleted_type is not None and isinstance(topic, deleted_type):
            continue
        if getattr(topic, "__class__", None).__name__ == "ForumTopicDeleted":
            continue
        # 防御缺少 top_message 属性引发的崩溃
        if hasattr(topic, "__dict__") and "top_message" not in topic.__dict__:
            try:
                topic.top_message = getattr(topic, "top_message", 0)
            except Exception:
                pass
        valid_topics.append(topic)

    return valid_topics




async def get_dc_session(
    client: Any,
    dc_id: int,
    export_authorization: bool = False,
    **kwargs: Any,
) -> Any:
    """获取指定 DC 的会话连接（兼容 kurigram 2.2.26 官方 Client.get_session 与老版本 inline_session）。

    注意：默认 export_authorization=False，避免在未授权阶段（如 QR 跨 DC 迁移未授权 candidate 阶段）
    错误调用 export_authorization 导致 AuthBytesInvalid / Unauthorized 异常。
    """
    if hasattr(client, "get_session") and callable(client.get_session):
        import inspect

        call_kwargs = dict(kwargs)
        try:
            sig = inspect.signature(client.get_session)
            has_var_keyword = any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            )
            if "export_authorization" in sig.parameters or has_var_keyword:
                call_kwargs.setdefault("export_authorization", export_authorization)
        except (ValueError, TypeError):
            call_kwargs.setdefault("export_authorization", export_authorization)
        return await client.get_session(dc_id, **call_kwargs)
    try:
        from pyrogram.methods.messages.inline_session import (
            get_session as _inline_get_session,
        )
        return await _inline_get_session(client, dc_id)
    except (ImportError, ModuleNotFoundError, AttributeError):
        pass
    sessions = getattr(client, "sessions", {}) or {}
    if dc_id in sessions:
        return sessions[dc_id]
    media_sessions = getattr(client, "media_sessions", {}) or {}
    if dc_id in media_sessions:
        return media_sessions[dc_id]
    raise RuntimeError(f"Cannot get session for DC {dc_id} on client")


# 模块导入时自动应用协议与解析补丁
try:
    patch_animated_chat_photo_parser()
except Exception:  # pragma: no cover
    pass

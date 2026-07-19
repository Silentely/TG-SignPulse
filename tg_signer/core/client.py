"""Client 生命周期与工厂（从 core 拆分）。"""
import asyncio
import json
import logging
import os
import pathlib
import random
import sqlite3
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from datetime import time as dt_time
from typing import (
    Any,
    BinaryIO,
    Generic,
    List,
    Optional,
    Type,
    TypeVar,
    Union,
)
from urllib import parse

import httpx
from croniter import CroniterBadCronError, croniter
from pydantic import BaseModel, Field, ValidationError

try:
    from pydantic import ConfigDict
except ImportError:  # pragma: no cover - pydantic v1 compatibility
    ConfigDict = None

from tg_signer.config import (
    ActionT,
    BaseJSONConfig,
    ChooseOptionByImageAction,
    ClickButtonByCalculationProblemAction,
    ClickKeyboardByTextAction,
    HttpCallback,
    KeywordNotifyAction,
    MatchConfig,
    MonitorConfig,
    ReplyByCalculationProblemAction,
    ReplyByImageRecognitionAction,
    SendDiceAction,
    SendTextAction,
    SignChatV3,
    SignConfigV3,
    SupportAction,
    UDPForward,
)

_PYDANTIC_V2 = hasattr(BaseModel, "model_validate")

from tg_signer.ai_tools import AITools, OpenAIConfigManager  # noqa: E402
from tg_signer.async_utils import create_logged_task  # noqa: E402
from tg_signer.compat import (  # noqa: E402
    _PYROGRAM_IMPORT_ERROR,
    BaseClient,
    Chat,
    ChatMembersFilter,
    ChatType,
    EditedMessageHandler,
    InlineKeyboardMarkup,
    MemoryStorage,
    Message,
    MessageHandler,
    Object,
    ReplyKeyboardMarkup,
    Session,
    User,
    _raise_pyrogram_import_error,
    errors,
    filters,
    idle,
    raw,
)
from tg_signer.log_utils import (  # noqa: E402
    safe_ai_request_meta,
    safe_ai_result_meta,
    safe_text_preview,
)
from tg_signer.notification.server_chan import sc_send  # noqa: E402
from tg_signer.utils import UserInput, print_to_user  # noqa: E402

# Monkeypatch sqlite3.connect to increase default timeout
_original_sqlite3_connect = sqlite3.connect


def _patched_sqlite3_connect(*args, **kwargs):
    # Force timeout to be at least 10 seconds, even if Pyrogram sets it to 1
    if "timeout" in kwargs:
        if kwargs["timeout"] < 30:
            kwargs["timeout"] = 30
    else:
        kwargs["timeout"] = 30
    return _original_sqlite3_connect(*args, **kwargs)


sqlite3.connect = _patched_sqlite3_connect

# Monkeypatch pyrogram FileStorage.open to skip VACUUM (causes exclusive locks)
# and enable WAL mode + busy_timeout immediately on open
try:
    from pyrogram.storage.file_storage import FileStorage as _PyrogramFileStorage

    _original_file_storage_open = _PyrogramFileStorage.open

    async def _patched_file_storage_open(self):
        path = self.database
        file_exists = path.is_file()

        self.conn = _original_sqlite3_connect(str(path), timeout=30, check_same_thread=False)

        # Enable WAL mode and busy_timeout BEFORE any writes
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA busy_timeout=30000")
        except Exception:
            pass

        if not file_exists:
            self.create()
        else:
            self.update()

        # Skip VACUUM - it requires exclusive lock and blocks other connections.
        # WAL mode handles fragmentation well enough for session files.

    _PyrogramFileStorage.open = _patched_file_storage_open
except Exception:
    pass

# Monkeypatch pyrogram.Client.invoke to add backpressure and retry logic for updates
_original_invoke = BaseClient.invoke
_get_channel_diff_semaphore = asyncio.Semaphore(50)


def _read_positive_float_env(name: str, default: float, minimum: float = 1.0) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(float(raw), minimum)
    except (TypeError, ValueError):
        return default


def _read_positive_int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(int(raw), minimum)
    except (TypeError, ValueError):
        return default


async def _patched_invoke(self, query, *args, **kwargs):
    if isinstance(query, (raw.functions.updates.GetChannelDifference, raw.functions.updates.GetDifference)):
        # Disable Pyrogram's internal sleep and retry mechanisms to prevent blocking the semaphore indefinitely
        kwargs.setdefault("sleep_threshold", 0)
        kwargs["retries"] = 0
        kwargs.setdefault("timeout", 5.0)

        async with _get_channel_diff_semaphore:
            max_retries = 2
            base_delay = 1.0
            for attempt in range(max_retries + 1):
                try:
                    return await _original_invoke(self, query, *args, **kwargs)
                except Exception as e:
                    err_str = str(e).lower()
                    if isinstance(e, asyncio.TimeoutError) or "timeout" in err_str or "connection" in err_str or "flood" in err_str or "network" in err_str:
                        if attempt < max_retries:
                            delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                            if "flood" in err_str and hasattr(e, "value"):
                                delay = min(e.value, 3.0)  # Wait for a shorter time, max 3 seconds
                            await asyncio.sleep(delay)
                            continue

                        logger.warning(f"Drop updates for {type(query).__name__} due to error: {e}")

                        if isinstance(query, raw.functions.updates.GetChannelDifference):
                            from pyrogram.raw.types.updates import (
                                ChannelDifferenceEmpty,
                            )
                            return ChannelDifferenceEmpty(pts=query.pts, timeout=0, final=True)
                        elif isinstance(query, raw.functions.updates.GetDifference):
                            from pyrogram.raw.types.updates import DifferenceEmpty
                            return DifferenceEmpty(date=query.date, seq=query.pts)
                    raise
    return await _original_invoke(self, query, *args, **kwargs)

BaseClient.invoke = _patched_invoke

logger = logging.getLogger("tg-signer")

DICE_EMOJIS = ("🎲", "🎯", "🏀", "⚽", "🎳", "🎰")

Session.START_TIMEOUT = 5  # 原始超时时间为2秒，但一些代理访问会超时，所以这里调大一点

OPENAI_USE_PROMPT = "当前任务需要配置大模型，请确保运行前正确设置`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`等环境变量，或通过`tg-signer llm-config`持久化配置。"


def _is_callback_data_invalid(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "data_invalid" in text or "encrypted data is invalid" in text


def _is_callback_confirmation_unavailable(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "channel_invalid" in text or "peer_id_invalid" in text


def readable_message(message: Message):
    s = "\nMessage: "
    s += f"\n  text: {message.text or ''}"
    if message.photo:
        s += f"\n  图片: [({message.photo.width}x{message.photo.height}) {message.caption}]"
    if message.reply_markup:
        if isinstance(message.reply_markup, InlineKeyboardMarkup):
            s += "\n  InlineKeyboard: "
            for row in message.reply_markup.inline_keyboard:
                s += "\n   "
                for button in row:
                    s += f"{button.text} | "
        elif isinstance(message.reply_markup, ReplyKeyboardMarkup):
            s += "\n  ReplyKeyboard: "
            for row in message.reply_markup.keyboard:
                s += "\n   "
                for button in row:
                    s += f"{getattr(button, 'text', str(button))} | "
    return s


def readable_chat(chat: Chat):
    if chat.type == ChatType.BOT:
        type_ = "BOT"
    elif chat.type == ChatType.GROUP:
        type_ = "群组"
    elif chat.type == ChatType.SUPERGROUP:
        type_ = "超级群组"
    elif chat.type == ChatType.CHANNEL:
        type_ = "频道"
    else:
        type_ = "个人"

    none_or_dash = lambda x: x or "-"  # noqa: E731

    return f"id: {chat.id}, username: {none_or_dash(chat.username)}, title: {none_or_dash(chat.title)}, type: {type_}, name: {none_or_dash(chat.first_name)}"


_CLIENT_INSTANCES: dict[str, "Client"] = {}

# reference counts and async locks for shared client lifecycle management
# Keyed by account name. Use asyncio locks to serialize start/stop operations
# so multiple coroutines in the same process can safely share one Client.
_CLIENT_REFS: defaultdict[str, int] = defaultdict(int)
_CLIENT_ASYNC_LOCKS: dict[str, asyncio.Lock] = {}


class Client(BaseClient):
    def __init__(self, name: str, *args, **kwargs):
        if _PYROGRAM_IMPORT_ERROR is not None:
            _raise_pyrogram_import_error()
        key = kwargs.pop("key", None)
        self._tg_signpulse_no_updates = kwargs.get("no_updates")
        super().__init__(name, *args, **kwargs)
        self.key = key or str(pathlib.Path(self.workdir).joinpath(self.name).resolve())
        if self.in_memory and not self.session_string:
            self.load_session_string()
            self.storage = MemoryStorage(self.name, self.session_string)

    async def __aenter__(self):
        lock = _CLIENT_ASYNC_LOCKS.get(self.key)
        if lock is None:
            lock = asyncio.Lock()
            _CLIENT_ASYNC_LOCKS[self.key] = lock
        async with lock:
            _CLIENT_REFS[self.key] += 1
            if _CLIENT_REFS[self.key] == 1:
                # Retry loop for database locks
                max_retries = 5
                for attempt in range(max_retries):
                    try:
                        if not self.is_connected:
                            is_authorized = await self.connect()
                            if not is_authorized:
                                raise ConnectionError("Session invalid: unauthorized")

                        try:
                            self.me = await self.get_me()
                        except Exception as e:
                            # Prevent interactive login attempt
                            raise ConnectionError(f"Session invalid: {e}")

                        try:
                            await self.invoke(raw.functions.updates.GetState())
                        except ConnectionError as e:
                            if "already started" not in str(e).lower():
                                raise e
                        try:
                            if not getattr(self, "is_initialized", False):
                                await self.initialize()
                        except ConnectionError as e:
                            if "already initialized" not in str(e).lower():
                                raise e

                        # Enable WAL mode after start (redundant with patch but safe)
                        if hasattr(self, "storage") and hasattr(self.storage, "conn"):
                            try:
                                self.storage.conn.execute("PRAGMA journal_mode=WAL")
                                self.storage.conn.execute("PRAGMA busy_timeout=30000")
                            except Exception as e:
                                logger.error(f"Failed to enable WAL mode: {e}")

                        # Success! Break loop
                        break

                    except Exception as e:
                        # If this is a database lock and we have retries left, wait and retry
                        is_locked = "database is locked" in str(e).lower()
                        if is_locked and attempt < max_retries - 1:
                            # Cleanup before retry
                            try:
                                if self.is_connected:
                                    await self.stop()
                            except Exception:
                                pass

                            wait_time = 2 + (attempt * 3)
                            logger.warning(f"Database locked when starting client {self.name}, retrying in {wait_time}s... ({attempt + 1}/{max_retries})")
                            await asyncio.sleep(wait_time)
                            continue

                        # If execution reaches here, it's a fatal error or retries exhausted
                        # Rollback the ref count
                        _CLIENT_REFS[self.key] -= 1
                        if _CLIENT_REFS[self.key] <= 0:
                            _CLIENT_REFS.pop(self.key, None)
                            _CLIENT_INSTANCES.pop(self.key, None)
                            try:
                                await self.stop()
                            except Exception:
                                pass
                        raise e
            return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        lock = _CLIENT_ASYNC_LOCKS.get(self.key)
        if lock is None:
            return
        async with lock:
            _CLIENT_REFS[self.key] -= 1
            if _CLIENT_REFS[self.key] <= 0:
                _CLIENT_REFS[self.key] = 0
                try:
                    await self.stop()
                except Exception:
                    pass
                # Remove from cache when no longer in use to prevent memory growth
                _CLIENT_INSTANCES.pop(self.key, None)
                _CLIENT_REFS.pop(self.key, None)
                _CLIENT_ASYNC_LOCKS.pop(self.key, None)

    @property
    def session_string_file(self):
        return self.workdir / (self.name + ".session_string")

    async def save_session_string(self):
        with open(self.session_string_file, "w") as fp:
            fp.write(await self.export_session_string())

    def load_session_string(self):
        logger.info("Loading session_string from local file.")
        if self.session_string_file.is_file():
            with open(self.session_string_file, "r") as fp:
                self.session_string = fp.read()
                logger.info("The session_string has been loaded.")
        return self.session_string

    async def log_out(
        self,
    ):
        await super().log_out()
        if self.session_string_file.is_file():
            os.remove(self.session_string_file)


def get_api_config():
    api_id_env = os.environ.get("TG_API_ID")
    api_hash_env = os.environ.get("TG_API_HASH")

    api_id = 611335
    if api_id_env:
        try:
            api_id = int(api_id_env)
        except (TypeError, ValueError):
            pass

    if isinstance(api_hash_env, str) and api_hash_env.strip():
        api_hash = api_hash_env.strip()
    else:
        api_hash = "d524b414d21f4d37f08684c1df41ac9c"

    return api_id, api_hash


def get_proxy(proxy: str = None):
    proxy = proxy or os.environ.get("TG_PROXY")
    if proxy:
        r = parse.urlparse(proxy)
        return {
            "scheme": r.scheme,
            "hostname": r.hostname,
            "port": r.port,
            "username": r.username,
            "password": r.password,
        }
    return None


def get_client(
    name: str = "my_account",
    proxy: dict = None,
    workdir: Union[str, pathlib.Path] = ".",
    session_string: str = None,
    in_memory: bool = False,
    api_id: int = None,
    api_hash: str = None,
    **kwargs,
) -> Client:
    proxy = proxy or get_proxy()
    if not api_id or not api_hash:
        _api_id, _api_hash = get_api_config()
        api_id = api_id or _api_id
        api_hash = api_hash or _api_hash

    # Use separate cache keys for in-memory vs file-mode clients to prevent
    # database lock conflicts when keyword monitor (file mode) and manual
    # task execution (in-memory mode) run on the same account
    base_key = str(pathlib.Path(workdir).joinpath(name).resolve())
    key = f"{base_key}::memory" if (in_memory and session_string) else base_key

    if key in _CLIENT_INSTANCES:
        existing = _CLIENT_INSTANCES[key]
        requested_no_updates = kwargs.get("no_updates")
        existing_no_updates = getattr(existing, "_tg_signpulse_no_updates", None)
        refs = _CLIENT_REFS.get(key, 0)
        if (
            requested_no_updates is not None
            and existing_no_updates is not None
            and requested_no_updates != existing_no_updates
            and refs <= 0
            and not getattr(existing, "is_connected", False)
        ):
            _CLIENT_INSTANCES.pop(key, None)
        else:
            return existing
    client = Client(
        name,
        api_id=api_id,
        api_hash=api_hash,
        proxy=proxy,
        workdir=workdir,
        session_string=session_string,
        in_memory=in_memory,
        key=key,
        **kwargs,
    )
    _CLIENT_INSTANCES[key] = client
    return client


async def close_client_by_name(name: str, workdir: Union[str, pathlib.Path] = "."):
    """
    Forcefully close a client instance by its name and release resources.
    """
    key = str(pathlib.Path(workdir).joinpath(name).resolve())

    # Check if we have a lock for this client
    lock = _CLIENT_ASYNC_LOCKS.get(key)
    if lock:
        # Acquire the lock to ensure we have exclusive access
        # Note: This might block if a task is running.
        # If we want to forceful kill, we might skip this, but that's dangerous.
        # For deletion, waiting a moment is acceptable.
        try:
            # Try to acquire with timeout to avoid deadlocks if something is stuck
            await asyncio.wait_for(lock.acquire(), timeout=5.0)
            try:
                # Reset references to 0 to ensure proper cleanup
                _CLIENT_REFS[key] = 0
            finally:
                # Even if we manipulated refs, release the lock we just acquired
                lock.release()
        except asyncio.TimeoutError:
            logger.warning(
                f"Timeout waiting for lock on client {name}, proceeding with forceful cleanup"
            )
            _CLIENT_REFS[key] = 0

    client = _CLIENT_INSTANCES.get(key)
    if client:
        try:
            if client.is_connected:
                await client.stop()
        except Exception as e:
            logger.warning(f"Error stopping client {name}: {e}")
        finally:
            _CLIENT_INSTANCES.pop(key, None)

    # Clean up locks
    if key in _CLIENT_ASYNC_LOCKS:
        _CLIENT_ASYNC_LOCKS.pop(key, None)
    if key in _CLIENT_REFS:
        _CLIENT_REFS.pop(key, None)


def get_task_timezone():
    """任务时区：TZ / APP_TIMEZONE，默认 Asia/Hong_Kong（与 UTC+8 一致）。"""
    tz_name = (
        (os.environ.get("TZ") or os.environ.get("APP_TIMEZONE") or "Asia/Hong_Kong")
        .strip()
        or "Asia/Hong_Kong"
    )
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(tz_name)
    except Exception:
        return timezone(timedelta(hours=8))


def get_now():
    """当前任务时区时间（默认香港/UTC+8，可被 TZ/APP_TIMEZONE 覆盖）。"""
    return datetime.now(tz=get_task_timezone())


def make_dirs(path: pathlib.Path, exist_ok=True):
    path = pathlib.Path(path)
    if not path.is_dir():
        os.makedirs(path, exist_ok=exist_ok)
    return path



# 兼容：worker 需要的 re-export 标记

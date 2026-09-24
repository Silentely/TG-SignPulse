"""Client 生命周期与工厂（从 core 拆分）。"""

import asyncio
import importlib
import inspect
import logging
import os
import pathlib
import random
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import (
    Union,
)
from urllib import parse

from pydantic import BaseModel

try:
    from pydantic import ConfigDict
except ImportError:  # pragma: no cover - pydantic v1 compatibility
    ConfigDict = None


_PYDANTIC_V2 = hasattr(BaseModel, "model_validate")

from tg_signer.compat import (  # noqa: E402
    _PYROGRAM_IMPORT_ERROR,
    BaseClient,
    Chat,
    ChatType,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    Session,
    _raise_pyrogram_import_error,
    is_valid_session_string,
    patch_kurigram_compat,
    raw,
    session_check_failure,
)
from tg_signer.utils import read_positive_float_env, read_positive_int_env  # noqa: E402

patch_kurigram_compat()

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

# 会话存储的 open() 补丁：kurigram 的文件会话仍会在每次 open 时执行
# PRAGMA journal_mode=DELETE + VACUUM（VACUUM 需要独占锁，会阻塞同账号其他客户端），
# 且连接超时仅 1 秒。这里统一改为 WAL + busy_timeout 并跳过 VACUUM。
#
# 存储类在 kurigram 2.2.10 起由 pyrogram.storage.file_storage.FileStorage 迁移为
# pyrogram.storage.sqlite_storage.SQLiteStorage，且 create()/update() 由同步改为协程；
# 因此按实际可用模块解析类，并保持原同步/异步契约调用生命周期方法。
# 项目钉死 kurigram==2.2.26（file_storage 模块已不存在），仅保留 SQLiteStorage 候选；
# 2.2.26 虽新增了构造参数 use_wal，但 Client 不会传入、且上游 open() 仍会执行 VACUUM，
# 因此本补丁（WAL + busy_timeout + 跳过 VACUUM）依然必要，不能以原生 use_wal 取代。
# 若候选类不可用，必须显式告警而不是静默降级，避免补丁失效无人察觉。
_STORAGE_CLASS_CANDIDATES = (
    ("pyrogram.storage.sqlite_storage", "SQLiteStorage"),
)


def _patch_storage_open(storage_cls) -> None:
    original_open = storage_cls.open

    async def _patched_open(self):
        # 内存存储无文件、无跨进程锁竞争，保持上游实现
        if getattr(self, "in_memory", False):
            return await original_open(self)

        path = self.database
        file_exists = hasattr(path, "is_file") and path.is_file()

        self.conn = _original_sqlite3_connect(
            str(path), timeout=30, check_same_thread=False
        )

        # 任何写入前先启用 WAL 与 busy_timeout
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA busy_timeout=30000")
        except Exception as exc:
            logger.warning("会话存储启用 WAL 失败: %s", exc)

        # create()/update() 在 kurigram 2.2.10+ 为协程，旧版本为同步方法
        result = self.create() if not file_exists else self.update()
        if inspect.isawaitable(result):
            await result

        # 跳过 VACUUM：需要独占锁，会阻塞同账号其他客户端的会话库访问；
        # WAL 模式足以应对碎片问题

    storage_cls.open = _patched_open


def _install_storage_open_patch() -> bool:
    patched = False
    for module_path, class_name in _STORAGE_CLASS_CANDIDATES:
        try:
            module = importlib.import_module(module_path)
        except ImportError:
            continue
        storage_cls = getattr(module, class_name, None)
        if storage_cls is None or not hasattr(storage_cls, "open"):
            continue
        _patch_storage_open(storage_cls)
        patched = True
    if not patched:
        logging.getLogger("tg-signer").warning(
            "未能定位会话存储类，WAL/busy_timeout 与跳过 VACUUM 的优化未生效"
            "（候选: %s）",
            ", ".join(f"{m}.{c}" for m, c in _STORAGE_CLASS_CANDIDATES),
        )
    return patched


_install_storage_open_patch()

# Monkeypatch pyrogram.Client.invoke to add backpressure and retry logic for updates
_original_invoke = BaseClient.invoke
_get_channel_diff_semaphore = asyncio.Semaphore(50)


async def _patched_invoke(self, query, *args, **kwargs):
    if isinstance(
        query,
        (
            raw.functions.updates.GetChannelDifference,
            raw.functions.updates.GetDifference,
        ),
    ):
        # Disable Pyrogram's internal sleep and retry mechanisms to prevent blocking the semaphore indefinitely
        kwargs.setdefault("sleep_threshold", 0)
        # Pyrogram Session.invoke loops `for attempt in range(1, retries + 1)`.
        # Passing retries=0 causes an empty range and raises TimeoutError immediately without attempting even once.
        # Must be at least 1 so it actually executes the network request.
        invoke_retries = read_positive_int_env("TG_UPDATES_INVOKE_RETRIES", 1, minimum=1)
        kwargs["retries"] = invoke_retries
        updates_timeout = read_positive_float_env("TG_UPDATES_TIMEOUT", 10.0, minimum=2.0)
        kwargs.setdefault("timeout", updates_timeout)

        async with _get_channel_diff_semaphore:
            max_retries = read_positive_int_env("TG_UPDATES_MAX_RETRIES", 2, minimum=0)
            base_delay = 1.0
            for attempt in range(max_retries + 1):
                try:
                    return await _original_invoke(self, query, *args, **kwargs)
                except Exception as e:
                    err_str = str(e).lower()
                    if (
                        isinstance(e, asyncio.TimeoutError)
                        or "timeout" in err_str
                        or "connection" in err_str
                        or "flood" in err_str
                        or "network" in err_str
                    ):
                        if attempt < max_retries:
                            delay = base_delay * (2**attempt) + random.uniform(0, 1)
                            if "flood" in err_str and hasattr(e, "value"):
                                delay = min(
                                    e.value, 3.0
                                )  # Wait for a shorter time, max 3 seconds
                            await asyncio.sleep(delay)
                            continue

                        logger.warning(
                            "Drop updates for %s due to error: %s",
                            type(query).__name__,
                            e,
                        )

                        if isinstance(
                            query, raw.functions.updates.GetChannelDifference
                        ):
                            from pyrogram.raw.types.updates import (
                                ChannelDifferenceEmpty,
                            )

                            return ChannelDifferenceEmpty(
                                pts=query.pts, timeout=0, final=True
                            )
                        elif isinstance(query, raw.functions.updates.GetDifference):
                            from pyrogram.raw.types.updates import DifferenceEmpty

                            return DifferenceEmpty(date=query.date, seq=query.pts)
                    raise
    return await _original_invoke(self, query, *args, **kwargs)


BaseClient.invoke = _patched_invoke

logger = logging.getLogger("tg-signer")

DICE_EMOJIS = ("🎲", "🎯", "🏀", "⚽", "🎳", "🎰")

# 会话握手超时：与 kurigram 2.2.26 上游默认值一致，显式保留以防上游调小后
# 慢速代理环境出现启动超时（原值为 2s，代理场景偏紧）
Session.START_TIMEOUT = 5

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


def is_account_client_active(
    name: str, workdir: Union[str, pathlib.Path] = None
) -> bool:
    """检查指定账号是否有活跃的 Client 实例在运行中 (_CLIENT_REFS > 0)。"""
    # 直接支持按 account_name 检索（单测 mock 或以名字为键）
    if _CLIENT_REFS.get(name, 0) > 0:
        return True

    expected_base = None
    if workdir is not None:
        try:
            expected_base = str(pathlib.Path(workdir).joinpath(name).resolve())
        except Exception:
            expected_base = None

    for key, count in list(_CLIENT_REFS.items()):
        if count <= 0:
            continue
        if key == name or key.startswith(f"{name}::"):
            return True
        if expected_base and (
            key == expected_base or key.startswith(f"{expected_base}::")
        ):
            return True
        try:
            p = pathlib.Path(key.split("::")[0])
            if p.stem == name or p.name == name:
                return True
        except Exception:
            pass
    return False


class Client(BaseClient):
    def __init__(self, name: str, *args, **kwargs):
        if _PYROGRAM_IMPORT_ERROR is not None:
            _raise_pyrogram_import_error()
        key = kwargs.pop("key", None)
        self._tg_signpulse_no_updates = kwargs.get("no_updates")
        # in_memory 模式且未显式提供 session_string 时，先从会话目录预加载并校验，
        # 再由父类原生装配 SQLiteStorage(in_memory=True, session_string=...)
        # （kurigram >= 2.2.10 原生能力，见 pyrogram/client.py 存储装配段）。
        # 必须在 super().__init__() 之前注入：父类据 session_string 决定存储类型。
        if kwargs.get("in_memory") and not kwargs.get("session_string"):
            loaded = self._read_validated_session_string_file(
                name, kwargs.get("workdir") or "."
            )
            if loaded:
                kwargs["session_string"] = loaded
        super().__init__(name, *args, **kwargs)
        self.key = key or str(pathlib.Path(self.workdir).joinpath(self.name).resolve())

    @staticmethod
    def _read_validated_session_string_file(
        name: str, workdir: Union[str, pathlib.Path]
    ) -> Union[str, None]:
        """读取并校验 `<workdir>/<name>.session_string` 缓存文件。

        校验逻辑与面板侧保持一致（tg_signer.compat.is_valid_session_string）：
        历史错误导出曾把超长坏串落盘成缓存，直接注入内存存储会在上游解码阶段抛
        binascii.Error / struct.error 使任务无自愈地全失败。坏串按缓存失效处理：
        删除文件、告警、返回 None 让调用方走明确的缺参报错路径。
        """
        path = pathlib.Path(workdir) / f"{name}.session_string"
        if not path.is_file():
            return None
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning("读取 session_string 缓存失败 %s: %s", path, exc)
            return None
        if not content:
            return None
        if not is_valid_session_string(content):
            logger.warning(
                "session_string 缓存损坏或为不受支持的格式，已删除并按缺失处理: %s",
                path,
            )
            try:
                path.unlink()
            except OSError:
                pass
            return None
        logger.info("从本地文件加载 session_string。")
        return content

    async def __aenter__(self):
        lock = _CLIENT_ASYNC_LOCKS.get(self.key)
        if lock is None:
            lock = asyncio.Lock()
            _CLIENT_ASYNC_LOCKS[self.key] = lock
        async with lock:
            _CLIENT_REFS[self.key] += 1
            if _CLIENT_REFS[self.key] == 1:
                # 内存模式没有任何可用 session_string 时，空库 connect() 同样返回 False。
                # 必须与真正的「会话失效」区分：否则上层会把配置缺失误判为账号需重新登录。
                # 消息刻意不含 "Session invalid" 字样，避免被失效判定链路误捕获。
                if self.in_memory and not self.session_string:
                    _CLIENT_REFS[self.key] -= 1
                    if _CLIENT_REFS[self.key] <= 0:
                        _CLIENT_REFS.pop(self.key, None)
                        _CLIENT_INSTANCES.pop(self.key, None)
                    raise ConnectionError(
                        "No session_string available for in-memory mode: expected "
                        f"{self.session_string_file} or an explicit session_string"
                    )
                # Retry loop for database locks
                max_retries = 5
                connected_ok = False
                try:
                    for attempt in range(max_retries):
                        try:
                            if not self.is_connected:
                                is_authorized = await self.connect()
                                if not is_authorized:
                                    raise ConnectionError(
                                        "Session invalid: unauthorized"
                                    )

                            try:
                                self.me = await self.get_me()
                            except Exception as e:
                                # 阻止交互式登录，并把会话失效与瞬态/解析故障区分开：
                                # 后者若标记为 Session invalid，上层会误判为需要重新登录
                                raise session_check_failure(e) from e

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
                            if hasattr(self, "storage") and hasattr(
                                self.storage, "conn"
                            ):
                                try:
                                    self.storage.conn.execute("PRAGMA journal_mode=WAL")
                                    self.storage.conn.execute(
                                        "PRAGMA busy_timeout=30000"
                                    )
                                except Exception as e:
                                    logger.error("启用 WAL 模式失败: %s", e)

                            # Success! Break loop
                            connected_ok = True
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

                                # SQLite 锁等待用线性退避（连接启动场景，与瞬态网络
                                # 错误的指数退避 compute_backoff 刻意区分）
                                wait_time = 2 + (attempt * 3)
                                logger.warning(
                                    "Database locked when starting client %s, retrying in %ss... (%s/%s)",
                                    self.name,
                                    wait_time,
                                    attempt + 1,
                                    max_retries,
                                )
                                await asyncio.sleep(wait_time)
                                continue

                            raise e
                except BaseException as exc:
                    # CancelledError or any other fatal error/exhausted retries: rollback ref count
                    if not connected_ok:
                        _CLIENT_REFS[self.key] -= 1
                        if _CLIENT_REFS[self.key] <= 0:
                            _CLIENT_REFS.pop(self.key, None)
                            _CLIENT_INSTANCES.pop(self.key, None)
                            try:
                                if getattr(self, "is_connected", False):
                                    await self.stop()
                            except Exception:
                                pass
                    raise exc
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
                # 锁保留在字典中：若在此处弹出，退出与下一次进入将持有不同锁对象，
                # 并发 __aenter__ 会在 stop() 尚未完成时新建锁并 connect()，破坏互斥。
                # 锁按账号 key 常驻，数量有界且开销极小。

    @property
    def session_string_file(self):
        return self.workdir / (self.name + ".session_string")

    async def save_session_string(self):
        with open(self.session_string_file, "w") as fp:
            fp.write(await self.export_session_string())

    def load_session_string(self):
        """从会话目录加载 session_string（带格式校验，坏串按缓存失效处理）。

        与 __init__ 的预加载共用同一判定：仅当文件内容可被上游存储解码时才赋值，
        否则删除坏缓存并保持 session_string 为 None。
        """
        loaded = self._read_validated_session_string_file(self.name, self.workdir)
        if loaded:
            self.session_string = loaded
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
    raw = proxy or os.environ.get("TG_PROXY")
    if not raw or not isinstance(raw, str):
        return None
    val = raw.strip()
    if not val:
        return None
    if "://" not in val:
        if "@" in val:
            val = f"socks5://{val}"
        else:
            parts = val.split(":")
            if len(parts) == 2:
                val = f"socks5://{parts[0]}:{parts[1]}"
            elif len(parts) == 4:
                val = f"socks5://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
            else:
                val = f"socks5://{val}"
    try:
        r = parse.urlparse(val)
        port = r.port
    except (ValueError, AttributeError):
        return None
    scheme = (r.scheme or "").lower()
    if not (scheme in {"http", "https", "socks4", "socks5"} and r.hostname and port):
        return None
    if not (1 <= port <= 65535):
        return None
    return {
        "scheme": scheme,
        "hostname": r.hostname,
        "port": port,
        "username": r.username,
        "password": r.password,
    }


def get_client(
    name: str = "my_account",
    proxy: dict = None,
    workdir: Union[str, pathlib.Path] = ".",
    session_string: str = None,
    in_memory: bool = False,
    api_id: int = None,
    api_hash: str = None,
    device_model: str = None,
    system_version: str = None,
    app_version: str = None,
    lang_code: str = None,
    system_lang_code: str = None,
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

    extra_device_kwargs = {}
    if device_model is not None:
        extra_device_kwargs["device_model"] = device_model
    if system_version is not None:
        extra_device_kwargs["system_version"] = system_version
    if app_version is not None:
        extra_device_kwargs["app_version"] = app_version
    if lang_code is not None:
        extra_device_kwargs["lang_code"] = lang_code
    if system_lang_code is not None:
        extra_device_kwargs["system_lang_code"] = system_lang_code

    if key in _CLIENT_INSTANCES:
        existing = _CLIENT_INSTANCES[key]
        requested_no_updates = kwargs.get("no_updates")
        existing_no_updates = getattr(existing, "_tg_signpulse_no_updates", None)
        refs = _CLIENT_REFS.get(key, 0)

        device_changed = any(
            getattr(existing, k, None) != v for k, v in extra_device_kwargs.items()
        )

        if (
            (
                (
                    requested_no_updates is not None
                    and existing_no_updates is not None
                    and requested_no_updates != existing_no_updates
                )
                or device_changed
            )
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
        **extra_device_kwargs,
        **kwargs,
    )
    _CLIENT_INSTANCES[key] = client
    return client


async def close_client_by_name(name: str, workdir: Union[str, pathlib.Path] = "."):
    """
    Forcefully close a client instance by its name and release resources.
    """
    base_key = str(pathlib.Path(workdir).joinpath(name).resolve())
    keys_to_clean = [
        k
        for k in list(_CLIENT_INSTANCES.keys())
        if k == base_key or k.startswith(f"{base_key}::")
    ]
    if not keys_to_clean:
        keys_to_clean = [base_key]

    for key in keys_to_clean:
        lock = _CLIENT_ASYNC_LOCKS.get(key)
        acquired = False
        if lock:
            try:
                # Try to acquire with timeout to serialize cleanup
                await asyncio.wait_for(lock.acquire(), timeout=5.0)
                acquired = True
            except asyncio.TimeoutError:
                logger.warning(
                    "Timeout waiting for lock on client key %s, proceeding with forceful cleanup",
                    key,
                )
        try:
            _CLIENT_REFS[key] = 0
            client = _CLIENT_INSTANCES.get(key)
            if client:
                try:
                    if getattr(client, "is_connected", False):
                        await client.stop()
                except Exception as e:
                    logger.warning("停止客户端 %s 失败: %s", name, e)
                finally:
                    _CLIENT_INSTANCES.pop(key, None)
            _CLIENT_REFS.pop(key, None)
        finally:
            if acquired and lock:
                lock.release()
            if key in _CLIENT_ASYNC_LOCKS:
                _CLIENT_ASYNC_LOCKS.pop(key, None)


def get_task_timezone():
    """任务时区：TZ / APP_TIMEZONE，默认 Asia/Hong_Kong（与 UTC+8 一致）。"""
    tz_name = (
        os.environ.get("TZ") or os.environ.get("APP_TIMEZONE") or "Asia/Hong_Kong"
    ).strip() or "Asia/Hong_Kong"
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

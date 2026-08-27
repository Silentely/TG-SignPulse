"""
UserSigner / UserMonitor / BaseUserWorker 运行时实现。

Client 生命周期与工厂见 `tg_signer.core.client`（本模块不再重复定义）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
from typing import (
    Generic,
    Optional,
    Type,
    TypeVar,
    Union,
)

from tg_signer.ai_tools import AITools, OpenAIConfigManager, ai_cfg_signature
from tg_signer.compat import (
    _PYROGRAM_IMPORT_ERROR,
    ChatMembersFilter,
    Object,
    User,
    _raise_pyrogram_import_error,
    call_with_retry,
    raw,
)
from tg_signer.config import (
    BaseJSONConfig,
    SignConfigV3,
)

# Client 真源：生命周期与工厂
from tg_signer.core.client import (  # noqa: F401
    _CLIENT_ASYNC_LOCKS,
    _CLIENT_INSTANCES,
    _CLIENT_REFS,
    DICE_EMOJIS,
    OPENAI_USE_PROMPT,
    Client,
    _is_callback_confirmation_unavailable,
    _is_callback_data_invalid,
    _patched_invoke,
    _patched_sqlite3_connect,
    close_client_by_name,
    get_api_config,
    get_client,
    get_now,
    get_proxy,
    make_dirs,
    readable_chat,
    readable_message,
)
from tg_signer.core.context import UserSignerWorkerContext
from tg_signer.core.signer_actions import SignerActionsMixin
from tg_signer.core.signer_config import SignerConfigMixin
from tg_signer.core.signer_matchers import SignerMatchersMixin
from tg_signer.core.signer_runner import SignerRunnerMixin
from tg_signer.utils import (
    print_to_user,
)

# 与 CLI / client / 后端 TaskLogHandler 统一使用历史名 tg-signer，
# 避免过程日志打到另一 logger 导致面板 flow_logs 只有外壳行。
logger = logging.getLogger("tg-signer")


ConfigT = TypeVar("ConfigT", bound=BaseJSONConfig)


class BaseUserWorker(Generic[ConfigT]):
    _workdir = "."
    _tasks_dir = "tasks"
    cfg_cls: Type["ConfigT"] = BaseJSONConfig

    def __init__(
        self,
        task_name: str = None,
        session_dir: str = ".",
        account: str = "my_account",
        proxy=None,
        workdir=None,
        session_string: str = None,
        in_memory: bool = False,
        api_id: int = None,
        api_hash: str = None,
        no_updates: Optional[bool] = None,
        *,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        self.task_name = task_name or "my_task"
        self._session_dir = pathlib.Path(session_dir)
        self._account = account
        self._proxy = proxy
        if workdir:
            self._workdir = pathlib.Path(workdir)
        client_kwargs = {
            "workdir": self._session_dir,
            "session_string": session_string,
            "in_memory": in_memory,
            "api_id": api_id,
            "api_hash": api_hash,
            "loop": loop,
        }
        if no_updates is not None:
            client_kwargs["no_updates"] = no_updates

        self.app = get_client(
            account,
            proxy,
            **client_kwargs,
        )
        self.loop = self.app.loop
        self.user: Optional[User] = None
        self._config = None
        self._ai_tools: Optional[AITools] = None
        self._ai_cfg_signature: Optional[tuple[str, str, str]] = None
        self.context = self.ensure_ctx()

    def ensure_ctx(self):
        return {}

    async def _ensure_app_ready(self):
        if _PYROGRAM_IMPORT_ERROR is not None:
            _raise_pyrogram_import_error()

        if getattr(self.app, "is_connected", False):
            if not getattr(self.app, "is_initialized", False):
                try:
                    await self.app.initialize()
                except ConnectionError as exc:
                    if "already initialized" not in str(exc).lower():
                        raise
            return

        is_authorized = await self.app.connect()
        if not is_authorized:
            raise ConnectionError("Session invalid: unauthorized")

        try:
            self.me = await self.app.get_me()
        except Exception as exc:
            raise ConnectionError(f"Session invalid: {exc}") from exc

        try:
            await self.app.invoke(raw.functions.updates.GetState())
        except ConnectionError as exc:
            if "already started" not in str(exc).lower():
                raise

        if not getattr(self.app, "is_initialized", False):
            try:
                await self.app.initialize()
            except ConnectionError as exc:
                if "already initialized" not in str(exc).lower():
                    raise

    async def _call_with_retry(
        self,
        callback,
        *,
        operation: str,
        max_retries: int = 4,
    ):
        return await call_with_retry(
            callback,
            operation=operation,
            max_retries=max_retries,
            log=lambda level, msg: self.log(msg, level=level),
            reconnect=self._ensure_app_ready,
        )

    def app_run(self, coroutine=None):
        if coroutine is not None:
            run = self.loop.run_until_complete
            run(coroutine)
        else:
            self.app.run()

    @property
    def workdir(self) -> pathlib.Path:
        workdir = self._workdir
        make_dirs(workdir)
        return pathlib.Path(workdir)

    @property
    def tasks_dir(self):
        tasks_dir = self.workdir / self._tasks_dir
        make_dirs(tasks_dir)
        return pathlib.Path(tasks_dir)

    @property
    def task_dir(self):
        task_dir = self.tasks_dir / self.task_name
        make_dirs(task_dir)
        return task_dir

    def get_user_dir(self, user: User):
        user_dir = self.workdir / "users" / str(user.id)
        make_dirs(user_dir)
        return user_dir

    @property
    def config_file(self):
        return self.task_dir.joinpath("config.json")

    @property
    def config(self) -> ConfigT:
        return self._config or self.load_config()

    @config.setter
    def config(self, value):
        self._config = value

    def log(self, msg, level: str = "INFO", **kwargs):
        msg = f"账户「{self._account}」- 任务「{self.task_name}」: {msg}"
        if level.upper() == "INFO":
            logger.info(msg, **kwargs)
        elif level.upper() == "WARNING":
            logger.warning(msg, **kwargs)
        elif level.upper() == "ERROR":
            logger.error(msg, **kwargs)
        elif level.upper() == "CRITICAL":
            logger.critical(msg, **kwargs)
        else:
            logger.debug(msg, **kwargs)

    def ask_for_config(self):
        raise NotImplementedError

    def write_config(self, config: BaseJSONConfig):
        with open(self.config_file, "w", encoding="utf-8") as fp:
            json.dump(config.to_jsonable(), fp, ensure_ascii=False)

    def reconfig(self):
        config = self.ask_for_config()
        self.write_config(config)
        return config

    def load_config(self, cfg_cls: Type[ConfigT] = None) -> ConfigT:
        cfg_cls = cfg_cls or self.cfg_cls
        if not self.config_file.exists():
            config = self.reconfig()
        else:
            with open(self.config_file, "r", encoding="utf-8") as fp:
                config, from_old = cfg_cls.load(json.load(fp))
                if from_old:
                    self.write_config(config)
        self.config = config
        return config

    def get_task_list(self):
        signs = []
        for d in os.listdir(self.tasks_dir):
            if self.tasks_dir.joinpath(d).is_dir():
                signs.append(d)
        return signs

    def list_(self):
        print_to_user("已配置的任务：")
        for d in self.get_task_list():
            print_to_user(d)

    def set_me(self, user: User):
        self.user = user
        with open(
            self.get_user_dir(user).joinpath("me.json"), "w", encoding="utf-8"
        ) as fp:
            fp.write(str(user))

    async def login(self, num_of_dialogs=20, print_chat=True):
        self.log("开始登录...")
        app = self.app
        async with app:
            me = await app.get_me()
            self.set_me(me)
            latest_chats = []
            try:
                async for dialog in app.get_dialogs(num_of_dialogs):
                    try:
                        chat = getattr(dialog, "chat", None)
                        if chat is None:
                            self.log("get_dialogs 返回空 chat，已跳过", level="WARNING")
                            continue
                        chat_id = getattr(chat, "id", None)
                        if chat_id is None:
                            self.log("get_dialogs 返回 chat.id 为空，已跳过", level="WARNING")
                            continue
                        latest_chats.append(
                            {
                                "id": chat_id,
                                "title": chat.title,
                                "type": chat.type,
                                "username": chat.username,
                                "first_name": chat.first_name,
                                "last_name": chat.last_name,
                            }
                        )
                        if print_chat:
                            print_to_user(readable_chat(chat))
                        logger.debug(readable_chat(chat))
                    except Exception as e:
                        self.log(
                            f"处理 dialog 失败，已跳过: {type(e).__name__}: {e}",
                            level="WARNING",
                        )
                        continue
            except Exception as e:
                self.log(
                    f"get_dialogs 中断，返回已获取结果: {type(e).__name__}: {e}",
                    level="WARNING",
                )
            self.log(f"登录完成，获取到 {len(latest_chats)} 个对话")

            with open(
                self.get_user_dir(me).joinpath("latest_chats.json"),
                "w",
                encoding="utf-8",
            ) as fp:
                json.dump(
                    latest_chats,
                    fp,
                    indent=4,
                    default=Object.default,
                    ensure_ascii=False,
                )
            await self.app.save_session_string()

    async def logout(self):
        self.log("开始登出...")
        is_authorized = await self.app.connect()
        if not is_authorized:
            await self.app.storage.delete()
            return None
        return await self.app.log_out()

    async def send_message(
        self, chat_id: Union[int, str], text: str, delete_after: int = None, **kwargs
    ):
        """
        发送文本消息
        :param chat_id:
        :param text:
        :param delete_after: 秒, 发送消息后进行删除，``None`` 表示不删除, ``0`` 表示立即删除.
        :param kwargs:
        :return:
        """
        message = await self._call_with_retry(
            lambda: self.app.send_message(chat_id, text, **kwargs),
            operation=f"发送消息到 {chat_id}",
        )
        self.log(
            f"已发送文本消息到 {chat_id}: {text}"
            + (
                f" (thread_id={kwargs.get('message_thread_id')})"
                if kwargs.get("message_thread_id") is not None
                else ""
            )
        )
        if delete_after is not None:
            self.log(
                f"消息「{text}」将在 {delete_after} 秒后删除 (Chat {chat_id})"
            )
            self.log("等待删除...")
            await asyncio.sleep(delete_after)
            try:
                await message.delete()
                self.log(f"已删除消息「{text}」 (Chat {chat_id})")
            except Exception as exc:
                self.log(f"删除消息失败: {exc}", level="WARNING")
        return message

    async def send_dice(
        self,
        chat_id: Union[int, str],
        emoji: str = "🎲",
        delete_after: int = None,
        **kwargs,
    ):
        """
        发送DICE类型消息
        :param chat_id:
        :param emoji: Should be one of "🎲", "🎯", "🏀", "⚽", "🎳", or "🎰".
        :param delete_after:
        :param kwargs:
        :return:
        """
        emoji = emoji.strip()
        if emoji not in DICE_EMOJIS:
            self.log(
                f"骰子表情不合法，应为以下之一: {', '.join(DICE_EMOJIS)}",
                level="WARNING",
            )
        message = await self._call_with_retry(
            lambda: self.app.send_dice(chat_id, emoji, **kwargs),
            operation=f"发送骰子到 {chat_id}",
        )
        self.log(
            f"已发送骰子到 {chat_id}: {emoji}"
            + (
                f" (thread_id={kwargs.get('message_thread_id')})"
                if kwargs.get("message_thread_id") is not None
                else ""
            )
        )
        if message and delete_after is not None:
            self.log(
                f"骰子「{emoji}」将在 {delete_after} 秒后删除 (Chat {chat_id})"
            )
            self.log("等待删除...")
            await asyncio.sleep(delete_after)
            try:
                await message.delete()
                self.log(f"已删除骰子「{emoji}」 (Chat {chat_id})")
            except Exception as e:
                self.log(f"删除骰子消息失败: {e}", level="ERROR")
        return message

    async def search_members(
        self, chat_id: Union[int, str], query: str, admin=False, limit=10
    ):
        filter_ = ChatMembersFilter.SEARCH
        if admin:
            filter_ = ChatMembersFilter.ADMINISTRATORS
            query = ""
        async for member in self.app.get_chat_members(
            chat_id, query, limit=limit, filter=filter_
        ):
            yield member

    async def list_members(
        self, chat_id: Union[int, str], query: str = "", admin=False, limit=10
    ):
        async with self.app:
            async for member in self.search_members(chat_id, query, admin, limit):
                print_to_user(
                    User(
                        id=member.user.id,
                        username=member.user.username,
                        first_name=member.user.first_name,
                        last_name=member.user.last_name,
                        is_bot=member.user.is_bot,
                    )
                )

    def export(self):
        with open(self.config_file, "r", encoding="utf-8") as fp:
            data = fp.read()
        return data

    def import_(self, config_str: str):
        with open(self.config_file, "w", encoding="utf-8") as fp:
            fp.write(config_str)

    def ask_one(self):
        raise NotImplementedError

    def ensure_ai_cfg(self):
        cfg_manager = OpenAIConfigManager(self.workdir)
        cfg = cfg_manager.load_config()
        if not cfg:
            cfg = cfg_manager.ask_for_config()
        return cfg

    def get_ai_tools(self):
        cfg = self.ensure_ai_cfg()
        signature = ai_cfg_signature(cfg)
        if self._ai_tools is None or self._ai_cfg_signature != signature:
            self._ai_tools = AITools(cfg)
            self._ai_cfg_signature = signature
        return self._ai_tools


class UserSigner(
    SignerRunnerMixin,
    SignerActionsMixin,
    SignerMatchersMixin,
    SignerConfigMixin,
    BaseUserWorker[SignConfigV3],
):
    _workdir = ".signer"
    _tasks_dir = "signs"
    cfg_cls = SignConfigV3
    context: UserSignerWorkerContext

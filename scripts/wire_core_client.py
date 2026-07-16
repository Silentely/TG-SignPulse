#!/usr/bin/env python3
"""让 runtime.py 依赖 client.py，去掉重复的 Client 生命周期实现。"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "tg_signer" / "core" / "runtime.py"
CLIENT = ROOT / "tg_signer" / "core" / "client.py"
INIT = ROOT / "tg_signer" / "core" / "__init__.py"


def main() -> None:
    runtime_lines = RUNTIME.read_text(encoding="utf-8").splitlines(keepends=True)
    # 从 ConfigT 开始保留 worker/signer/monitor
    start = None
    for i, line in enumerate(runtime_lines):
        if line.startswith("ConfigT = TypeVar"):
            start = i
            break
    if start is None:
        raise SystemExit("ConfigT not found in runtime.py")

    body = "".join(runtime_lines[start:])

    header = '''\
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
import random
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
except ImportError:  # pragma: no cover
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
from tg_signer.ai_tools import AITools, OpenAIConfigManager
from tg_signer.async_utils import create_logged_task
from tg_signer.compat import (
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
    errors,
    filters,
    idle,
    raw,
)
from tg_signer.log_utils import (
    safe_ai_request_meta,
    safe_ai_result_meta,
    safe_text_preview,
)
from tg_signer.notification.server_chan import sc_send
from tg_signer.utils import UserInput, print_to_user

# Client 真源：生命周期与工厂
from tg_signer.core.client import (  # noqa: F401
    OPENAI_USE_PROMPT,
    DICE_EMOJIS,
    Client,
    _CLIENT_ASYNC_LOCKS,
    _CLIENT_INSTANCES,
    _CLIENT_REFS,
    _is_callback_confirmation_unavailable,
    _is_callback_data_invalid,
    _patched_invoke,
    _patched_sqlite3_connect,
    _read_positive_float_env,
    _read_positive_int_env,
    close_client_by_name,
    get_api_config,
    get_client,
    get_now,
    get_proxy,
    make_dirs,
    readable_chat,
    readable_message,
)

logger = logging.getLogger("tg_signer")
_PYDANTIC_V2 = hasattr(BaseModel, "model_validate")

'''

    RUNTIME.write_text(header + "\n" + body, encoding="utf-8")
    print(f"rewrote runtime.py: kept from line {start + 1}, total body lines {len(runtime_lines) - start}")

    # __init__ 优先从 client 导出 Client 相关符号，其余从 runtime
    INIT.write_text(
        '''\
"""
tg_signer.core 包

- client: Client 生命周期与工厂（真源）
- runtime: BaseUserWorker / UserSigner / UserMonitor
- worker/signer/monitor: 渐进迁移阅读入口
"""
from __future__ import annotations

from tg_signer.core.client import (
    Client,
    _CLIENT_ASYNC_LOCKS,
    _CLIENT_INSTANCES,
    _CLIENT_REFS,
    _is_callback_confirmation_unavailable,
    _is_callback_data_invalid,
    _patched_invoke,
    _patched_sqlite3_connect,
    _read_positive_float_env,
    _read_positive_int_env,
    close_client_by_name,
    get_api_config,
    get_client,
    get_now,
    get_proxy,
    make_dirs,
    readable_chat,
    readable_message,
)
from tg_signer.core.runtime import (
    BaseUserWorker,
    UserMonitor,
    UserSigner,
    UserSignerWorkerContext,
    Waiter,
)

# 动态回退：其余符号仍可从 runtime 取
from tg_signer.core import runtime as _runtime


def __getattr__(name: str):
    if hasattr(_runtime, name):
        return getattr(_runtime, name)
    raise AttributeError(name)


def __dir__():
    return sorted(set(globals()) | set(dir(_runtime)))


__all__ = [
    "Client",
    "BaseUserWorker",
    "Waiter",
    "UserSignerWorkerContext",
    "UserSigner",
    "UserMonitor",
    "get_client",
    "close_client_by_name",
    "get_api_config",
    "get_proxy",
    "get_now",
    "make_dirs",
    "readable_chat",
    "readable_message",
    "_read_positive_float_env",
    "_read_positive_int_env",
    "_CLIENT_INSTANCES",
    "_CLIENT_REFS",
    "_CLIENT_ASYNC_LOCKS",
    "_is_callback_confirmation_unavailable",
    "_is_callback_data_invalid",
]
''',
        encoding="utf-8",
    )
    print("updated __init__.py to prefer client for Client symbols")
    print("client.py size", CLIENT.stat().st_size)


if __name__ == "__main__":
    main()

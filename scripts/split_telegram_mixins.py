#!/usr/bin/env python3
"""将 TelegramService 方法按职责拆到 mixin 模块，runtime 仅保留组合与会话清理。"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "backend" / "services" / "telegram" / "runtime.py"
PKG = ROOT / "backend" / "services" / "telegram"

# 方法名 -> mixin 模块
METHOD_TO_MIXIN: dict[str, str] = {}

for name in (
    "_normalize_account_name",
    "_account_status_payload",
    "_move_path",
    "_rename_pending_login_records",
    "list_accounts",
    "account_exists",
    "download_account_avatar",
    "download_chat_avatar",
    "_build_account_client",
    "check_account_status",
    "delete_account",
    "rename_account",
):
    METHOD_TO_MIXIN[name] = "accounts"

for name in (
    "_normalize_login_token_expires",
    "start_login",
    "verify_login",
    "_persist_client_session",
    "login_sync",
):
    METHOD_TO_MIXIN[name] = "login_phone"

for name in (
    "_log_qr_state",
    "_apply_migrate_auth",
    "_capture_migrate_auth",
    "_cleanup_qr_login",
    "_extend_qr_expires",
    "_expire_qr_login",
    "start_qr_login",
    "get_qr_login_status",
    "submit_qr_password",
    "cancel_qr_login",
):
    METHOD_TO_MIXIN[name] = "login_qr"

for name in (
    "list_account_devices",
    "terminate_account_device",
    "list_official_messages",
):
    METHOD_TO_MIXIN[name] = "devices"


def _decorator_start(lines: list[str], def_line: int, class_line: int) -> int:
    """包含 def 前的 @decorator / 空行，避免装饰器残留在上一段。"""
    start = def_line
    j = def_line - 1
    while j > class_line:
        raw = lines[j].rstrip("\n")
        if raw.strip() == "" or raw.startswith("    @") or raw.startswith("    #"):
            start = j
            j -= 1
            continue
        break
    return start


def find_class_methods(lines: list[str], class_line: int) -> list[tuple[str, int, int]]:
    """返回 (method_name, start, end_exclusive) 列表，按出现顺序。"""
    methods: list[tuple[str, int]] = []
    for i in range(class_line + 1, len(lines)):
        line = lines[i]
        if line.startswith("class ") or (
            line.startswith("def ") and not line.startswith("    ")
        ):
            break
        if line.startswith("# 创建全局"):
            break
        m = re.match(r"    (async )?def ([A-Za-z_][A-Za-z0-9_]*)\(", line)
        if m:
            start = _decorator_start(lines, i, class_line)
            methods.append((m.group(2), start))
    # end bounds
    result = []
    for idx, (name, start) in enumerate(methods):
        end = methods[idx + 1][1] if idx + 1 < len(methods) else None
        if end is None:
            end = len(lines)
            for j in range(start + 1, len(lines)):
                if (
                    lines[j].startswith("def ")
                    or lines[j].startswith("class ")
                    or lines[j].startswith("# 创建全局")
                ):
                    end = j
                    break
        result.append((name, start, end))
    return result


def main() -> None:
    text = RUNTIME.read_text(encoding="utf-8")
    # 去掉 BOM
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    lines = text.splitlines(keepends=True)

    class_line = next(i for i, l in enumerate(lines) if l.startswith("class TelegramService"))
    methods = find_class_methods(lines, class_line)

    # 分组方法体
    groups: dict[str, list[str]] = {
        "accounts": [],
        "login_phone": [],
        "login_qr": [],
        "devices": [],
        "core": [],  # __init__ 与未分组方法
    }
    kept_in_service: list[str] = []

    # __init__ 单独保留
    init_body = ""
    for name, start, end in methods:
        body = "".join(lines[start:end])
        # 降一级缩进？不，mixin 方法保持 4 空格类内缩进
        if name == "__init__":
            init_body = body
            continue
        mixin = METHOD_TO_MIXIN.get(name)
        if mixin:
            groups[mixin].append(body)
        else:
            groups["core"].append(body)
            kept_in_service.append(name)

    common_imports = '''\
from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import os
import secrets
import time
from typing import Any, Dict, List, Optional

from backend.core.config import get_settings
from backend.services.telegram.sessions import (
    _LOGIN_SESSION_MAX_AGE,
    _MAX_LOGIN_SESSIONS,
    _QR_LOGIN_SESSION_MAX_AGE,
    _cleanup_expired_login_sessions,
    _login_sessions,
    _qr_login_sessions,
    _release_login_session,
)
from backend.utils.account_locks import get_account_lock
from backend.utils.names import validate_storage_name
from backend.utils.proxy import build_proxy_dict
from backend.utils.tg_session import (
    delete_account_session_string,
    delete_session_string_file,
    get_account_profile,
    get_account_session_string,
    get_account_status,
    get_global_semaphore,
    get_session_mode,
    is_string_session_mode,
    list_account_names,
    load_session_string_file,
    rename_account_entry,
    save_session_string_file,
    set_account_session_string,
    set_account_status,
)
from backend.utils.time import utc_from_timestamp_iso_z, utc_now_iso_z
from tg_signer.async_utils import create_logged_task

settings = get_settings()
logger = logging.getLogger("backend.qr_login")
'''

    mixin_class_names = {
        "accounts": "TelegramAccountsMixin",
        "login_phone": "TelegramPhoneLoginMixin",
        "login_qr": "TelegramQrLoginMixin",
        "devices": "TelegramDevicesMixin",
    }

    for key, class_name in mixin_class_names.items():
        bodies = groups[key]
        content = (
            f'"""TelegramService mixin: {key}."""\n'
            + common_imports
            + "\n"
            + f"class {class_name}:\n"
        )
        if not bodies:
            content += "    pass\n"
        else:
            content += "\n".join(bodies)
            if not content.endswith("\n"):
                content += "\n"
        (PKG / f"{key}.py").write_text(content, encoding="utf-8")
        print(f"wrote {key}.py methods={len(bodies)}")

    # 抽出 sessions 模块（登录临时状态）
    # preamble 到 class 之前
    preamble = "".join(lines[:class_line])
    if preamble.startswith("\ufeff"):
        preamble = preamble.lstrip("\ufeff")

    # 写 sessions.py：从原文 preamble 提取 session 相关
    sessions_src = preamble
    # 确保可独立导入
    (PKG / "sessions.py").write_text(
        '"""登录会话临时存储与清理。"""\n' + sessions_src,
        encoding="utf-8",
    )
    print("wrote sessions.py")

    # 全局实例部分
    tail_start = methods[-1][2] if methods else len(lines)
    tail = "".join(lines[tail_start:])

    service = (
        '"""TelegramService 组合入口。"""\n'
        "from __future__ import annotations\n\n"
        "from typing import Any, Dict, List, Optional\n\n"
        "from backend.core.config import get_settings\n"
        "from backend.services.telegram.accounts import TelegramAccountsMixin\n"
        "from backend.services.telegram.devices import TelegramDevicesMixin\n"
        "from backend.services.telegram.login_phone import TelegramPhoneLoginMixin\n"
        "from backend.services.telegram.login_qr import TelegramQrLoginMixin\n"
        "from backend.services.telegram.sessions import (  # noqa: F401\n"
        "    _login_sessions,\n"
        "    _qr_login_sessions,\n"
        "    _cleanup_expired_login_sessions,\n"
        ")\n\n"
        "settings = get_settings()\n\n"
        "class TelegramService(\n"
        "    TelegramAccountsMixin,\n"
        "    TelegramPhoneLoginMixin,\n"
        "    TelegramQrLoginMixin,\n"
        "    TelegramDevicesMixin,\n"
        "):\n"
        '    """Telegram 服务类（由 mixin 组合）。"""\n\n'
        + (init_body if init_body else "    def __init__(self):\n        pass\n")
        + "\n"
        + "".join(groups["core"])
        + "\n"
        + tail
    )
    RUNTIME.write_text(service, encoding="utf-8")
    print("rewrote runtime.py service composition")
    print("core leftover methods:", kept_in_service)

    (PKG / "__init__.py").write_text(
        '"""Telegram 服务包：mixin 组合 + get_telegram_service。"""\n'
        "from backend.services.telegram.runtime import (  # noqa: F401\n"
        "    TelegramService,\n"
        "    get_telegram_service,\n"
        ")\n"
        "from backend.services.telegram.sessions import (  # noqa: F401\n"
        "    _login_sessions,\n"
        "    _qr_login_sessions,\n"
        ")\n",
        encoding="utf-8",
    )
    print("updated __init__.py")


if __name__ == "__main__":
    main()

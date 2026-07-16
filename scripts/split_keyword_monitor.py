#!/usr/bin/env python3
"""抽出 keyword_monitor 的规则模型与关键词解析工具。"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "backend" / "services" / "keyword_monitor" / "runtime.py"
PKG = ROOT / "backend" / "services" / "keyword_monitor"


def main() -> None:
    text = RUNTIME.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    # 找到 KeywordMonitorService class 行
    service_line = next(
        i for i, l in enumerate(lines) if l.startswith("class KeywordMonitorService")
    )
    # rules 文件：从文件头到 KeywordMonitorService 之前
    # 但要去掉 service 之后的内容；保留 TerminalAIActionError 到 _load 相关顶层函数
    head = "".join(lines[:service_line])

    rules = (
        '"""关键词监控规则模型与纯函数工具。"""\n'
        + head
        + "\n__all__ = [\n"
        + '    "TerminalAIActionError",\n'
        + '    "KeywordMonitorRule",\n'
        + '    "DEFAULT_CONTINUE_TIMEOUT",\n'
        + '    "DEFAULT_HISTORY_LIMIT",\n'
        + '    "DEFAULT_COMMAND_PREFIX",\n'
        + '    "DEFAULT_BOT_CMD_INTERVAL",\n'
        + '    "DEFAULT_BOT_CMD_MAX_BATCH",\n'
        + "]\n"
    )
    (PKG / "rules.py").write_text(rules, encoding="utf-8")

    # runtime 改为 from .rules import *
    # 找 service 到文件结束
    body = "".join(lines[service_line:])
    new_runtime = (
        '"""关键词监控服务（规则见 rules.py）。"""\n'
        "from __future__ import annotations\n\n"
        "import asyncio\n"
        "import logging\n"
        "import os\n"
        "import random\n"
        "import re\n"
        "import time\n"
        "import unicodedata\n"
        "from datetime import datetime\n"
        "from typing import Any, Dict, List, Optional, Union\n\n"
        "from backend.core.config import get_settings\n"
        "from backend.services.push_notifications import send_keyword_push\n"
        "from backend.utils.account_locks import get_account_lock\n"
        "from backend.utils.proxy import build_proxy_dict\n"
        "from backend.utils.tg_session import (\n"
        "    get_account_proxy,\n"
        "    get_account_session_string,\n"
        "    get_session_mode,\n"
        "    load_session_string_file,\n"
        ")\n"
        "from tg_signer.compat import (\n"
        "    InlineKeyboardMarkup,\n"
        "    Message,\n"
        "    MessageHandler,\n"
        "    ReplyKeyboardMarkup,\n"
        "    errors,\n"
        "    filters,\n"
        ")\n"
        "from tg_signer.log_utils import (\n"
        "    safe_ai_request_meta,\n"
        "    safe_ai_result_meta,\n"
        "    safe_text_preview,\n"
        ")\n"
        "from backend.services.keyword_monitor.rules import (  # noqa: F401\n"
        "    DEFAULT_BOT_CMD_INTERVAL,\n"
        "    DEFAULT_BOT_CMD_MAX_BATCH,\n"
        "    DEFAULT_COMMAND_PREFIX,\n"
        "    DEFAULT_CONTINUE_TIMEOUT,\n"
        "    DEFAULT_HISTORY_LIMIT,\n"
        "    KeywordMonitorRule,\n"
        "    TerminalAIActionError,\n"
        "    _BOT_CMD_MAX_BATCH_RISK_HINT,\n"
        "    _TG_START_LINK_RE,\n"
        "    _is_callback_data_invalid,\n"
        "    _keyword_split_commas,\n"
        "    _parse_keywords,\n"
        "    _regex_keyword_value,\n"
        "    logger,\n"
        "    settings,\n"
        ")\n\n"
        # rules 可能还有更多顶层函数，用 star 更稳
        "from backend.services.keyword_monitor.rules import *  # noqa: F403\n\n"
        + body
    )
    RUNTIME.write_text(new_runtime, encoding="utf-8")

    (PKG / "__init__.py").write_text(
        '"""关键词监控包。"""\n'
        "from backend.services.keyword_monitor.runtime import (  # noqa: F401\n"
        "    KeywordMonitorService,\n"
        "    get_keyword_monitor_service,\n"
        ")\n"
        "from backend.services.keyword_monitor.rules import (  # noqa: F401\n"
        "    KeywordMonitorRule,\n"
        "    TerminalAIActionError,\n"
        ")\n",
        encoding="utf-8",
    )
    print("split keyword_monitor rules/runtime")


if __name__ == "__main__":
    main()

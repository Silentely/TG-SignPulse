"""Reply settings shared by the standalone signer and backend environment bridge."""

from __future__ import annotations

import os
import re
from typing import Any

DEFAULT_RETRY_KEYWORDS: tuple[str, ...] = (
    "再试",
    "重试",
    "稍后",
    "人数较多",
    "繁忙",
    "请 10 秒后",
)


def parse_retry_keywords(raw: Any) -> list[str]:
    if isinstance(raw, list):
        keywords = [str(k).strip() for k in raw if str(k).strip()]
    elif isinstance(raw, str):
        keywords = [k.strip() for k in re.split(r"[\n,]+", raw) if k.strip()]
    else:
        keywords = []
    return keywords or list(DEFAULT_RETRY_KEYWORDS)


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def get_reply_timeout() -> int:
    return _env_int("SIGN_TASK_REPLY_TIMEOUT", 90, 30, 3600)


def get_retry_interval() -> int:
    return _env_int("SIGN_TASK_RETRY_INTERVAL", 10, 1, 300)


def get_retry_max_attempts() -> int:
    return _env_int("SIGN_TASK_RETRY_MAX_ATTEMPTS", 3, 0, 10)


def get_retry_keywords() -> list[str]:
    return parse_retry_keywords(os.getenv("SIGN_TASK_RETRY_KEYWORDS"))

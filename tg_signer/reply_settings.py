"""Reply settings shared by the standalone signer and backend environment bridge."""

from __future__ import annotations

import os
import re
from typing import Any

DEFAULT_RETRY_KEYWORDS: tuple[str, ...] = (
    "再试",
    "重试",
    "稍后",
    "请稍后",
    "人数较多",
    "繁忙",
    "系统繁忙",
    "请 10 秒后",
    "try again",
    "slow down",
    "busy",
)

DEFAULT_REPLY_SUCCESS_PATTERNS: tuple[str, ...] = (
    "签到成功",
    "打卡成功",
    "(已|今天已|今日已)签到",
    r"获得.+?(?:经验|积分|金币|能量|流量|点数|GB|MB|KB)",
    r"连续签到.+?天",
    r"出席率\s*成功",
    r"(?i)(?:success|successfully|checked[- ]?in)",
)

DEFAULT_REPLY_FAILURE_PATTERNS: tuple[str, ...] = (
    "签到失败",
    "打卡失败",
    "操作失败",
    r"验证码错误|验证失败",
    r"回答超时|答题超时",
    r"(?:签到)?机会(?:已)?用完|(?:今日|今天|当天)(?:已)?(?:不能|不可|无法)再?签到",
    r"出席率\s*失败",
    r"(?i)(?:failed|failure|invalid)",
)


class BotTerminalFailure(RuntimeError):
    """机器人明确表示当天无法继续；保留原文并禁止重试。"""

    non_retryable = True
    failure_category = "other"


def is_daily_terminal_failure(text: str) -> bool:
    return bool(
        re.search(
            r"(?:签到)?机会(?:已)?用完|(?:今日|今天|当天)(?:已)?(?:不能|不可|无法)再?签到"
            r"|(?:回答|答题|验证)(?:超时|失败|错误).*?(?:明天|明日|次日)再试",
            str(text or ""),
        )
    )


def upgrade_reply_patterns(patterns: list[str], *, success: bool) -> list[str]:
    """只升级已知旧默认组合；自定义规则原样保留。"""
    old = (
        [("签到成功",), (r"出席率\s*成功", "签到成功", "操作成功")]
        if success
        else [
            (r"出席率\s*失败", "签到失败", "操作失败"),
            tuple(
                p
                for p in DEFAULT_REPLY_FAILURE_PATTERNS
                if p
                not in (
                    r"回答超时|答题超时",
                    r"(?:签到)?机会(?:已)?用完|(?:今日|今天|当天)(?:已)?(?:不能|不可|无法)再?签到",
                )
            ),
        ]
    )
    defaults = (
        DEFAULT_REPLY_SUCCESS_PATTERNS if success else DEFAULT_REPLY_FAILURE_PATTERNS
    )
    if not patterns or any(set(patterns) == set(group) for group in old):
        return list(defaults)
    return list(patterns)


def get_default_success_patterns() -> list[str]:
    return list(DEFAULT_REPLY_SUCCESS_PATTERNS)


def get_default_failure_patterns() -> list[str]:
    return list(DEFAULT_REPLY_FAILURE_PATTERNS)


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

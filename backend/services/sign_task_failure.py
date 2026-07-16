"""
签到任务失败分类与判定

从 SignTaskService 抽离的纯逻辑，便于单测与复用，避免与执行流程耦合。
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Optional


class FailureCategory(str, Enum):
    """任务失败类别，供日志/诊断/通知使用。"""

    NONE = "none"
    SESSION_INVALID = "session_invalid"
    FLOOD_WAIT = "flood_wait"
    AI_TIMEOUT = "ai_timeout"
    AI_ERROR = "ai_error"
    BUTTON_NOT_FOUND = "button_not_found"
    TARGET_NOT_FOUND = "target_not_found"
    NETWORK_PROXY = "network_proxy"
    TIMEOUT = "timeout"
    STRONG_FAILURE = "strong_failure"
    UNKNOWN = "unknown"


_STRONG_FAILURE_PATTERNS = (
    re.compile(r"(签到|任务|执行|操作|请求|发送|点击)\s*(失败|异常|超时)"),
    re.compile(r"(未找到|找不到).*(按钮|消息|会话|聊天|目标)"),
    re.compile(r"(账号|会话|session).*(失效|无效|invalid)"),
    re.compile(
        r"\b(failed|failure|timed out|timeout|not found|invalid session|error)\b",
        re.IGNORECASE,
    ),
)

_SUCCESS_MARKERS = (
    "签到成功",
    "已签到",
    "任务完成",
    "执行完成",
    "操作完成",
    "success",
    "successful",
    "done",
    "completed",
)

_CATEGORY_RULES: tuple[tuple[FailureCategory, tuple[str, ...]], ...] = (
    (
        FailureCategory.SESSION_INVALID,
        (
            "invalid session",
            "auth key",
            "session 失效",
            "会话失效",
            "账号失效",
            "unauthorized",
            "user deactivated",
            "session_revoked",
        ),
    ),
    (
        FailureCategory.FLOOD_WAIT,
        ("floodwait", "flood wait", "flood_wait", "太频繁", "slowmode"),
    ),
    (
        FailureCategory.AI_TIMEOUT,
        ("ai timeout", "vision timeout", "openai timeout", "ai 超时", "识图超时"),
    ),
    (
        FailureCategory.AI_ERROR,
        ("openai", "ai error", "vision error", "api key", "quota", "rate limit"),
    ),
    (
        FailureCategory.BUTTON_NOT_FOUND,
        ("未找到按钮", "找不到按钮", "button not found", "no button"),
    ),
    (
        FailureCategory.TARGET_NOT_FOUND,
        (
            "未找到消息",
            "找不到消息",
            "未找到会话",
            "找不到聊天",
            "chat not found",
            "peer id invalid",
        ),
    ),
    (
        FailureCategory.NETWORK_PROXY,
        (
            "proxy",
            "proxyerror",
            "connection reset",
            "connection refused",
            "network is unreachable",
            "timed out connecting",
            "socks",
            "ssl",
        ),
    ),
    (
        FailureCategory.TIMEOUT,
        ("timeout", "timed out", "超时"),
    ),
)


def message_indicates_strong_failure(text: str) -> bool:
    """目标消息文本是否呈现强失败语义（排除成功标记）。"""
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    if any(marker in normalized for marker in _SUCCESS_MARKERS):
        return False
    return any(pattern.search(normalized) for pattern in _STRONG_FAILURE_PATTERNS)


def classify_failure(
    error: Optional[str] = None,
    output: Optional[str] = None,
    *,
    success: Optional[bool] = None,
) -> FailureCategory:
    """
    根据错误信息与输出文本对失败原因分类。

    success=True 时返回 NONE；无文本时返回 UNKNOWN。
    """
    if success is True:
        return FailureCategory.NONE

    blob = f"{error or ''}\n{output or ''}".strip().lower()
    if not blob:
        return FailureCategory.UNKNOWN if success is False else FailureCategory.NONE

    for category, keywords in _CATEGORY_RULES:
        if any(k in blob for k in keywords):
            return category

    if message_indicates_strong_failure(blob):
        return FailureCategory.STRONG_FAILURE

    return FailureCategory.UNKNOWN if success is False else FailureCategory.NONE


def failure_category_label(category: FailureCategory) -> str:
    """中文短标签，用于面板展示。"""
    labels = {
        FailureCategory.NONE: "正常",
        FailureCategory.SESSION_INVALID: "会话失效",
        FailureCategory.FLOOD_WAIT: "频率限制",
        FailureCategory.AI_TIMEOUT: "AI 超时",
        FailureCategory.AI_ERROR: "AI 错误",
        FailureCategory.BUTTON_NOT_FOUND: "按钮未找到",
        FailureCategory.TARGET_NOT_FOUND: "目标未找到",
        FailureCategory.NETWORK_PROXY: "网络/代理",
        FailureCategory.TIMEOUT: "超时",
        FailureCategory.STRONG_FAILURE: "业务失败",
        FailureCategory.UNKNOWN: "未知失败",
    }
    return labels.get(category, category.value)

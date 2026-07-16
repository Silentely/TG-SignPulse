"""关键词监控包。"""
import asyncio  # noqa: F401  # 兼容测试 patch backend.services.keyword_monitor.asyncio

from backend.services.keyword_monitor import rules as _rules
from backend.services.keyword_monitor.rules import (  # noqa: F401
    KeywordMonitorRule,
    TerminalAIActionError,
)
from backend.services.keyword_monitor.runtime import (  # noqa: F401
    KeywordMonitorService,
    get_keyword_monitor_service,
)


def __getattr__(name: str):
    if hasattr(_rules, name):
        return getattr(_rules, name)
    raise AttributeError(name)


def __dir__():
    return sorted(set(globals()) | set(dir(_rules)))

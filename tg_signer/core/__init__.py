"""
tg_signer.core 包

- client: Client 生命周期与工厂（真源）
- runtime: BaseUserWorker / UserSigner / UserMonitor（真源）
"""
from __future__ import annotations

# 动态回退：其余符号仍可从 runtime 取
from tg_signer.core import runtime as _runtime
from tg_signer.core.client import (
    _CLIENT_ASYNC_LOCKS,
    _CLIENT_INSTANCES,
    _CLIENT_REFS,
    Client,
    _is_callback_confirmation_unavailable,
    _is_callback_data_invalid,
    _patched_invoke,  # noqa: F401 — 副作用导入：触发 monkey-patch 装配
    _patched_sqlite3_connect,  # noqa: F401 — 副作用导入：触发 monkey-patch 装配
    close_client_by_name,
    get_api_config,
    get_client,
    get_now,
    get_proxy,
    get_task_timezone,
    make_dirs,
    readable_chat,
    readable_message,
)
from tg_signer.core.monitor import UserMonitor
from tg_signer.core.runtime import (
    BaseUserWorker,
    UserSigner,
    UserSignerWorkerContext,
)


def __getattr__(name: str):
    if hasattr(_runtime, name):
        return getattr(_runtime, name)
    raise AttributeError(name)


def __dir__():
    return sorted(set(globals()) | set(dir(_runtime)))


__all__ = [
    "Client",
    "BaseUserWorker",
    "UserSignerWorkerContext",
    "UserSigner",
    "UserMonitor",
    "get_client",
    "close_client_by_name",
    "get_api_config",
    "get_proxy",
    "get_now",
    "get_task_timezone",
    "make_dirs",
    "readable_chat",
    "readable_message",
    "_CLIENT_INSTANCES",
    "_CLIENT_REFS",
    "_CLIENT_ASYNC_LOCKS",
    "_is_callback_confirmation_unavailable",
    "_is_callback_data_invalid",
    "_patched_invoke",
    "_patched_sqlite3_connect",
]

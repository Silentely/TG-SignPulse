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

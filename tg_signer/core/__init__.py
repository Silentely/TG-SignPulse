"""
tg_signer.core 包（自 monorepo core.py 拆分）

子模块：
- client / worker / signer / monitor：按职责切分的阅读与渐进迁移入口
- runtime：完整原实现（默认加载，保证行为一致）

对外 import 保持不变：`from tg_signer.core import UserSigner, get_client`
"""
from __future__ import annotations

from tg_signer.core import runtime as _runtime

# 将 runtime 的公共与测试用私有符号提升到包命名空间
from tg_signer.core.runtime import (  # noqa: F401
    BaseUserWorker,
    Client,
    UserMonitor,
    UserSigner,
    UserSignerWorkerContext,
    Waiter,
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

# 允许 `tg_signer.core.XXX` 动态访问 runtime 其余符号
def __getattr__(name: str):
    return getattr(_runtime, name)


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

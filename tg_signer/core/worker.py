"""BaseUserWorker / Waiter / Context 阅读入口。

真源在 `tg_signer.core.runtime`；本模块仅 re-export，避免拆分后
`from client import *` 漏掉 typing/配置符号导致 NameError。
"""
from __future__ import annotations

from tg_signer.core.runtime import (  # noqa: F401
    BaseUserWorker,
    ConfigT,
    UserSignerWorkerContext,
    Waiter,
)

__all__ = [
    "ConfigT",
    "BaseUserWorker",
    "Waiter",
    "UserSignerWorkerContext",
]

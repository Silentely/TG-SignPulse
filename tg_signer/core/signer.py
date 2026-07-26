"""UserSigner 阅读入口。

真源在 `tg_signer.core.runtime`；本模块仅 re-export。
"""
from __future__ import annotations

from tg_signer.core.runtime import UserSigner  # noqa: F401

__all__ = ["UserSigner"]

from __future__ import annotations

import asyncio
from typing import Dict

_ACCOUNT_LOCKS: Dict[str, asyncio.Lock] = {}

# 锁表容量上限：超过后清理未持锁条目，防账号删除后 Lock 永久滞留
_MAX_LOCKS = 500


def _prune_unlocked() -> None:
    """清理未被持有的锁，防字典随历史账号无限增长。"""
    for name, lock in list(_ACCOUNT_LOCKS.items()):
        if not lock.locked():
            _ACCOUNT_LOCKS.pop(name, None)


def get_account_lock(account_name: str) -> asyncio.Lock:
    lock = _ACCOUNT_LOCKS.get(account_name)
    if lock is None:
        if len(_ACCOUNT_LOCKS) >= _MAX_LOCKS:
            _prune_unlocked()
        lock = asyncio.Lock()
        _ACCOUNT_LOCKS[account_name] = lock
    return lock

"""
账号锁注册表 (Account Lock Registry)

全局约定与并发安全规范：
1. 账号级互斥：
   每个账号名称对应独立的 asyncio.Lock，保护 Pyrogram 客户端会话、SQLite 数据库文件及相关状态。
2. 弱引用生命周期 (WeakValueDictionary)：
   锁对象通过 weakref.WeakValueDictionary 管理。只要有协程持有锁或在等待锁，
   该锁对象即在内存中保持；当所有引用释放后，Python GC 自动回收，彻底消除“锁孤儿”与内存泄漏。
3. 超时获取机制：
   对于 HTTP 接口等有严格时延要求的场景，应使用 `acquire_account_lock_with_timeout`，
   避免请求因锁竞争长期挂起或造成协程无界堆积。
4. 多账号锁防死锁规范：
   当操作涉及多个账号（例如账号重命名、跨账号资产或任务迁移）时，
   必须严格按照 `sorted(account_names)` 字典序（以账号名排序）依次获取锁，
   在退出时逆序或自动释放，杜绝死锁 (Deadlock)。
"""
from __future__ import annotations

import asyncio
import contextlib
import weakref
from typing import AsyncIterator, Iterable

_ACCOUNT_LOCKS: weakref.WeakValueDictionary[str, asyncio.Lock] = (
    weakref.WeakValueDictionary()
)


class AccountLockTimeout(RuntimeError):
    """Raised when an account lock cannot be acquired within the timeout window."""

    pass


def get_account_lock(account_name: str) -> asyncio.Lock:
    """
    获取指定账号的并发锁。
    若该账号当前已有活跃锁（被协程持有或排队等待），返回已有实例；
    否则新建锁并由 WeakValueDictionary 弱引用追踪。
    """
    lock = _ACCOUNT_LOCKS.get(account_name)
    if lock is None:
        lock = asyncio.Lock()
        _ACCOUNT_LOCKS[account_name] = lock
    return lock


@contextlib.asynccontextmanager
async def acquire_account_lock_with_timeout(
    account_name: str,
    timeout: float = 15.0,
) -> AsyncIterator[asyncio.Lock]:
    """
    异步上下文管理器：在指定超时时间内获取账号锁。
    若在超时时间内获取到锁，进入临界区；
    若超时，抛出 AccountLockTimeout。
    """
    lock = get_account_lock(account_name)
    acquired = False
    try:
        await asyncio.wait_for(lock.acquire(), timeout=timeout)
        acquired = True
    except asyncio.TimeoutError as e:
        raise AccountLockTimeout(
            f"Timed out after {timeout}s waiting for account lock: {account_name}"
        ) from e
    try:
        yield lock
    finally:
        if acquired:
            lock.release()


@contextlib.asynccontextmanager
async def acquire_multi_account_locks(
    account_names: Iterable[str],
    timeout: float = 15.0,
) -> AsyncIterator[list[asyncio.Lock]]:
    """
    按字典序依次获取多个账号锁的异步上下文管理器，防止死锁。
    """
    ordered_names = sorted(set(account_names))
    acquired_locks: list[asyncio.Lock] = []
    try:
        for name in ordered_names:
            lock = get_account_lock(name)
            await asyncio.wait_for(lock.acquire(), timeout=timeout)
            acquired_locks.append(lock)
    except asyncio.TimeoutError as e:
        for lock in reversed(acquired_locks):
            lock.release()
        raise AccountLockTimeout(
            f"Timed out after {timeout}s waiting for multi-account locks: {ordered_names}"
        ) from e
    except BaseException:
        # 取消/其他异常同样必须释放已获取的锁，否则锁将永久滞留
        for lock in reversed(acquired_locks):
            lock.release()
        raise

    try:
        yield acquired_locks
    finally:
        for lock in reversed(acquired_locks):
            lock.release()

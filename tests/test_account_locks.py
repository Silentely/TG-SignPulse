from __future__ import annotations

import asyncio
import gc
import unittest.mock

import pytest

from backend.utils.account_locks import (
    _ACCOUNT_LOCKS,
    AccountLockTimeout,
    acquire_account_lock_with_timeout,
    acquire_multi_account_locks,
    get_account_lock,
)


@pytest.mark.asyncio
async def test_lock_registry_survives_gc_while_waiter_pending():
    """验证排队协程持有锁引用时字典不被清空。"""
    account = "test_gc_acc"
    acquired_evt = asyncio.Event()
    release_evt = asyncio.Event()

    async def holder():
        async with acquire_account_lock_with_timeout(account, timeout=5.0):
            acquired_evt.set()
            await release_evt.wait()

    waiter_acquired = False

    async def waiter():
        nonlocal waiter_acquired
        await acquired_evt.wait()
        async with acquire_account_lock_with_timeout(account, timeout=5.0):
            waiter_acquired = True

    holder_task = asyncio.create_task(holder())
    await acquired_evt.wait()

    waiter_task = asyncio.create_task(waiter())
    await asyncio.sleep(0.05)

    # 强制执行垃圾回收
    gc.collect()

    # 排队协程与持有者持有强引用，WeakValueDictionary 中键必须依然存在
    assert account in _ACCOUNT_LOCKS
    assert _ACCOUNT_LOCKS[account].locked()

    # 释放持有者，排队者应顺利获取
    release_evt.set()
    await waiter_task
    await holder_task
    assert waiter_acquired is True


@pytest.mark.asyncio
async def test_lock_registry_reuses_same_lock_for_concurrent_getters():
    """并发获取同名锁必为同一实例。"""
    account = "concurrent_acc"

    async def getter():
        lock = get_account_lock(account)
        await asyncio.sleep(0.01)
        return lock

    results = await asyncio.gather(*(getter() for _ in range(10)))
    first = results[0]
    for lk in results:
        assert lk is first


def test_lock_collected_when_no_references():
    """无任何强引用时，锁对象由 Python GC 自动从 WeakValueDictionary 回收。"""
    account = "orphan_acc"
    lock = get_account_lock(account)
    assert account in _ACCOUNT_LOCKS
    del lock
    gc.collect()
    assert account not in _ACCOUNT_LOCKS


@pytest.mark.asyncio
async def test_acquire_with_timeout_raises_account_lock_timeout():
    """超时抛出 AccountLockTimeout。"""
    account = "timeout_acc"
    hold_evt = asyncio.Event()

    async def holder():
        async with acquire_account_lock_with_timeout(account, timeout=5.0):
            await hold_evt.wait()

    holder_task = asyncio.create_task(holder())
    await asyncio.sleep(0.05)

    with pytest.raises(AccountLockTimeout):
        async with acquire_account_lock_with_timeout(account, timeout=0.1):
            pass

    hold_evt.set()
    await holder_task


@pytest.mark.asyncio
async def test_multi_account_locks_released_on_cancellation():
    """等待后续账号锁时被取消，已获取的锁必须全部释放，否则永久滞留。"""
    first, second = "cancel_acc_a", "cancel_acc_b"

    # 先占住第二个账号的锁，让获取流程卡在第二个账号上
    blocker_evt = asyncio.Event()

    async def blocker():
        async with acquire_account_lock_with_timeout(second, timeout=5.0):
            blocker_evt.set()
            await asyncio.sleep(5)

    blocker_task = asyncio.create_task(blocker())
    await blocker_evt.wait()

    async def acquire_two():
        async with acquire_multi_account_locks([first, second], timeout=30.0):
            pass  # pragma: no cover - 不应进入

    task = asyncio.create_task(acquire_two())
    # 等它拿到第一个锁并阻塞在第二个锁上
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # 第一个账号的锁必须已被释放
    assert not get_account_lock(first).locked()

    blocker_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await blocker_task


@pytest.mark.asyncio
async def test_multi_account_locks_acquired_in_sorted_order(monkeypatch):
    """验证多账号锁按字典序获取以杜绝死锁。"""
    names = ["zebra", "apple", "mango"]
    acquired_sequence = []

    original_acquire = asyncio.Lock.acquire

    async def spy_acquire(self):
        for name in names:
            if get_account_lock(name) is self:
                acquired_sequence.append(name)
                break
        return await original_acquire(self)

    monkeypatch.setattr(asyncio.Lock, "acquire", spy_acquire)

    async with acquire_multi_account_locks(names, timeout=2.0) as locks:
        assert len(locks) == 3

    assert acquired_sequence == ["apple", "mango", "zebra"]


@pytest.mark.asyncio
async def test_check_account_status_timeout_returns_busy():
    """check_account_status 在获取锁超时时映射为 ACCOUNT_BUSY。"""
    from backend.services.telegram.accounts import TelegramAccountsMixin

    class DummyService(TelegramAccountsMixin):
        def __init__(self):
            self.session_dir = None

        def _normalize_account_name(self, name):
            return name

        def account_exists(self, name):
            return True

    svc = DummyService()
    account = "busy_status_acc"
    hold_evt = asyncio.Event()

    async def blocker():
        async with acquire_account_lock_with_timeout(account, timeout=5.0):
            await hold_evt.wait()

    blocker_task = asyncio.create_task(blocker())
    await asyncio.sleep(0.05)

    with unittest.mock.patch("tg_signer.core.get_client"):
        result = await svc.check_account_status(account, timeout_seconds=0.1)

    hold_evt.set()
    await blocker_task

    assert result["ok"] is False
    assert result["code"] == "ACCOUNT_BUSY"
    assert result["status"] == "busy"


@pytest.mark.asyncio
async def test_devices_timeout_raises_busy():
    """devices 接口在锁超时时抛出统一 ACCOUNT_BUSY 错误。"""
    from backend.services.telegram.devices import TelegramDevicesMixin

    class DummyDeviceService(TelegramDevicesMixin):
        def _normalize_account_name(self, name):
            return name

        def account_exists(self, name):
            return True

        def _build_account_client(self, name, no_updates=True):
            return unittest.mock.AsyncMock(), None

    svc = DummyDeviceService()
    account = "busy_device_acc"
    hold_evt = asyncio.Event()

    async def blocker():
        async with acquire_account_lock_with_timeout(account, timeout=5.0):
            await hold_evt.wait()

    blocker_task = asyncio.create_task(blocker())
    await asyncio.sleep(0.05)

    with pytest.raises(RuntimeError) as exc_info:
        await svc.list_account_devices(account, timeout_seconds=0.1)
    assert "ACCOUNT_BUSY" in str(exc_info.value)

    with pytest.raises(RuntimeError) as exc_info2:
        with unittest.mock.patch.object(
            svc, "list_account_devices", return_value=[{"hash": "123", "current": False}]
        ):
            await svc.terminate_account_device(account, 123, timeout_seconds=0.1)
    assert "ACCOUNT_BUSY" in str(exc_info2.value)

    hold_evt.set()
    await blocker_task

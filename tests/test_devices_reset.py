from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pyrogram import raw

from backend.services.telegram.devices import TelegramDevicesMixin
from backend.utils.account_locks import (
    AccountLockTimeout,
)
from tests.test_api import _auth, _login, api_client, db  # noqa: F401


class DummyDeviceService(TelegramDevicesMixin):
    def __init__(self, exists: bool = True):
        self._exists = exists
        self.client = AsyncMock()
        self.client.is_connected = False
        self.client.invoke = AsyncMock(return_value=True)

    def _normalize_account_name(self, name: str) -> str:
        return name

    def account_exists(self, name: str) -> bool:
        return self._exists

    def _build_account_client(self, name: str, no_updates: bool = True):
        return self.client, None


@pytest.mark.asyncio
async def test_reset_account_authorizations_invokes_raw_rpc_under_lock():
    """测试 reset_account_authorizations 在锁内进入客户端上下文并调用 ResetAuthorizations RPC。"""
    svc = DummyDeviceService(exists=True)
    account_name = "test_acc_reset"

    result = await svc.reset_account_authorizations(account_name, timeout_seconds=5.0)

    assert result is True
    # 客户端连接由引用计数上下文管理，不得手动 connect/disconnect
    svc.client.__aenter__.assert_awaited_once()
    svc.client.connect.assert_not_awaited()
    assert svc.client.invoke.call_count == 1
    call_arg = svc.client.invoke.call_args[0][0]
    expected_rpc_cls = (
        getattr(raw.functions.account, "ResetAuthorizations", None)
        or getattr(raw.functions.auth, "ResetAuthorizations", None)
    )
    assert isinstance(call_arg, expected_rpc_cls)
    svc.client.__aexit__.assert_awaited_once()
    svc.client.disconnect.assert_not_awaited()


@pytest.mark.asyncio
async def test_reset_account_authorizations_rejects_missing_account():
    """测试当账号不存在时抛出 ValueError。"""
    svc = DummyDeviceService(exists=False)
    with pytest.raises(ValueError, match="账号不存在"):
        await svc.reset_account_authorizations("nonexistent_acc")


def _patch_telegram_service(svc: MagicMock):
    return patch("backend.api.routes.accounts.get_telegram_service", return_value=svc)


def test_reset_authorizations_route_returns_success(api_client, db):  # noqa: F811
    """测试 POST /api/accounts/{account_name}/devices/reset-others 路由成功返回。"""
    token = _login(api_client)
    svc = MagicMock()
    svc.account_exists.return_value = True
    svc.reset_account_authorizations = AsyncMock(return_value=True)

    with _patch_telegram_service(svc):
        resp = api_client.post(
            "/api/accounts/my_account/devices/reset-others",
            headers=_auth(token),
        )

    assert resp.status_code == 200
    assert resp.json() == {
        "success": True,
        "message": "已成功清退其他设备",
    }
    svc.reset_account_authorizations.assert_awaited_once_with("my_account")


def test_reset_authorizations_route_handles_busy_lock(api_client, db):  # noqa: F811
    """测试 POST /api/accounts/{account_name}/devices/reset-others 锁繁忙时返回 409 ACCOUNT_BUSY。"""
    token = _login(api_client)
    svc = MagicMock()
    svc.account_exists.return_value = True
    svc.reset_account_authorizations = AsyncMock(
        side_effect=AccountLockTimeout("ACCOUNT_BUSY")
    )

    with _patch_telegram_service(svc):
        resp = api_client.post(
            "/api/accounts/busy_account/devices/reset-others",
            headers=_auth(token),
        )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "ACCOUNT_BUSY"


@pytest.mark.asyncio
async def test_list_account_devices_disconnects_client():
    svc = DummyDeviceService(exists=True)
    svc.client.invoke.return_value = MagicMock(authorizations=[])
    await svc.list_account_devices("test_acc_reset")
    svc.client.__aenter__.assert_awaited_once()
    svc.client.__aexit__.assert_awaited_once()
    svc.client.disconnect.assert_not_awaited()


@pytest.mark.asyncio
async def test_client_context_exits_before_lock_release():
    """客户端必须在账号锁释放前断开，否则锁外仍持有连接。

    连接若活过锁，后续同账号任务会撞上未断开的会话（SQLite 锁/风控），
    异常路径更会直接泄漏。
    """
    events: list[str] = []
    account_name = "test_acc_lock_order"

    class _OrderedClient:
        is_connected = True

        async def __aenter__(self):
            events.append("enter")
            return self

        async def __aexit__(self, *exc):
            events.append("client_exit")
            return False

        async def invoke(self, _rpc):
            events.append("invoke")
            return MagicMock(authorizations=[])

    svc = DummyDeviceService(exists=True)
    svc.client = _OrderedClient()

    from backend.utils import account_locks as account_locks_mod

    original = account_locks_mod.acquire_account_lock_with_timeout

    @account_locks_mod.contextlib.asynccontextmanager
    async def _tracked(account, timeout=15.0):
        async with original(account, timeout=timeout) as lock:
            events.append("lock_acquired")
            try:
                yield lock
            finally:
                events.append("lock_released")

    with patch.object(svc, "_build_account_client", return_value=(svc.client, None)), patch(
        "backend.services.telegram.devices.acquire_account_lock_with_timeout",
        _tracked,
    ):
        await svc.list_account_devices(account_name, timeout_seconds=5.0)

    assert events == ["lock_acquired", "enter", "invoke", "client_exit", "lock_released"]

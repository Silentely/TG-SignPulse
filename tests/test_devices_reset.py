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
    """测试 reset_account_authorizations 在锁内连接并调用 ResetAuthorizations RPC。"""
    svc = DummyDeviceService(exists=True)
    account_name = "test_acc_reset"

    result = await svc.reset_account_authorizations(account_name, timeout_seconds=5.0)

    assert result is True
    svc.client.connect.assert_awaited_once()
    assert svc.client.invoke.call_count == 1
    call_arg = svc.client.invoke.call_args[0][0]
    expected_rpc_cls = (
        getattr(raw.functions.account, "ResetAuthorizations", None)
        or getattr(raw.functions.auth, "ResetAuthorizations", None)
    )
    assert isinstance(call_arg, expected_rpc_cls)
    svc.client.disconnect.assert_awaited_once()


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
    svc.client.connect.assert_awaited_once()
    svc.client.disconnect.assert_awaited_once()

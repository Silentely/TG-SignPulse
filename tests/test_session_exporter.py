"""Tests for standalone session exporter (acceptLoginToken flow)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pyrogram import raw
from pyrogram.errors import SessionPasswordNeeded

from backend.services.telegram.session_exporter import (
    SessionExportResult,
    create_standalone_session_export,
)
from backend.utils.account_locks import AccountLockTimeout
from tests.test_api import _auth, _login, api_client, db  # noqa: F401


@pytest.mark.asyncio
async def test_export_standalone_session_success_flow():
    account_name = "test_acc"
    mock_service = MagicMock()
    mock_service.account_exists.return_value = True
    mock_service.verify_account_proxy = AsyncMock()

    # Main account client
    mock_main_client = MagicMock()
    mock_main_client.is_connected = True
    mock_main_client.invoke = AsyncMock()
    mock_main_client.disconnect = AsyncMock()
    mock_service._build_account_client.return_value = (mock_main_client, None)

    # Candidate client
    mock_candidate_client = MagicMock()
    mock_candidate_client.is_connected = False
    mock_candidate_client.connect = AsyncMock()
    mock_candidate_client.disconnect = AsyncMock()
    mock_candidate_client.export_session_string = AsyncMock(return_value="standalone_session_str_123")
    mock_candidate_client.storage = MagicMock()
    mock_candidate_client.storage.dc_id = AsyncMock(return_value=2)
    mock_candidate_client.storage.user_id = AsyncMock(return_value=999888)
    mock_candidate_client.storage.is_bot = AsyncMock()
    mock_candidate_client.storage.test_mode = AsyncMock(return_value=False)

    fake_raw_user = MagicMock(spec=raw.types.User)
    fake_raw_user.id = 999888
    fake_raw_user.is_self = True
    fake_auth = MagicMock(spec=raw.types.auth.Authorization)
    fake_auth.user = fake_raw_user

    exported_token = raw.types.auth.LoginToken(expires=100, token=b"valid_token_bytes")
    success_token = raw.types.auth.LoginTokenSuccess(authorization=fake_auth)

    # Candidate invokes: 1st ExportLoginToken -> LoginToken, 2nd ExportLoginToken -> LoginTokenSuccess
    mock_candidate_client.invoke = AsyncMock(side_effect=[exported_token, success_token])

    with patch("backend.services.telegram.session_exporter.Client", return_value=mock_candidate_client), \
         patch("backend.services.telegram.session_exporter.resolve_telegram_api_credentials", return_value=(12345, "test_hash")), \
         patch("backend.services.telegram.session_exporter.get_config_service") as mock_cfg_svc:
        mock_cfg_svc.return_value.get_global_settings.return_value = {"require_proxy_for_telegram": False}
        mock_cfg_svc.return_value.get_telegram_config.return_value = {}

        result = await create_standalone_session_export(
            account_name,
            device_model="Custom Device Model",
            timeout_seconds=10.0,
            service=mock_service,
        )

    assert result.success is True
    assert result.session_string == "standalone_session_str_123"
    assert result.dc_id == 2
    assert result.user_id == 999888
    assert result.error is None

    mock_candidate_client.connect.assert_awaited_once()
    mock_candidate_client.disconnect.assert_awaited_once()
    # 主客户端连接纳入锁内：由引用计数上下文管理，不得在锁外手动 disconnect
    mock_main_client.__aenter__.assert_awaited_once()
    mock_main_client.__aexit__.assert_awaited_once()
    mock_main_client.disconnect.assert_not_awaited()
    # Main client should have invoked AcceptLoginToken with the token bytes
    assert mock_main_client.invoke.await_count == 1
    call_arg = mock_main_client.invoke.call_args[0][0]
    assert isinstance(call_arg, raw.functions.auth.AcceptLoginToken)
    assert call_arg.token == b"valid_token_bytes"


@pytest.mark.asyncio
async def test_export_standalone_session_handles_dc_migration():
    account_name = "test_acc_dc"
    mock_service = MagicMock()
    mock_service.account_exists.return_value = True
    mock_service.verify_account_proxy = AsyncMock()

    mock_main_client = MagicMock()
    mock_main_client.is_connected = True
    mock_main_client.invoke = AsyncMock()
    mock_service._build_account_client.return_value = (mock_main_client, None)

    mock_candidate_client = MagicMock()
    mock_candidate_client.is_connected = False
    mock_candidate_client.connect = AsyncMock()
    mock_candidate_client.disconnect = AsyncMock()
    mock_candidate_client.session = MagicMock()
    mock_candidate_client.session.stop = AsyncMock()
    mock_candidate_client.export_session_string = AsyncMock(return_value="migrated_dc4_session_str")
    mock_candidate_client.storage = MagicMock()
    mock_candidate_client.storage.dc_id = AsyncMock(return_value=4)
    mock_candidate_client.storage.auth_key = AsyncMock()
    mock_candidate_client.storage.user_id = AsyncMock(return_value=777)
    mock_candidate_client.storage.is_bot = AsyncMock()
    mock_candidate_client.storage.test_mode = AsyncMock(return_value=False)

    fake_raw_user = MagicMock(spec=raw.types.User)
    fake_raw_user.id = 777
    fake_auth = MagicMock(spec=raw.types.auth.Authorization)
    fake_auth.user = fake_raw_user

    # 1st call on DC 2 -> LoginTokenMigrateTo(dc_id=4)
    # 2nd call on DC 4 -> LoginToken
    # 3rd call on DC 4 -> LoginTokenSuccess
    migrate_resp = raw.types.auth.LoginTokenMigrateTo(dc_id=4, token=b"migrate_tok")
    exported_token = raw.types.auth.LoginToken(expires=100, token=b"migrated_token_bytes")
    success_token = raw.types.auth.LoginTokenSuccess(authorization=fake_auth)

    mock_candidate_client.invoke = AsyncMock(side_effect=[migrate_resp, exported_token, success_token])

    with patch("backend.services.telegram.session_exporter.Client", return_value=mock_candidate_client), \
         patch("backend.services.telegram.session_exporter.resolve_telegram_api_credentials", return_value=(12345, "test_hash")), \
         patch("backend.services.telegram.session_exporter.get_config_service") as mock_cfg_svc, \
         patch("backend.services.telegram.session_exporter.Auth") as mock_auth_cls, \
         patch("backend.services.telegram.session_exporter.Session") as mock_session_cls:
        mock_cfg_svc.return_value.get_global_settings.return_value = {"require_proxy_for_telegram": False}
        mock_cfg_svc.return_value.get_telegram_config.return_value = {}

        mock_auth_instance = MagicMock()
        mock_auth_instance.create = AsyncMock(return_value=b"new_auth_key_dc4")
        mock_auth_cls.return_value = mock_auth_instance

        mock_session_instance = MagicMock()
        mock_session_instance.start = AsyncMock()
        mock_session_cls.return_value = mock_session_instance

        result = await create_standalone_session_export(
            account_name,
            timeout_seconds=10.0,
            service=mock_service,
        )

    assert result.success is True
    assert result.session_string == "migrated_dc4_session_str"
    assert result.dc_id == 4
    assert result.user_id == 777
    assert result.error is None
    mock_candidate_client.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_export_standalone_session_handles_missing_account():
    mock_service = MagicMock()
    mock_service.account_exists.return_value = False

    result = await create_standalone_session_export(
        "non_existent_acc",
        service=mock_service,
    )

    assert result.success is False
    assert result.session_string is None
    assert "ACCOUNT_NOT_FOUND" in (result.error or "")


@pytest.mark.asyncio
async def test_export_standalone_session_handles_lock_timeout():
    account_name = "busy_acc"
    mock_service = MagicMock()
    mock_service.account_exists.return_value = True
    mock_service.verify_account_proxy = AsyncMock()

    mock_candidate_client = MagicMock()
    mock_candidate_client.is_connected = False
    mock_candidate_client.connect = AsyncMock()
    mock_candidate_client.disconnect = AsyncMock()
    mock_candidate_client.storage = MagicMock()
    mock_candidate_client.storage.test_mode = AsyncMock(return_value=False)

    exported_token = raw.types.auth.LoginToken(expires=100, token=b"tok_bytes")
    mock_candidate_client.invoke = AsyncMock(return_value=exported_token)

    with patch("backend.services.telegram.session_exporter.Client", return_value=mock_candidate_client), \
         patch("backend.services.telegram.session_exporter.resolve_telegram_api_credentials", return_value=(12345, "test_hash")), \
         patch("backend.services.telegram.session_exporter.get_config_service") as mock_cfg_svc, \
         patch("backend.services.telegram.session_exporter.acquire_account_lock_with_timeout") as mock_lock:
        mock_cfg_svc.return_value.get_global_settings.return_value = {"require_proxy_for_telegram": False}
        mock_cfg_svc.return_value.get_telegram_config.return_value = {}

        mock_lock.side_effect = AccountLockTimeout("ACCOUNT_BUSY")

        result = await create_standalone_session_export(
            account_name,
            timeout_seconds=5.0,
            service=mock_service,
        )

    assert result.success is False
    assert result.error == "ACCOUNT_BUSY"
    # Ensure candidate client cleanup was still invoked
    mock_candidate_client.disconnect.assert_awaited_once()


def test_export_standalone_session_route_success(api_client, db):  # noqa: F811
    token = _login(api_client)
    mock_svc = MagicMock()
    mock_svc.account_exists.return_value = True
    mock_svc.export_standalone_session = AsyncMock(
        return_value=SessionExportResult(
            success=True,
            session_string="1BVtsOHQBu2...standalone_key",
            dc_id=2,
            user_id=1234567,
            error=None,
        )
    )

    with patch("backend.api.routes.accounts.get_telegram_service", return_value=mock_svc):
        resp = api_client.post(
            "/api/accounts/my_test_acc/session-exports",
            json={"device_model": "TG-SignPulse Export", "timeout_seconds": 30.0},
            headers=_auth(token),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["session_string"] == "1BVtsOHQBu2...standalone_key"
    assert data["dc_id"] == 2
    assert data["user_id"] == 1234567
    mock_svc.export_standalone_session.assert_awaited_once_with(
        "my_test_acc",
        device_model="TG-SignPulse Export",
        timeout_seconds=30.0,
    )


@pytest.mark.asyncio
async def test_export_standalone_session_handles_2fa():
    account_name = "acc_2fa"
    mock_service = MagicMock()
    mock_service.account_exists.return_value = True
    mock_service.verify_account_proxy = AsyncMock()

    mock_candidate_client = MagicMock()
    mock_candidate_client.is_connected = False
    mock_candidate_client.connect = AsyncMock()
    mock_candidate_client.disconnect = AsyncMock()
    mock_candidate_client.storage = MagicMock()

    exported_token = raw.types.auth.LoginToken(expires=100, token=b"tok_2fa")
    mock_candidate_client.invoke = AsyncMock(side_effect=[exported_token, SessionPasswordNeeded()])

    mock_main_client = MagicMock()
    mock_main_client.is_connected = True
    mock_main_client.invoke = AsyncMock()
    mock_service._build_account_client.return_value = (mock_main_client, None)

    with patch("backend.services.telegram.session_exporter.Client", return_value=mock_candidate_client), \
         patch("backend.services.telegram.session_exporter.resolve_telegram_api_credentials", return_value=(12345, "test_hash")), \
         patch("backend.services.telegram.session_exporter.get_config_service") as mock_cfg_svc:
        mock_cfg_svc.return_value.get_global_settings.return_value = {"require_proxy_for_telegram": False}
        mock_cfg_svc.return_value.get_telegram_config.return_value = {}

        result = await create_standalone_session_export(
            account_name,
            timeout_seconds=5.0,
            service=mock_service,
        )

    assert result.success is False
    assert "2FA_NOT_SUPPORTED" in result.error
    mock_candidate_client.disconnect.assert_awaited_once()


def test_export_standalone_session_route_busy_409(api_client, db):  # noqa: F811
    token = _login(api_client)
    mock_svc = MagicMock()
    mock_svc.account_exists.return_value = True
    mock_svc.export_standalone_session = AsyncMock(
        return_value=SessionExportResult(
            success=False,
            error="ACCOUNT_BUSY",
        )
    )

    with patch("backend.api.routes.accounts.get_telegram_service", return_value=mock_svc):
        resp = api_client.post(
            "/api/accounts/busy_acc/session-exports",
            headers=_auth(token),
        )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "ACCOUNT_BUSY"


def test_export_standalone_session_route_not_found_404(api_client, db):  # noqa: F811
    token = _login(api_client)
    mock_svc = MagicMock()
    mock_svc.account_exists.return_value = False

    with patch("backend.api.routes.accounts.get_telegram_service", return_value=mock_svc):
        resp = api_client.post(
            "/api/accounts/missing_acc/session-exports",
            headers=_auth(token),
        )

    assert resp.status_code == 404
    assert "账号不存在" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_migrate_candidate_dc_fails_closed_on_unknown_dc():
    from backend.services.telegram.session_exporter import _migrate_candidate_dc

    mock_client = MagicMock()
    mock_client.storage.dc_id = AsyncMock()
    mock_client.storage.test_mode = AsyncMock(return_value=0)
    mock_client.session = MagicMock()
    mock_client.session.stop = AsyncMock()

    with pytest.raises(ValueError, match="无法确定目标 DC 999 的连接端点"):
        await _migrate_candidate_dc(mock_client, target_dc=999)

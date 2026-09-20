"""Standalone session exporter service.

Derives a standalone SessionString using Telegram's official auth.ExportLoginToken
and auth.AcceptLoginToken handshake protocol, providing a completely separate AuthKey
without requiring re-entering phone number or SMS code.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any, Optional

from pyrogram import Client, raw
from pyrogram.errors import SessionPasswordNeeded
from pyrogram.session import Session
from pyrogram.session.auth import Auth

from backend.services.config import get_config_service
from backend.services.telegram.credentials import resolve_telegram_api_credentials
from backend.utils.account_locks import (
    AccountLockTimeout,
    acquire_account_lock_with_timeout,
)
from backend.utils.names import validate_storage_name
from backend.utils.proxy import build_proxy_dict
from backend.utils.tg_session import get_account_profile

logger = logging.getLogger("backend.telegram.session_exporter")


@dataclass
class SessionExportResult:
    success: bool
    session_string: Optional[str] = None
    dc_id: Optional[int] = None
    user_id: Optional[int] = None
    error: Optional[str] = None


async def _migrate_candidate_dc(client: Client, target_dc: int) -> None:
    """Migrate candidate client session to target data center."""
    server_address = None
    port = None
    if hasattr(client, "get_dc_option") and callable(client.get_dc_option):
        try:
            dc_opt = await client.get_dc_option(target_dc)
            if dc_opt:
                server_address = getattr(dc_opt, "ip_address", None)
                port = getattr(dc_opt, "port", None)
        except Exception as exc:
            logger.debug("Failed getting dc option before stop: %s", exc)

    if getattr(client, "session", None) and hasattr(client.session, "stop"):
        try:
            await client.session.stop()
        except Exception as exc:
            logger.debug("Stopping session before DC migrate: %s", exc)

    await client.storage.dc_id(target_dc)
    test_mode = await client.storage.test_mode()

    if not server_address or not port:
        from backend.services.telegram.session_importer import (
            get_default_dc_endpoint,
        )
        try:
            default_addr, default_port = get_default_dc_endpoint(target_dc, bool(test_mode))
            server_address = server_address or default_addr
            port = port or default_port
        except Exception as exc:
            raise ValueError(f"无法确定目标 DC {target_dc} 的连接端点，迁移中止: {exc}") from exc

    import inspect
    auth_sig = inspect.signature(Auth.__init__)
    if "server_address" in auth_sig.parameters:
        auth_obj = Auth(client, target_dc, server_address, port, test_mode)
    else:
        auth_obj = Auth(client, target_dc, test_mode)
    auth_key = await auth_obj.create()
    await client.storage.auth_key(auth_key)

    session_sig = inspect.signature(Session.__init__)
    if "server_address" in session_sig.parameters:
        client.session = Session(client, target_dc, server_address, port, auth_key, test_mode)
    else:
        client.session = Session(client, target_dc, auth_key, test_mode)
    await client.session.start()
    client.is_connected = True


async def create_standalone_session_export(
    account_name: str,
    *,
    device_model: str = "TG-SignPulse Exported Session",
    timeout_seconds: float = 60.0,
    service: Optional[Any] = None,
) -> SessionExportResult:
    """Derives a new standalone session string from an active logged-in account."""
    try:
        account_name = validate_storage_name(account_name, field_name="account_name")
    except ValueError as e:
        return SessionExportResult(success=False, error=f"INVALID_ACCOUNT_NAME: {e}")

    if service is None:
        from backend.services.telegram import get_telegram_service

        service = get_telegram_service()

    if not service.account_exists(account_name):
        return SessionExportResult(success=False, error="ACCOUNT_NOT_FOUND")

    # Proxy resolution and policy checks
    profile = get_account_profile(account_name) or {}
    proxy_value = profile.get("proxy")
    if not proxy_value:
        proxy_value = get_config_service().get_global_settings().get("global_proxy")
    proxy_dict = build_proxy_dict(proxy_value) if proxy_value else None

    global_settings = get_config_service().get_global_settings()
    if bool(global_settings.get("require_proxy_for_telegram", False)) and not proxy_dict:
        return SessionExportResult(
            success=False,
            error="PROXY_REQUIRED_BLOCKED: Global policy requires proxy",
        )

    try:
        if hasattr(service, "verify_account_proxy"):
            await service.verify_account_proxy(account_name, proxy_dict)
    except Exception as exc:
        return SessionExportResult(
            success=False,
            error=f"PROXY_VERIFICATION_FAILED: {exc}",
        )

    # Resolve API credentials
    try:
        api_id, api_hash = resolve_telegram_api_credentials(
            get_config_service().get_telegram_config(),
            env_api_id=os.getenv("TG_API_ID"),
            env_api_hash=os.getenv("TG_API_HASH"),
        )
    except Exception as exc:
        return SessionExportResult(
            success=False,
            error=f"CREDENTIALS_RESOLUTION_FAILED: {exc}",
        )

    temp_name = f"candidate_export_{secrets.token_hex(6)}"
    candidate_client = Client(
        name=temp_name,
        in_memory=True,
        api_id=api_id,
        api_hash=api_hash,
        proxy=proxy_dict,
        device_model=device_model,
        no_updates=True,
    )

    try:
        await candidate_client.connect()
        candidate_client.is_connected = True

        # Step 4: Export initial login token
        export_result = await candidate_client.invoke(
            raw.functions.auth.ExportLoginToken(
                api_id=api_id, api_hash=api_hash, except_ids=[]
            )
        )

        migrate_count = 0
        while (
            isinstance(export_result, raw.types.auth.LoginTokenMigrateTo)
            and migrate_count < 3
        ):
            migrate_count += 1
            await _migrate_candidate_dc(candidate_client, export_result.dc_id)
            export_result = await candidate_client.invoke(
                raw.functions.auth.ExportLoginToken(
                    api_id=api_id, api_hash=api_hash, except_ids=[]
                )
            )

        token_bytes = getattr(export_result, "token", None)
        if not token_bytes:
            return SessionExportResult(
                success=False,
                error="EXPORT_TOKEN_FAILED: No token received from Telegram",
            )

        # Step 5: Main account accepts login token under account lock
        candidate_auth_hash = None
        main_client = None
        try:
            async with acquire_account_lock_with_timeout(account_name, timeout=15.0):
                main_client, _ = service._build_account_client(
                    account_name, no_updates=True
                )
                if not getattr(main_client, "is_connected", False):
                    await main_client.connect()
                accept_res = await main_client.invoke(
                    raw.functions.auth.AcceptLoginToken(token=token_bytes)
                )
                candidate_auth_hash = getattr(accept_res, "hash", None) or getattr(
                    getattr(accept_res, "authorization", None), "hash", None
                )
        except AccountLockTimeout as exc:
            logger.warning("Account lock timeout while exporting session for %s: %s", account_name, exc)
            return SessionExportResult(success=False, error="ACCOUNT_BUSY")
        except SessionPasswordNeeded:
            return SessionExportResult(
                success=False,
                error="2FA_NOT_SUPPORTED: Account has two-step verification enabled",
            )
        except Exception as exc:
            logger.error("Failed to accept login token on main client: %s", exc, exc_info=True)
            return SessionExportResult(
                success=False,
                error=f"ACCEPT_LOGIN_TOKEN_FAILED: {exc}",
            )

        async def _rollback_candidate_auth() -> None:
            if main_client and candidate_auth_hash:
                with contextlib.suppress(Exception):
                    reset_auth_cls = getattr(raw.functions.account, "ResetAuthorization", None)
                    if reset_auth_cls:
                        await main_client.invoke(reset_auth_cls(hash=candidate_auth_hash))

        # Step 6: Candidate client polls for LoginTokenSuccess
        poll_start = time.monotonic()
        poll_deadline = poll_start + max(5.0, timeout_seconds)
        success_result = None

        while time.monotonic() < poll_deadline:
            try:
                check_result = await candidate_client.invoke(
                    raw.functions.auth.ExportLoginToken(
                        api_id=api_id, api_hash=api_hash, except_ids=[]
                    )
                )
            except SessionPasswordNeeded:
                await _rollback_candidate_auth()
                return SessionExportResult(
                    success=False,
                    error="2FA_NOT_SUPPORTED: Account has two-step verification enabled",
                )
            except Exception as exc:
                logger.warning("Error polling ExportLoginToken: %s", exc)
                await asyncio.sleep(1.0)
                continue

            if isinstance(check_result, raw.types.auth.LoginTokenSuccess):
                success_result = check_result
                break
            elif isinstance(check_result, raw.types.auth.LoginTokenMigrateTo):
                await _migrate_candidate_dc(candidate_client, check_result.dc_id)

            await asyncio.sleep(1.0)

        if success_result is None:
            await _rollback_candidate_auth()
            return SessionExportResult(
                success=False,
                error="EXPORT_LOGIN_TIMEOUT: Timeout waiting for candidate authorization",
            )

        # Step 7: Authorize candidate client storage
        auth_user = getattr(success_result.authorization, "user", None)
        user_id = getattr(auth_user, "id", None)
        if user_id is not None:
            await candidate_client.storage.user_id(user_id)
            await candidate_client.storage.is_bot(False)

        # Step 8: Export session string
        session_str = await candidate_client.export_session_string()
        dc_id = await candidate_client.storage.dc_id()
        if user_id is None:
            user_id = await candidate_client.storage.user_id()

        return SessionExportResult(
            success=True,
            session_string=session_str,
            dc_id=dc_id,
            user_id=user_id,
        )

    except Exception as exc:
        logger.error("Unexpected error during session export for %s: %s", account_name, exc, exc_info=True)
        return SessionExportResult(success=False, error=str(exc))
    finally:
        try:
            if getattr(candidate_client, "is_connected", False):
                await candidate_client.disconnect()
        except Exception as exc:
            logger.debug("Error disconnecting candidate client: %s", exc)

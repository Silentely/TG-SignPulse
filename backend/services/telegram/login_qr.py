"""TelegramService mixin: login_qr."""
from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import os
import secrets
import time
from typing import Any, Dict, Optional

from backend.core.config import get_settings
from backend.services.telegram.sessions import (
    _cleanup_expired_login_sessions,
    _qr_login_sessions,
)
from backend.utils.account_locks import get_account_lock
from backend.utils.proxy import build_proxy_dict
from backend.utils.tg_session import (
    get_global_semaphore,
    get_session_mode,
)
from backend.utils.time import utc_from_timestamp_iso_z
from tg_signer.async_utils import create_logged_task

settings = get_settings()


logger = logging.getLogger("backend.qr_login")

class TelegramQrLoginMixin:

    def _log_qr_state(
        self, login_id: str, state: str, data: Optional[Dict[str, Any]] = None
    ) -> None:
        if not login_id:
            return
        if data is not None:
            last_state = data.get("last_state_logged")
            if last_state == state:
                return
            data["last_state_logged"] = state
        logger.info("qr_login state=%s login_id=%s", state, login_id)


    async def _apply_migrate_auth(self, client, data: Dict[str, Any]) -> None:
        migrate_dc_id = data.get("migrate_dc_id")
        migrate_auth_key = data.get("migrate_auth_key")
        if migrate_dc_id and migrate_auth_key:
            try:
                await client.storage.dc_id(migrate_dc_id)
                await client.storage.auth_key(migrate_auth_key)
            except Exception:
                pass


    @staticmethod
    def _capture_migrate_auth(data: Dict[str, Any], session: Any) -> None:
        if not session:
            return
        try:
            auth_key = getattr(session, "auth_key", None)
            dc_id = getattr(session, "dc_id", None)
            if auth_key:
                data["migrate_auth_key"] = auth_key
            if dc_id:
                data["migrate_dc_id"] = dc_id
        except Exception:
            pass


    async def _cleanup_qr_login(self, login_id: str, preserve_session: bool = False) -> None:
        data = _qr_login_sessions.pop(login_id, None)
        if not data:
            return
        expire_task = data.get("expire_task")
        current_task = asyncio.current_task()
        if (
            expire_task is not None
            and expire_task is not current_task
            and not expire_task.done()
        ):
            expire_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await expire_task
        client = data.get("client")
        handler = data.get("handler")
        if client and handler:
            try:
                client.remove_handler(*handler)
            except Exception:
                pass
        if client:
            try:
                if getattr(client, "is_initialized", False):
                    await client.stop()
                elif getattr(client, "is_connected", False):
                    await client.disconnect()
            except Exception:
                try:
                    if getattr(client, "is_connected", False):
                        await client.disconnect()
                except Exception:
                    pass
        if not preserve_session:
            session_mode = get_session_mode()
            if session_mode == "file":
                account_name = data.get("account_name")
                if account_name:
                    session_file = self.session_dir / f"{account_name}.session"
                    if session_file.exists():
                        try:
                            session_file.unlink()
                            for ext in [".session-journal", ".session-wal", ".session-shm"]:
                                aux_file = self.session_dir / f"{account_name}{ext}"
                                if aux_file.exists():
                                    aux_file.unlink()
                        except Exception:
                            pass
        lock = data.get("lock")
        if lock and lock.locked():
            lock.release()


    def _extend_qr_expires(self, data: Dict[str, Any], min_seconds: int = 300) -> None:
        now = int(time.time())
        min_expires = now + min_seconds
        current = int(data.get("expires_ts") or 0)
        if current < min_expires:
            data["expires_ts"] = min_expires
            data["expires_at"] = utc_from_timestamp_iso_z(min_expires)


    async def _expire_qr_login(self, login_id: str, expires_ts: int) -> None:
        while True:
            wait_seconds = max(0, int(expires_ts - time.time()))
            if wait_seconds:
                await asyncio.sleep(wait_seconds)
            data = _qr_login_sessions.get(login_id)
            if not data:
                return
            current_expires = int(data.get("expires_ts") or 0)
            if current_expires > expires_ts:
                expires_ts = current_expires
                continue
            data["status"] = "expired"
            self._log_qr_state(login_id, "expired", data)
            await self._cleanup_qr_login(login_id)
            return


    async def start_qr_login(
        self, account_name: str, proxy: Optional[str] = None
    ) -> Dict[str, Any]:

        account_name = self._normalize_account_name(account_name)

        from pyrogram import Client, handlers, raw
        from pyrogram.errors import FloodWait

        from tg_signer.core import close_client_by_name

        await _cleanup_expired_login_sessions()

        account_lock = get_account_lock(account_name)
        session_mode = get_session_mode()
        global_semaphore = get_global_semaphore()

        # 清理同账号残留的扫码会话
        for key, value in list(_qr_login_sessions.items()):
            if value.get("account_name") == account_name:
                await self._cleanup_qr_login(key)

        await account_lock.acquire()

        def _release_account_lock() -> None:
            if account_lock.locked():
                account_lock.release()

        # 清理后台客户端
        try:
            await close_client_by_name(account_name, workdir=self.session_dir)
        except Exception:
            pass

        # API credentials
        from backend.services.config import get_config_service

        config_service = get_config_service()
        tg_config = config_service.get_telegram_config()
        api_id = os.getenv("TG_API_ID") or tg_config.get("api_id")
        api_hash = os.getenv("TG_API_HASH") or tg_config.get("api_hash")

        try:
            api_id = int(api_id) if api_id is not None else None
        except (TypeError, ValueError):
            api_id = None

        if isinstance(api_hash, str):
            api_hash = api_hash.strip()

        if not api_id or not api_hash:
            _release_account_lock()
            raise ValueError("Telegram API ID / API Hash 未配置或无效")

        if not proxy:
            global_proxy = config_service.get_global_settings().get("global_proxy")
            if global_proxy:
                proxy = global_proxy

        proxy_dict = build_proxy_dict(proxy) if proxy else None

        # 清理旧 session 文件（与手机号登录保持一致）
        if session_mode == "file":
            session_file = self.session_dir / f"{account_name}.session"
            if session_file.exists():
                try:
                    session_file.unlink()
                    for ext in [".session-journal", ".session-wal", ".session-shm"]:
                        aux_file = self.session_dir / f"{account_name}{ext}"
                        if aux_file.exists():
                            aux_file.unlink()
                except OSError:
                    pass

        session_path = str(self.session_dir / account_name)
        client_kwargs = {
            "name": session_path,
            "api_id": api_id,
            "api_hash": api_hash,
            "proxy": proxy_dict,
            "in_memory": session_mode == "string",
        }
        # QR 登录依赖 UpdateLoginToken，必须启用 updates（无论 session 模式）
        client_kwargs["no_updates"] = False
        client = Client(**client_kwargs)

        try:
            async with global_semaphore:
                await client.connect()

                if hasattr(client, "storage") and getattr(client.storage, "conn", None):
                    try:
                        client.storage.conn.execute("PRAGMA journal_mode=WAL")
                        client.storage.conn.execute("PRAGMA busy_timeout=30000")
                    except Exception:
                        pass

                result = await client.invoke(
                    raw.functions.auth.ExportLoginToken(
                        api_id=api_id, api_hash=api_hash, except_ids=[]
                    )
                )

            token_bytes = getattr(result, "token", None)
            if not token_bytes:
                raise ValueError("获取二维码 token 失败")

            token_expires = getattr(result, "expires", None)
            expires_ts = self._normalize_login_token_expires(token_expires)
            expires_at = utc_from_timestamp_iso_z(expires_ts)
            qr_uri = "tg://login?token=" + base64.urlsafe_b64encode(
                token_bytes
            ).decode("utf-8")

            login_id = secrets.token_urlsafe(16)

            session_data = {
                "account_name": account_name,
                "proxy": proxy,
                "client": client,
                "token": token_bytes,
                "expires_ts": expires_ts,
                "expires_at": expires_at,
                "status": "waiting_scan",
                "scan_seen": False,
                "lock": account_lock,
                "migrate_dc_id": getattr(result, "dc_id", None),
                "api_id": api_id,
                "api_hash": api_hash,
                "handler": None,
                "_created_at": time.monotonic(),
            }
            _qr_login_sessions[login_id] = session_data
            self._log_qr_state(login_id, "waiting_scan", session_data)

            # 监听扫码更新
            try:
                # 初始化 updates/dispatcher，确保后续 stop 能完整关闭
                try:
                    if not getattr(client, "is_initialized", False):
                        await client.initialize()
                except Exception:
                    try:
                        await client.dispatcher.start()
                    except Exception:
                        pass

                async def _raw_handler(_, update, __, ___):
                    if not isinstance(update, raw.types.UpdateLoginToken):
                        return
                    data = _qr_login_sessions.get(login_id)
                    if data and data.get("status") in ("waiting_scan", "scanned_wait_confirm"):
                        new_token = getattr(update, "token", None)
                        if new_token:
                            data["token"] = new_token
                        token_expires = getattr(update, "expires", None)
                        if token_expires:
                            data["expires_ts"] = self._normalize_login_token_expires(
                                token_expires
                            )
                            data["expires_at"] = utc_from_timestamp_iso_z(
                                data["expires_ts"]
                            )
                        data["scan_seen"] = True
                        data["status"] = "scanned_wait_confirm"
                        self._log_qr_state(login_id, "scanned_wait_confirm", data)

                handler = client.add_handler(handlers.RawUpdateHandler(_raw_handler))
                session_data["handler"] = handler
            except Exception:
                pass

            session_data["expire_task"] = create_logged_task(
                self._expire_qr_login(login_id, expires_ts),
                logger=logger,
                description=f"QR login expiry watcher {login_id}",
            )

            return {
                "login_id": login_id,
                "qr_uri": qr_uri,
                "expires_at": expires_at,
            }

        except FloodWait as e:
            try:
                await client.disconnect()
            except Exception:
                pass
            _release_account_lock()
            raise ValueError(f"请求过于频繁，请等待 {e.value} 秒后重试")
        except Exception as e:
            try:
                await client.disconnect()
            except Exception:
                pass
            _release_account_lock()
            raise ValueError(f"获取二维码失败: {str(e)}")


    async def get_qr_login_status(self, login_id: str) -> Dict[str, Any]:
        from pyrogram import raw, types
        from pyrogram.errors import FloodWait, SessionPasswordNeeded, Unauthorized
        from pyrogram.methods.messages.inline_session import get_session

        data = _qr_login_sessions.get(login_id)
        if not data:
            return {
                "status": "expired",
                "message": "二维码已过期或不存在",
            }

        if time.time() >= data.get("expires_ts", 0):
            self._log_qr_state(login_id, "expired", data)
            await self._cleanup_qr_login(login_id)
            return {
                "status": "expired",
                "message": "二维码已过期",
            }

        if data.get("status") == "password_required":
            self._log_qr_state(login_id, "password_required", data)
            return {
                "status": "password_required",
                "expires_at": data.get("expires_at"),
                "message": "需要 2FA 密码",
            }

        # 扫码后状态保持，避免回退到 waiting_scan
        if data.get("status") == "scanned_wait_confirm":
            data["scan_seen"] = True
            self._extend_qr_expires(data)

        # 未扫码时不要调用 ImportLoginToken，避免服务端轮转 token 导致二维码失效
        if not data.get("scan_seen") and data.get("status") == "waiting_scan":
            self._log_qr_state(login_id, "waiting_scan", data)
            return {
                "status": "waiting_scan",
                "expires_at": data.get("expires_at"),
            }

        client = data.get("client")
        token = data.get("token")
        migrate_dc_id = data.get("migrate_dc_id")

        async def _finalize_login(login_result: Any) -> Dict[str, Any]:
            # 标记授权用户
            user = types.User._parse(client, login_result.authorization.user)
            await client.storage.user_id(user.id)
            await client.storage.is_bot(False)
            data["authorized"] = True
            data["authorized_user"] = user

            # 获取用户信息并持久化会话
            try:
                try:
                    me = await client.get_me()
                except Exception:
                    me = user

                try:
                    password_state = await client.get_password()
                except Exception:
                    password_state = None

                if password_state and getattr(password_state, "has_password", False):
                    data["status"] = "password_required"
                    data["scan_seen"] = True
                    self._extend_qr_expires(data)
                    self._log_qr_state(login_id, "password_required", data)
                    return {
                        "status": "password_required",
                        "expires_at": data.get("expires_at"),
                        "message": "需要 2FA 密码",
                    }

                await self._apply_migrate_auth(client, data)
                await self._persist_client_session(
                    client, data.get("account_name"), data.get("proxy")
                )
            except SessionPasswordNeeded:
                data["status"] = "password_required"
                data["scan_seen"] = True
                self._extend_qr_expires(data)
                self._log_qr_state(login_id, "password_required", data)
                return {
                    "status": "password_required",
                    "expires_at": data.get("expires_at"),
                    "message": "需要 2FA 密码",
                }

            self._log_qr_state(login_id, "success", data)
            account_name = data.get("account_name")
            await self._cleanup_qr_login(login_id, preserve_session=True)

            account = None
            try:
                accounts = self.list_accounts(force_refresh=True)
                account = next(
                    (acc for acc in accounts if acc.get("name") == account_name),
                    None,
                )
            except Exception:
                account = None

            return {
                "status": "success",
                "message": "登录成功",
                "account": account,
                "user_id": me.id,
                "first_name": me.first_name,
                "username": me.username,
            }

        try:
            if not client.is_connected:
                await client.connect()

            result = None
            # 扫码确认后应再次调用 ExportLoginToken（官方流程）
            if data.get("status") == "scanned_wait_confirm":
                now = time.time()
                last_import_ts = data.get("last_import_ts", 0)
                if now - last_import_ts < 2:
                    status = (
                        "scanned_wait_confirm"
                        if data.get("scan_seen")
                        else data.get("status", "waiting_scan")
                    )
                    self._log_qr_state(login_id, status, data)
                    return {
                        "status": status,
                        "expires_at": data.get("expires_at"),
                    }
                data["last_import_ts"] = now

                token = data.get("token")
                migrate_dc_id = data.get("migrate_dc_id")
                result = None
                if token:
                    try:
                        for _ in range(2):
                            if migrate_dc_id:
                                session = await get_session(client, migrate_dc_id)
                                self._capture_migrate_auth(data, session)
                                result = await session.invoke(
                                    raw.functions.auth.ImportLoginToken(token=token)
                                )
                            else:
                                result = await client.invoke(
                                    raw.functions.auth.ImportLoginToken(token=token)
                                )

                            if isinstance(result, raw.types.auth.LoginTokenMigrateTo):
                                migrate_dc_id = result.dc_id
                                token = result.token
                                data["migrate_dc_id"] = migrate_dc_id
                                data["token"] = token
                                continue
                            break
                    except SessionPasswordNeeded:
                        data["status"] = "password_required"
                        data["scan_seen"] = True
                        data["authorized"] = True
                        self._extend_qr_expires(data)
                        self._log_qr_state(login_id, "password_required", data)
                        return {
                            "status": "password_required",
                            "expires_at": data.get("expires_at"),
                            "message": "需要 2FA 密码",
                        }
                    except Exception:
                        pass

                if isinstance(result, raw.types.auth.LoginTokenSuccess):
                    return await _finalize_login(result)
                if isinstance(result, raw.types.auth.LoginToken):
                    token_expires = getattr(result, "expires", None)
                    if token_expires:
                        data["expires_ts"] = self._normalize_login_token_expires(
                            token_expires
                        )
                        data["expires_at"] = utc_from_timestamp_iso_z(
                            data["expires_ts"]
                        )
                    if result.token:
                        data["token"] = result.token
                    data["status"] = "scanned_wait_confirm"

                # fallback: 再次调用 ExportLoginToken 获取最终状态（符合官方流程）
                if result is None or isinstance(result, raw.types.auth.LoginToken):
                    last_export_ts = data.get("last_export_ts", 0)
                    if now - last_export_ts >= 3:
                        api_id = data.get("api_id")
                        api_hash = data.get("api_hash")
                        if not api_id or not api_hash:
                            try:
                                from backend.services.config import get_config_service

                                tg_config = get_config_service().get_telegram_config()
                                api_id = os.getenv("TG_API_ID") or tg_config.get("api_id")
                                api_hash = os.getenv("TG_API_HASH") or tg_config.get("api_hash")
                                try:
                                    api_id = int(api_id) if api_id is not None else None
                                except (TypeError, ValueError):
                                    api_id = None
                                if isinstance(api_hash, str):
                                    api_hash = api_hash.strip()
                                if api_id and api_hash:
                                    data["api_id"] = api_id
                                    data["api_hash"] = api_hash
                            except Exception:
                                api_id = None
                                api_hash = None

                        if api_id and api_hash:
                            data["last_export_ts"] = now
                            try:
                                export_result = await client.invoke(
                                    raw.functions.auth.ExportLoginToken(
                                        api_id=api_id, api_hash=api_hash, except_ids=[]
                                    )
                                )
                                if isinstance(export_result, raw.types.auth.LoginTokenSuccess):
                                    return await _finalize_login(export_result)
                                if isinstance(export_result, raw.types.auth.LoginTokenMigrateTo):
                                    data["migrate_dc_id"] = export_result.dc_id
                                    data["token"] = export_result.token
                                    try:
                                        session = await get_session(client, export_result.dc_id)
                                        self._capture_migrate_auth(data, session)
                                        migrate_result = await session.invoke(
                                            raw.functions.auth.ImportLoginToken(token=export_result.token)
                                        )
                                        if isinstance(migrate_result, raw.types.auth.LoginTokenSuccess):
                                            return await _finalize_login(migrate_result)
                                    except SessionPasswordNeeded:
                                        data["status"] = "password_required"
                                        data["scan_seen"] = True
                                        self._extend_qr_expires(data)
                                        self._log_qr_state(login_id, "password_required", data)
                                        return {
                                            "status": "password_required",
                                            "expires_at": data.get("expires_at"),
                                            "message": "需要 2FA 密码",
                                        }
                                    except Exception:
                                        pass
                                elif isinstance(export_result, raw.types.auth.LoginToken):
                                    token_expires = getattr(export_result, "expires", None)
                                    if token_expires:
                                        data["expires_ts"] = self._normalize_login_token_expires(
                                            token_expires
                                        )
                                        data["expires_at"] = utc_from_timestamp_iso_z(
                                            data["expires_ts"]
                                        )
                                    if export_result.token:
                                        data["token"] = export_result.token
                                    data["status"] = "scanned_wait_confirm"
                            except Exception:
                                pass

            status = (
                "scanned_wait_confirm"
                if data.get("scan_seen")
                else data.get("status", "waiting_scan")
            )
            self._log_qr_state(login_id, status, data)
            return {
                "status": status,
                "expires_at": data.get("expires_at"),
            }

        except FloodWait as e:
            self._log_qr_state(login_id, "failed", data)
            await self._cleanup_qr_login(login_id)
            return {
                "status": "failed",
                "message": f"请求过于频繁，请等待 {e.value} 秒后重试",
            }
        except SessionPasswordNeeded:
            data = _qr_login_sessions.get(login_id)
            if data:
                data["status"] = "password_required"
                data["scan_seen"] = True
                self._extend_qr_expires(data)
                data["authorized"] = True
                self._log_qr_state(login_id, "password_required", data)
            return {
                "status": "password_required",
                "expires_at": data.get("expires_at") if data else None,
                "message": "需要 2FA 密码",
            }
        except Unauthorized:
            self._log_qr_state(login_id, "failed", data)
            await self._cleanup_qr_login(login_id)
            return {
                "status": "failed",
                "message": "登录失败，请重试",
            }
        except Exception:
            self._log_qr_state(login_id, "failed", data)
            await self._cleanup_qr_login(login_id)
            return {
                "status": "failed",
                "message": "登录失败，请重试",
            }


    async def submit_qr_password(self, login_id: str, password: str) -> Dict[str, Any]:
        from pyrogram import raw, types
        from pyrogram.errors import (
            FloodWait,
            PasswordHashInvalid,
            SessionPasswordNeeded,
            Unauthorized,
        )
        from pyrogram.methods.messages.inline_session import get_session
        from pyrogram.utils import compute_password_check

        password = (password or "").strip()
        if not password:
            raise ValueError("2FA 密码不能为空")

        data = _qr_login_sessions.get(login_id)
        if not data:
            raise ValueError("二维码已过期或不存在")

        if time.time() >= data.get("expires_ts", 0):
            if data.get("status") in {"password_required", "authorized"}:
                self._extend_qr_expires(data)
            else:
                await self._cleanup_qr_login(login_id)
                raise ValueError("二维码已过期")

        client = data.get("client")
        if not client:
            await self._cleanup_qr_login(login_id)
            raise ValueError("登录会话已失效")

        account_lock = data.get("lock")
        if account_lock and not account_lock.locked():
            await account_lock.acquire()

        global_semaphore = get_global_semaphore()

        async def _finalize_password_login(user_fallback=None) -> Dict[str, Any]:
            user_from_password = None
            try:
                if data.get("migrate_dc_id"):
                    session = await get_session(client, data.get("migrate_dc_id"))
                    self._capture_migrate_auth(data, session)
                    auth = await session.invoke(
                        raw.functions.auth.CheckPassword(
                            password=compute_password_check(
                                await session.invoke(raw.functions.account.GetPassword()),
                                password,
                            )
                        )
                    )
                    user_from_password = types.User._parse(client, auth.user)
                    await client.storage.user_id(user_from_password.id)
                    await client.storage.is_bot(False)
                    data["authorized"] = True
                    data["authorized_user"] = user_from_password
                else:
                    user_from_password = await client.check_password(password)
                    data["authorized"] = True
                    data["authorized_user"] = user_from_password
            except PasswordHashInvalid:
                await self._cleanup_qr_login(login_id)
                raise ValueError("两步验证密码错误")

            try:
                if user_from_password is not None:
                    me = user_from_password
                else:
                    me = await client.get_me()
            except Exception:
                me = user_fallback

            await self._apply_migrate_auth(client, data)
            await self._persist_client_session(
                client, data.get("account_name"), data.get("proxy")
            )

            account_name = data.get("account_name")
            self._log_qr_state(login_id, "success", data)
            await self._cleanup_qr_login(login_id, preserve_session=True)

            account = None
            try:
                accounts = self.list_accounts(force_refresh=True)
                account = next(
                    (acc for acc in accounts if acc.get("name") == account_name),
                    None,
                )
            except Exception:
                account = None

            return {
                "status": "success",
                "message": "登录成功",
                "account": account,
                "user_id": getattr(me, "id", None),
                "first_name": getattr(me, "first_name", None),
                "username": getattr(me, "username", None),
            }

        try:
            async with global_semaphore:
                if not client.is_connected:
                    await client.connect()

                async def _ensure_authorized():
                    if data.get("authorized"):
                        return data.get("authorized_user")

                    token = data.get("token")
                    migrate_dc_id = data.get("migrate_dc_id")
                    result = None
                    if token:
                        try:
                            for _ in range(2):
                                if migrate_dc_id:
                                    session = await get_session(client, migrate_dc_id)
                                    self._capture_migrate_auth(data, session)
                                    result = await session.invoke(
                                        raw.functions.auth.ImportLoginToken(token=token)
                                    )
                                else:
                                    result = await client.invoke(
                                        raw.functions.auth.ImportLoginToken(token=token)
                                    )

                                if isinstance(result, raw.types.auth.LoginTokenMigrateTo):
                                    migrate_dc_id = result.dc_id
                                    token = result.token
                                    data["migrate_dc_id"] = migrate_dc_id
                                    data["token"] = token
                                    continue
                                break
                        except SessionPasswordNeeded:
                            data["status"] = "password_required"
                            data["scan_seen"] = True
                            data["authorized"] = True
                            self._extend_qr_expires(data)
                            return data.get("authorized_user")
                        except Exception:
                            result = None

                    if isinstance(result, raw.types.auth.LoginTokenSuccess):
                        user = types.User._parse(client, result.authorization.user)
                        await client.storage.user_id(user.id)
                        await client.storage.is_bot(False)
                        data["authorized"] = True
                        data["authorized_user"] = user
                        return user
                    if isinstance(result, raw.types.auth.LoginToken):
                        token_expires = getattr(result, "expires", None)
                        if token_expires:
                            data["expires_ts"] = self._normalize_login_token_expires(
                                token_expires
                            )
                            data["expires_at"] = utc_from_timestamp_iso_z(
                                data["expires_ts"]
                            )
                        if result.token:
                            data["token"] = result.token

                    api_id = data.get("api_id")
                    api_hash = data.get("api_hash")
                    if not api_id or not api_hash:
                        try:
                            from backend.services.config import get_config_service

                            tg_config = get_config_service().get_telegram_config()
                            api_id = os.getenv("TG_API_ID") or tg_config.get("api_id")
                            api_hash = os.getenv("TG_API_HASH") or tg_config.get(
                                "api_hash"
                            )
                            try:
                                api_id = int(api_id) if api_id is not None else None
                            except (TypeError, ValueError):
                                api_id = None
                            if isinstance(api_hash, str):
                                api_hash = api_hash.strip()
                            if api_id and api_hash:
                                data["api_id"] = api_id
                                data["api_hash"] = api_hash
                        except Exception:
                            api_id = None
                            api_hash = None

                    if api_id and api_hash:
                        try:
                            export_result = await client.invoke(
                                raw.functions.auth.ExportLoginToken(
                                    api_id=api_id, api_hash=api_hash, except_ids=[]
                                )
                            )
                            if isinstance(
                                export_result, raw.types.auth.LoginTokenSuccess
                            ):
                                user = types.User._parse(
                                    client, export_result.authorization.user
                                )
                                await client.storage.user_id(user.id)
                                await client.storage.is_bot(False)
                                data["authorized"] = True
                                data["authorized_user"] = user
                                return user
                            if isinstance(
                                export_result, raw.types.auth.LoginTokenMigrateTo
                            ):
                                data["migrate_dc_id"] = export_result.dc_id
                                data["token"] = export_result.token
                                try:
                                    session = await get_session(
                                        client, export_result.dc_id
                                    )
                                    self._capture_migrate_auth(data, session)
                                    migrate_result = await session.invoke(
                                        raw.functions.auth.ImportLoginToken(
                                            token=export_result.token
                                        )
                                    )
                                    if isinstance(
                                        migrate_result,
                                        raw.types.auth.LoginTokenSuccess,
                                    ):
                                        user = types.User._parse(
                                            client, migrate_result.authorization.user
                                        )
                                        await client.storage.user_id(user.id)
                                        await client.storage.is_bot(False)
                                        data["authorized"] = True
                                        data["authorized_user"] = user
                                        return user
                                except SessionPasswordNeeded:
                                    data["status"] = "password_required"
                                    data["scan_seen"] = True
                                    data["authorized"] = True
                                    self._extend_qr_expires(data)
                                    return data.get("authorized_user")
                                except Exception:
                                    pass
                            elif isinstance(export_result, raw.types.auth.LoginToken):
                                token_expires = getattr(export_result, "expires", None)
                                if token_expires:
                                    data["expires_ts"] = (
                                        self._normalize_login_token_expires(token_expires)
                                    )
                                    data["expires_at"] = utc_from_timestamp_iso_z(
                                        data["expires_ts"]
                                    )
                                if export_result.token:
                                    data["token"] = export_result.token
                        except Exception:
                            pass

                    return data.get("authorized_user")

                if data.get("status") == "password_required" or data.get("authorized"):
                    try:
                        return await _finalize_password_login(
                            data.get("authorized_user")
                        )
                    except Unauthorized:
                        user = await _ensure_authorized()
                        if not data.get("authorized"):
                            self._extend_qr_expires(data)
                            raise ValueError("请先在手机端确认登录")
                        return await _finalize_password_login(user)

                token = data.get("token")
                migrate_dc_id = data.get("migrate_dc_id")
                result = None
                try:
                    for _ in range(2):
                        if migrate_dc_id:
                            session = await get_session(client, migrate_dc_id)
                            self._capture_migrate_auth(data, session)
                            result = await session.invoke(
                                raw.functions.auth.ImportLoginToken(token=token)
                            )
                        else:
                            result = await client.invoke(
                                raw.functions.auth.ImportLoginToken(token=token)
                            )

                        if isinstance(result, raw.types.auth.LoginTokenMigrateTo):
                            migrate_dc_id = result.dc_id
                            token = result.token
                            data["migrate_dc_id"] = migrate_dc_id
                            data["token"] = token
                            continue
                        break
                except SessionPasswordNeeded:
                    data["status"] = "password_required"
                    data["scan_seen"] = True
                    data["authorized"] = True
                    self._extend_qr_expires(data)
                    return await _finalize_password_login()

                if isinstance(result, raw.types.auth.LoginToken):
                    token_expires = getattr(result, "expires", None)
                    if token_expires:
                        data["expires_ts"] = self._normalize_login_token_expires(
                            token_expires
                        )
                        data["expires_at"] = utc_from_timestamp_iso_z(
                            data["expires_ts"]
                        )
                    if data.get("token") != result.token:
                        data["token"] = result.token
                    raise ValueError("请先在手机端确认登录")

                if isinstance(result, raw.types.auth.LoginTokenSuccess):
                    user = types.User._parse(client, result.authorization.user)
                    await client.storage.user_id(user.id)
                    await client.storage.is_bot(False)
                    data["authorized"] = True
                    data["authorized_user"] = user

                    try:
                        try:
                            me = await client.get_me()
                        except Exception:
                            me = user

                        try:
                            password_state = await client.get_password()
                        except Exception:
                            password_state = None

                        if password_state and getattr(password_state, "has_password", False):
                            return await _finalize_password_login(user)

                        await self._apply_migrate_auth(client, data)
                        await self._persist_client_session(
                            client, data.get("account_name"), data.get("proxy")
                        )
                    except SessionPasswordNeeded:
                        data["status"] = "password_required"
                        data["scan_seen"] = True
                        return await _finalize_password_login(user)

                    try:
                        await client.disconnect()
                    except Exception:
                        pass

                    account_name = data.get("account_name")
                    await self._cleanup_qr_login(login_id, preserve_session=True)

                    account = None
                    try:
                        accounts = self.list_accounts(force_refresh=True)
                        account = next(
                            (acc for acc in accounts if acc.get("name") == account_name),
                            None,
                        )
                    except Exception:
                        account = None

                    return {
                        "status": "success",
                        "message": "登录成功",
                        "account": account,
                        "user_id": getattr(me, "id", None),
                        "first_name": getattr(me, "first_name", None),
                        "username": getattr(me, "username", None),
                    }

                raise ValueError("请先在手机端确认登录")

        except FloodWait as e:
            await self._cleanup_qr_login(login_id)
            raise ValueError(f"请求过于频繁，请等待 {e.value} 秒后重试")
        except Unauthorized:
            if data and data.get("status") in {"password_required", "scanned_wait_confirm"}:
                self._extend_qr_expires(data)
                raise ValueError("请先在手机端确认登录")
            await self._cleanup_qr_login(login_id)
            raise ValueError("登录失败，请重试")
        except ValueError:
            raise
        except Exception:
            if data and data.get("status") in {"password_required", "scanned_wait_confirm"}:
                self._extend_qr_expires(data)
                raise ValueError("登录失败，请重试")
            await self._cleanup_qr_login(login_id)
            raise ValueError("登录失败，请重试")


    async def cancel_qr_login(self, login_id: str) -> bool:
        data = _qr_login_sessions.get(login_id)
        if not data:
            return False
        self._log_qr_state(login_id, "cancelled", data)
        await self._cleanup_qr_login(login_id)
        return True

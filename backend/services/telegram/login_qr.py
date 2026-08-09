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

logger = logging.getLogger("backend.telegram.login_qr")

# _export_login_token 兜底返回的特殊标记：轮询已确认进入 2FA 状态（会话状态已置位）
_PASSWORD_REQUIRED = object()


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
        logger.info("QR 登录状态 state=%s login_id=%s", state, login_id)


    async def _apply_migrate_auth(self, client, data: Dict[str, Any]) -> None:
        migrate_dc_id = data.get("migrate_dc_id")
        migrate_auth_key = data.get("migrate_auth_key")
        if migrate_dc_id and migrate_auth_key:
            try:
                await client.storage.dc_id(migrate_dc_id)
                await client.storage.auth_key(migrate_auth_key)
            except Exception as exc:
                logger.warning("应用 QR 迁移 auth 失败 (dc_id=%s): %s", migrate_dc_id, exc)


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
        except Exception as exc:
            logger.warning("捕获 QR 迁移 auth 失败: %s", exc)


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
            except Exception as exc:
                logger.warning("QR 登录清理 remove_handler 失败 (login_id=%s): %s", login_id, exc)
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


    def _resolve_api_credentials(
        self, data: Optional[Dict[str, Any]] = None, *, strict: bool = False
    ) -> tuple:
        """解析 api_id/api_hash：会话缓存优先，配置/环境变量兜底。

        - data 非空时优先复用其中缓存的 api_id/api_hash，并回写解析结果
        - strict=True（start_qr_login）解析失败原样抛出；
          strict=False 返回 (None, None) 由调用方决定降级
        """
        if data is not None:
            api_id = data.get("api_id")
            api_hash = data.get("api_hash")
            if api_id and api_hash:
                return api_id, api_hash

        from backend.services.config import get_config_service
        from backend.services.telegram.credentials import (
            resolve_telegram_api_credentials,
        )

        try:
            api_id, api_hash = resolve_telegram_api_credentials(
                get_config_service().get_telegram_config(),
                env_api_id=os.getenv("TG_API_ID"),
                env_api_hash=os.getenv("TG_API_HASH"),
            )
        except Exception:
            if strict:
                raise
            return None, None
        if data is not None:
            data["api_id"] = api_id
            data["api_hash"] = api_hash
        return api_id, api_hash


    async def _import_login_token(
        self, client, data: Dict[str, Any], token, migrate_dc_id
    ) -> tuple:
        """ImportLoginToken 轮询（含 dc 迁移循环，最多 2 轮）。

        返回 (result, error)：
        - result：最近一次成功调用的结果（迁移轮次的部分结果会保留）
        - error：循环内吞掉的通用异常（SessionPasswordNeeded 直接抛出由调用方处理）
        """
        from pyrogram import raw
        from pyrogram.errors import SessionPasswordNeeded
        from pyrogram.methods.messages.inline_session import get_session

        result = None
        error = None
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
            raise
        except Exception as exc:
            error = exc
        return result, error


    def _apply_login_token_update(self, data: Dict[str, Any], result: Any) -> None:
        """将 LoginToken 轮询结果（token/过期时间）回写会话数据。"""
        token_expires = getattr(result, "expires", None)
        if token_expires:
            data["expires_ts"] = self._normalize_login_token_expires(token_expires)
            data["expires_at"] = utc_from_timestamp_iso_z(
                data["expires_ts"]
            )
        if getattr(result, "token", None):
            data["token"] = result.token


    async def _export_login_token(self, client, data: Dict[str, Any]) -> Any:
        """ExportLoginToken 兜底轮询（含凭据兜底解析与 dc 迁移后再导入）。

        返回约定：
        - LoginTokenSuccess：本轮已获得授权（含迁移后导入成功），调用方执行 finalize
        - LoginToken：已刷新 token/过期时间，调用方按轮询态处理
        - _PASSWORD_REQUIRED：已进入 2FA 状态（status/scan_seen/过期时间已置位）
        - None：无可用结果（凭据缺失或瞬时异常已吞）
        """
        from pyrogram import raw
        from pyrogram.errors import SessionPasswordNeeded
        from pyrogram.methods.messages.inline_session import get_session

        api_id, api_hash = self._resolve_api_credentials(data)
        if not api_id or not api_hash:
            return None

        try:
            export_result = await client.invoke(
                raw.functions.auth.ExportLoginToken(
                    api_id=api_id, api_hash=api_hash, except_ids=[]
                )
            )
        except Exception:
            return None

        if isinstance(export_result, raw.types.auth.LoginTokenSuccess):
            return export_result
        if isinstance(export_result, raw.types.auth.LoginTokenMigrateTo):
            data["migrate_dc_id"] = export_result.dc_id
            data["token"] = export_result.token
            try:
                session = await get_session(client, export_result.dc_id)
                self._capture_migrate_auth(data, session)
                migrate_result = await session.invoke(
                    raw.functions.auth.ImportLoginToken(token=export_result.token)
                )
            except SessionPasswordNeeded:
                self._set_qr_password_required(data, None)
                return _PASSWORD_REQUIRED
            except Exception:
                return None
            if isinstance(migrate_result, raw.types.auth.LoginTokenSuccess):
                return migrate_result
            return None
        if isinstance(export_result, raw.types.auth.LoginToken):
            self._apply_login_token_update(data, export_result)
            return export_result
        return None


    def _set_qr_password_required(
        self,
        data: Dict[str, Any],
        login_id: Optional[str] = None,
        *,
        authorized: bool = False,
        extend: bool = True,
    ) -> None:
        """将会话标记为需要 2FA 密码（login_id 提供时同步记录状态日志）。"""
        data["status"] = "password_required"
        data["scan_seen"] = True
        if authorized:
            data["authorized"] = True
        if extend:
            self._extend_qr_expires(data)
        if login_id:
            self._log_qr_state(login_id, "password_required", data)


    @staticmethod
    def _password_required_response(data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "status": "password_required",
            "expires_at": data.get("expires_at"),
            "message": "需要 2FA 密码",
        }


    async def _store_qr_authorized_user(self, client, data: Dict[str, Any], login_result) -> Any:
        """从 LoginTokenSuccess 解析授权用户并写入会话存储。"""
        from pyrogram import types

        user = types.User._parse(client, login_result.authorization.user)
        await client.storage.user_id(user.id)
        await client.storage.is_bot(False)
        data["authorized"] = True
        data["authorized_user"] = user
        return user


    async def _finalize_qr_login_success(
        self, login_id: str, data: Dict[str, Any], user
    ) -> Dict[str, Any]:
        """QR 登录成功收尾：清理会话并返回成功响应（状态日志由调用方记录）。"""
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
            "user_id": getattr(user, "id", None),
            "first_name": getattr(user, "first_name", None),
            "username": getattr(user, "username", None),
        }


    async def _persist_qr_authorized(
        self, client, data: Dict[str, Any], login_id: str, user
    ) -> Any:
        """授权后统一收尾：取 me、检测 2FA、持久化会话。

        返回 _PASSWORD_REQUIRED（会话已进入 2FA 状态）或授权用户 me（登录完成）。
        """
        from pyrogram.errors import SessionPasswordNeeded

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
                return _PASSWORD_REQUIRED
            await self._apply_migrate_auth(client, data)
            await self._persist_client_session(
                client, data.get("account_name"), data.get("proxy")
            )
        except SessionPasswordNeeded:
            data["status"] = "password_required"
            data["scan_seen"] = True
            return _PASSWORD_REQUIRED
        return me


    async def _finalize_qr_login(
        self, client, data: Dict[str, Any], login_id: str, login_result
    ) -> Dict[str, Any]:
        """扫码确认后的授权收尾：写入会话、检查 2FA、持久化会话并返回结果。"""
        user = await self._store_qr_authorized_user(client, data, login_result)
        me = await self._persist_qr_authorized(client, data, login_id, user)
        if me is _PASSWORD_REQUIRED:
            self._set_qr_password_required(data, login_id)
            return self._password_required_response(data)

        self._log_qr_state(login_id, "success", data)
        return await self._finalize_qr_login_success(login_id, data, me)


    async def _finalize_qr_password_login(
        self, client, data: Dict[str, Any], login_id: str, password: str, user_fallback=None
    ) -> Dict[str, Any]:
        """2FA 密码校验后的授权收尾：校验密码、写入会话、持久化会话并返回结果。"""
        from pyrogram import raw, types
        from pyrogram.errors import PasswordHashInvalid
        from pyrogram.methods.messages.inline_session import get_session
        from pyrogram.utils import compute_password_check

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

        self._log_qr_state(login_id, "success", data)
        return await self._finalize_qr_login_success(login_id, data, me)


    async def _ensure_qr_authorized(
        self, client, data: Dict[str, Any], login_id: str
    ) -> Any:
        """确保会话已授权：ImportLoginToken/ExportLoginToken 轮询后返回授权用户或 None。"""
        from pyrogram import raw
        from pyrogram.errors import SessionPasswordNeeded

        if data.get("authorized"):
            return data.get("authorized_user")

        result = None
        if data.get("token"):
            try:
                result, error = await self._import_login_token(
                    client, data, data.get("token"), data.get("migrate_dc_id")
                )
            except SessionPasswordNeeded:
                self._set_qr_password_required(data, None, authorized=True)
                return data.get("authorized_user")
            if error is not None:
                result = None

        if isinstance(result, raw.types.auth.LoginTokenSuccess):
            return await self._store_qr_authorized_user(client, data, result)
        if isinstance(result, raw.types.auth.LoginToken):
            self._apply_login_token_update(data, result)

        try:
            outcome = await self._export_login_token(client, data)
        except Exception:
            outcome = None
        if outcome is _PASSWORD_REQUIRED:
            data["authorized"] = True
            return data.get("authorized_user")
        if isinstance(outcome, raw.types.auth.LoginTokenSuccess):
            try:
                return await self._store_qr_authorized_user(client, data, outcome)
            except Exception:
                pass
        return data.get("authorized_user")


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
        try:
            api_id, api_hash = self._resolve_api_credentials(strict=True)
        except ValueError:
            _release_account_lock()
            raise ValueError("Telegram API ID / API Hash 未配置或无效") from None

        if not proxy:
            global_proxy = config_service.get_global_proxy()
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
                    except Exception as exc:
                        # 初始化失败不致命：后续 stop 仍会尝试完整关闭
                        logger.debug("QR 登录客户端初始化失败: %s", exc)

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
            except Exception as exc:
                # 注册失败会导致扫码更新永远收不到，登录卡死在 waiting_scan；
                # 必须记录错误并标记状态，避免静默失败
                logger.error("QR 登录注册扫码监听失败: %s", exc)
                session_data["status"] = "error"
                session_data["error"] = "qr_handler_register_failed"
                self._log_qr_state(login_id, "error", session_data)

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
        from pyrogram import raw
        from pyrogram.errors import FloodWait, SessionPasswordNeeded

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
            return self._password_required_response(data)

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

                # 先 ImportLoginToken 轮询扫码确认；SessionPasswordNeeded 交外层处理
                if data.get("token"):
                    result, _ = await self._import_login_token(
                        client, data, data.get("token"), data.get("migrate_dc_id")
                    )

                if isinstance(result, raw.types.auth.LoginTokenSuccess):
                    return await self._finalize_qr_login(client, data, login_id, result)
                if isinstance(result, raw.types.auth.LoginToken):
                    self._apply_login_token_update(data, result)
                    data["status"] = "scanned_wait_confirm"

                # fallback: 再次调用 ExportLoginToken 获取最终状态（符合官方流程）
                last_export_ts = data.get("last_export_ts", 0)
                if (
                    result is None or isinstance(result, raw.types.auth.LoginToken)
                ) and now - last_export_ts >= 3:
                    data["last_export_ts"] = now
                    try:
                        outcome = await self._export_login_token(client, data)
                        if outcome is _PASSWORD_REQUIRED:
                            self._log_qr_state(login_id, "password_required", data)
                            return self._password_required_response(data)
                        if isinstance(outcome, raw.types.auth.LoginTokenSuccess):
                            return await self._finalize_qr_login(
                                client, data, login_id, outcome
                            )
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
                self._set_qr_password_required(data, login_id, authorized=True)
            return {
                "status": "password_required",
                "expires_at": data.get("expires_at") if data else None,
                "message": "需要 2FA 密码",
            }
        except Exception:
            self._log_qr_state(login_id, "failed", data)
            await self._cleanup_qr_login(login_id)
            return {
                "status": "failed",
                "message": "登录失败，请重试",
            }


    async def submit_qr_password(self, login_id: str, password: str) -> Dict[str, Any]:
        from pyrogram import raw
        from pyrogram.errors import (
            FloodWait,
            SessionPasswordNeeded,
            Unauthorized,
        )

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

        try:
            async with global_semaphore:
                if not client.is_connected:
                    await client.connect()

                # 已进入 2FA 或已授权：直接校验密码完成登录
                if data.get("status") == "password_required" or data.get("authorized"):
                    try:
                        return await self._finalize_qr_password_login(
                            client, data, login_id, password, data.get("authorized_user")
                        )
                    except Unauthorized:
                        user = await self._ensure_qr_authorized(client, data, login_id)
                        if not data.get("authorized"):
                            self._extend_qr_expires(data)
                            raise ValueError("请先在手机端确认登录")
                        return await self._finalize_qr_password_login(
                            client, data, login_id, password, user
                        )

                # 常规路径：先 ImportLoginToken 轮询扫码确认
                result = None
                try:
                    result, error = await self._import_login_token(
                        client, data, data.get("token"), data.get("migrate_dc_id")
                    )
                    if error is not None:
                        raise error
                except SessionPasswordNeeded:
                    self._set_qr_password_required(data, None, authorized=True)
                    return await self._finalize_qr_password_login(
                        client, data, login_id, password
                    )

                if isinstance(result, raw.types.auth.LoginToken):
                    self._apply_login_token_update(data, result)
                    raise ValueError("请先在手机端确认登录")

                if isinstance(result, raw.types.auth.LoginTokenSuccess):
                    user = await self._store_qr_authorized_user(client, data, result)
                    me = await self._persist_qr_authorized(client, data, login_id, user)
                    if me is _PASSWORD_REQUIRED:
                        return await self._finalize_qr_password_login(
                            client, data, login_id, password, user
                        )
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
                    return await self._finalize_qr_login_success(login_id, data, me)

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

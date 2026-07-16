"""TelegramService mixin: accounts."""
from __future__ import annotations

import asyncio
import logging
import secrets
from typing import Any, Dict, List, Optional

from backend.core.config import get_settings
from backend.services.telegram.sessions import (
    _login_sessions,
    _qr_login_sessions,
)
from backend.utils.account_locks import get_account_lock
from backend.utils.names import validate_storage_name
from backend.utils.proxy import build_proxy_dict
from backend.utils.tg_session import (
    delete_account_session_string,
    delete_session_string_file,
    get_account_profile,
    get_account_session_string,
    get_account_status,
    get_session_mode,
    is_string_session_mode,
    list_account_names,
    load_session_string_file,
    rename_account_entry,
    set_account_status,
)
from backend.utils.time import utc_now_iso_z

settings = get_settings()


logger = logging.getLogger("backend.qr_login")

class TelegramAccountsMixin:

    @staticmethod
    def _normalize_account_name(account_name: str) -> str:
        return validate_storage_name(account_name, field_name="account_name")


    @staticmethod
    def _account_status_payload(account_name: str) -> Dict[str, Any]:
        status = get_account_status(account_name)
        return {
            "status": status.get("status") or "connected",
            "status_message": status.get("message") or "",
            "status_code": status.get("code"),
            "status_checked_at": status.get("checked_at"),
            "needs_relogin": bool(status.get("needs_relogin", False)),
        }


    @staticmethod
    def _move_path(source, target) -> None:
        if not source.exists():
            return

        source_resolved = str(source.resolve()).lower()
        target_resolved = str(target.resolve()).lower()
        if source_resolved == target_resolved:
            if str(source) == str(target):
                return
            temp_target = source.with_name(
                f"{source.name}.__rename_tmp__{secrets.token_hex(6)}"
            )
            source.replace(temp_target)
            temp_target.replace(target)
            return

        if target.exists():
            raise ValueError(f"目标路径已存在: {target}")

        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)


    @staticmethod
    def _rename_pending_login_records(old_account_name: str, new_account_name: str) -> None:
        for store in (_login_sessions, _qr_login_sessions):
            replacements = []
            for key, value in list(store.items()):
                if not isinstance(value, dict):
                    continue
                if str(value.get("account_name") or "").strip() != old_account_name:
                    continue
                next_key = (
                    key.replace(f"{old_account_name}_", f"{new_account_name}_", 1)
                    if isinstance(key, str) and key.startswith(f"{old_account_name}_")
                    else key
                )
                replacements.append((key, next_key, {**value, "account_name": new_account_name}))

            for old_key, next_key, next_value in replacements:
                store.pop(old_key, None)
                store[next_key] = next_value


    def list_accounts(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        获取所有账号列表（基于 session 文件）

        Returns:
            账号列表，每个账号包含：
            - name: 账号名称
            - session_file: session 文件路径
            - exists: session 文件是否存在
            - size: 文件大小（字节）
        """
        if self._accounts_cache is not None and not force_refresh:
            return [
                {**acc, **self._account_status_payload(acc.get("name", ""))}
                for acc in self._accounts_cache
            ]

        accounts = []

        pending_accounts = set()
        for data in _login_sessions.values():
            name = data.get("account_name")
            if name:
                pending_accounts.add(name)
        for data in _qr_login_sessions.values():
            name = data.get("account_name")
            status = data.get("status")
            if name and status != "success":
                pending_accounts.add(name)

        # 扫描 session 目录
        try:
            if is_string_session_mode():
                seen = set()
                for session_file in self.session_dir.glob("*.session_string"):
                    account_name = session_file.stem
                    seen.add(account_name)
                    if account_name in pending_accounts:
                        continue
                    profile = get_account_profile(account_name)
                    accounts.append(
                        {
                            "name": account_name,
                            "session_file": str(session_file),
                            "exists": session_file.exists(),
                            "size": session_file.stat().st_size
                            if session_file.exists()
                            else 0,
                            "remark": profile.get("remark"),
                            "proxy": profile.get("proxy"),
                            **self._account_status_payload(account_name),
                        }
                    )

                for account_name in list_account_names():
                    if account_name in seen:
                        continue
                    if account_name in pending_accounts:
                        continue
                    session_file = self.session_dir / f"{account_name}.session_string"
                    profile = get_account_profile(account_name)
                    accounts.append(
                        {
                            "name": account_name,
                            "session_file": str(session_file),
                            "exists": session_file.exists(),
                            "size": session_file.stat().st_size
                            if session_file.exists()
                            else 0,
                            "remark": profile.get("remark"),
                            "proxy": profile.get("proxy"),
                            **self._account_status_payload(account_name),
                        }
                    )
            else:
                for session_file in self.session_dir.glob("*.session"):
                    account_name = session_file.stem  # 文件名（不含扩展名）
                    profile = get_account_profile(account_name)

                    if account_name in pending_accounts:
                        continue

                    accounts.append(
                        {
                            "name": account_name,
                            "session_file": str(session_file),
                            "exists": session_file.exists(),
                            "size": session_file.stat().st_size
                            if session_file.exists()
                            else 0,
                            "remark": profile.get("remark"),
                            "proxy": profile.get("proxy"),
                            **self._account_status_payload(account_name),
                        }
                    )

            self._accounts_cache = sorted(accounts, key=lambda x: x["name"])
            return self._accounts_cache
        except Exception:
            return []


    def account_exists(self, account_name: str) -> bool:
        """检查账号是否存在"""
        # 优先查缓存
        account_name = self._normalize_account_name(account_name)
        if self._accounts_cache is not None:
            for acc in self._accounts_cache:
                if acc["name"] == account_name:
                    return True
            # 如果缓存里没有，可能是缓存过期，也可是真的没有
            # 保险起见，如果没有找到，还是查一下文件，或者信任缓存？
            # 考虑到 start_login 会更新缓存，应该可以信任。
            # 但为了稳妥，如果缓存没命中，再查文件
            pass

        if is_string_session_mode():
            if get_account_session_string(account_name):
                return True
            if load_session_string_file(self.session_dir, account_name):
                return True
            return False

        session_file = self.session_dir / f"{account_name}.session"
        return session_file.exists()


    async def download_account_avatar(self, account_name: str) -> Optional[bytes]:
        """
        下载账号的 Telegram 头像。

        Returns:
            头像的 JPEG 字节数据，如果没有头像则返回 None
        """
        from tg_signer.core import get_client

        account_name = self._normalize_account_name(account_name)

        if not self.account_exists(account_name):
            return None

        proxy_dict = None
        try:
            profile = get_account_profile(account_name) or {}
            proxy_value = profile.get("proxy")
            if not proxy_value:
                from backend.services.config import get_config_service
                proxy_value = get_config_service().get_global_settings().get("global_proxy")
            if proxy_value:
                proxy_dict = build_proxy_dict(proxy_value)
        except Exception:
            proxy_dict = None

        session_mode = get_session_mode()
        session_string = None
        in_memory = False
        if session_mode == "string":
            session_string = get_account_session_string(
                account_name
            ) or load_session_string_file(self.session_dir, account_name)
            if not session_string:
                return None
            in_memory = True

        try:
            client = get_client(
                account_name,
                proxy=proxy_dict,
                workdir=self.session_dir,
                session_string=session_string,
                in_memory=in_memory,
                no_updates=True,
            )

            lock = get_account_lock(account_name)
            async with lock:
                async with client:
                    me = await asyncio.wait_for(client.get_me(), timeout=10)
                    if not me or not getattr(me, "photo", None):
                        return None

                    # Download the small profile photo
                    photo_bytes = await asyncio.wait_for(
                        client.download_media(me.photo.small_file_id, in_memory=True),
                        timeout=15,
                    )
                    if photo_bytes:
                        photo_bytes.seek(0)
                        return photo_bytes.read()
                    return None
        except Exception as e:
            logger.debug("Failed to download avatar for %s: %s", account_name, e)
            return None


    async def download_chat_avatar(
        self, account_name: str, chat_id: int
    ) -> Optional[bytes]:
        """
        下载 Chat 对象的头像。

        Returns:
            头像的 JPEG 字节数据，如果没有头像则返回 None
        """
        from tg_signer.core import get_client

        account_name = self._normalize_account_name(account_name)

        if not self.account_exists(account_name):
            return None

        proxy_dict = None
        try:
            profile = get_account_profile(account_name) or {}
            proxy_value = profile.get("proxy")
            if not proxy_value:
                from backend.services.config import get_config_service
                proxy_value = get_config_service().get_global_settings().get("global_proxy")
            if proxy_value:
                proxy_dict = build_proxy_dict(proxy_value)
        except Exception:
            proxy_dict = None

        session_mode = get_session_mode()
        session_string = None
        in_memory = False
        if session_mode == "string":
            session_string = get_account_session_string(
                account_name
            ) or load_session_string_file(self.session_dir, account_name)
            if not session_string:
                return None
            in_memory = True

        try:
            client = get_client(
                account_name,
                proxy=proxy_dict,
                workdir=self.session_dir,
                session_string=session_string,
                in_memory=in_memory,
                no_updates=True,
            )

            lock = get_account_lock(account_name)
            async with lock:
                async with client:
                    chat = await asyncio.wait_for(
                        client.get_chat(chat_id), timeout=10
                    )
                    if not chat or not getattr(chat, "photo", None):
                        return None

                    photo_bytes = await asyncio.wait_for(
                        client.download_media(
                            chat.photo.small_file_id, in_memory=True
                        ),
                        timeout=15,
                    )
                    if photo_bytes:
                        photo_bytes.seek(0)
                        return photo_bytes.read()
                    return None
        except Exception as e:
            logger.debug(
                "Failed to download chat avatar for %s/%s: %s",
                account_name,
                chat_id,
                e,
            )
            return None


    def _build_account_client(
        self,
        account_name: str,
        no_updates: bool = True,
    ):
        """
        构建账号客户端（辅助方法，减少代码重复）。

        返回 (client, proxy_dict) 元组。
        """
        from tg_signer.core import get_client

        account_name = self._normalize_account_name(account_name)

        proxy_dict = None
        try:
            profile = get_account_profile(account_name) or {}
            proxy_value = profile.get("proxy")
            if not proxy_value:
                from backend.services.config import get_config_service

                proxy_value = get_config_service().get_global_settings().get(
                    "global_proxy"
                )
            if proxy_value:
                proxy_dict = build_proxy_dict(proxy_value)
        except Exception:
            proxy_dict = None

        session_mode = get_session_mode()
        session_string = None
        in_memory = False
        if session_mode == "string":
            session_string = get_account_session_string(
                account_name
            ) or load_session_string_file(self.session_dir, account_name)
            if not session_string:
                raise ValueError("session_string 不存在或已失效")
            in_memory = True

        client = get_client(
            account_name,
            proxy=proxy_dict,
            workdir=self.session_dir,
            session_string=session_string,
            in_memory=in_memory,
            no_updates=no_updates,
        )

        return client, proxy_dict


    async def check_account_status(
        self,
        account_name: str,
        timeout_seconds: float = 8.0,
        no_updates: bool = True,
    ) -> Dict[str, Any]:
        """
        检测账号 session 是否可用。

        设计目标：
        1. 复用共享 Client，不主动关闭正在运行中的任务连接。
        2. 使用单次 get_me 探活，避免执行重操作。
        3. 将“会话失效”与“临时网络错误”分开，前端可据此决定是否引导重新登录。
        """
        from tg_signer.core import get_client

        account_name = self._normalize_account_name(account_name)
        checked_at = utc_now_iso_z()

        if not self.account_exists(account_name):
            return {
                "account_name": account_name,
                "ok": False,
                "status": "not_found",
                "message": "账号不存在",
                "code": "ACCOUNT_NOT_FOUND",
                "checked_at": checked_at,
                "needs_relogin": True,
            }

        proxy_dict = None
        try:
            profile = get_account_profile(account_name) or {}
            proxy_value = profile.get("proxy")
            if not proxy_value:
                from backend.services.config import get_config_service

                proxy_value = get_config_service().get_global_settings().get(
                    "global_proxy"
                )
            if proxy_value:
                proxy_dict = build_proxy_dict(proxy_value)
        except Exception:
            proxy_dict = None

        session_mode = get_session_mode()
        session_string = None
        in_memory = False
        if session_mode == "string":
            session_string = get_account_session_string(
                account_name
            ) or load_session_string_file(self.session_dir, account_name)
            if not session_string:
                set_account_status(
                    account_name,
                    status="invalid",
                    message="session_string 不存在或已失效",
                    code="ACCOUNT_SESSION_INVALID",
                    needs_relogin=True,
                )
                return {
                    "account_name": account_name,
                    "ok": False,
                    "status": "invalid",
                    "message": "session_string 不存在或已失效",
                    "code": "ACCOUNT_SESSION_INVALID",
                    "checked_at": checked_at,
                    "needs_relogin": True,
                }
            in_memory = True

        timeout_seconds = max(1.0, min(float(timeout_seconds or 8.0), 20.0))

        try:
            client = get_client(
                account_name,
                proxy=proxy_dict,
                workdir=self.session_dir,
                session_string=session_string,
                in_memory=in_memory,
                no_updates=no_updates,
            )
        except Exception as e:
            return {
                "account_name": account_name,
                "ok": False,
                "status": "error",
                "message": str(e) or "client init failed",
                "code": "CLIENT_INIT_FAILED",
                "checked_at": checked_at,
                "needs_relogin": False,
            }

        try:
            # Reuse shared clients and avoid context-manager disconnect on each refresh.
            lock = get_account_lock(account_name)
            async with lock:
                if not getattr(client, "is_connected", False):
                    await client.connect()
                me = await asyncio.wait_for(client.get_me(), timeout=timeout_seconds)
            set_account_status(
                account_name,
                status="connected",
                message="",
                code="OK",
                needs_relogin=False,
            )
            return {
                "account_name": account_name,
                "ok": True,
                "status": "connected",
                "message": "",
                "code": "OK",
                "checked_at": checked_at,
                "needs_relogin": False,
                "user_id": getattr(me, "id", None),
            }
        except asyncio.TimeoutError:
            return {
                "account_name": account_name,
                "ok": False,
                "status": "checking",
                "message": "Request timed out",
                "code": "TIMEOUT",
                "checked_at": checked_at,
                "needs_relogin": False,
            }
        except ConnectionError as e:
            return {
                "account_name": account_name,
                "ok": False,
                "status": "checking",
                "message": str(e),
                "code": "CONNECTION_ERROR",
                "checked_at": checked_at,
                "needs_relogin": False,
            }
        except Exception as e:
            err_text = str(e) or type(e).__name__
            err_upper = err_text.upper()
            err_lower = err_text.lower()
            if (
                "READONLY DATABASE" in err_upper
                or "PERMISSION DENIED" in err_upper
                or "ATTEMPT TO WRITE A READONLY DATABASE" in err_upper
            ):
                return {
                    "account_name": account_name,
                    "ok": False,
                    "status": "checking",
                    "message": err_text,
                    "code": "STORAGE_PERMISSION_DENIED",
                    "checked_at": checked_at,
                    "needs_relogin": False,
                }
            if "SESSION" in err_upper and "INVALID" in err_upper:
                set_account_status(
                    account_name,
                    status="invalid",
                    message=err_text,
                    code="ACCOUNT_SESSION_INVALID",
                    needs_relogin=True,
                )
                return {
                    "account_name": account_name,
                    "ok": False,
                    "status": "invalid",
                    "message": err_text,
                    "code": "ACCOUNT_SESSION_INVALID",
                    "checked_at": checked_at,
                    "needs_relogin": True,
                }
            if "UNAUTHORIZED" in err_upper or "AUTH_KEY_UNREGISTERED" in err_upper:
                set_account_status(
                    account_name,
                    status="invalid",
                    message=err_text,
                    code="ACCOUNT_SESSION_INVALID",
                    needs_relogin=True,
                )
                return {
                    "account_name": account_name,
                    "ok": False,
                    "status": "invalid",
                    "message": err_text,
                    "code": "ACCOUNT_SESSION_INVALID",
                    "checked_at": checked_at,
                    "needs_relogin": True,
                }
            if "FLOOD_WAIT" in err_upper or "TRANSPORT FLOOD" in err_lower:
                return {
                    "account_name": account_name,
                    "ok": False,
                    "status": "checking",
                    "message": err_text,
                    "code": "FLOOD_WAIT",
                    "checked_at": checked_at,
                    "needs_relogin": False,
                }
            if (
                "TIMEOUT" in err_upper
                or "TIMED OUT" in err_upper
                or "REQUEST TIMED OUT" in err_upper
                or "REQUEST TIME OUT" in err_upper
            ):
                return {
                    "account_name": account_name,
                    "ok": False,
                    "status": "checking",
                    "message": err_text,
                    "code": "TIMEOUT",
                    "checked_at": checked_at,
                    "needs_relogin": False,
                }
            if (
                "CONNECTION" in err_upper
                or "NETWORK" in err_upper
                or "CONNECTION RESET" in err_upper
                or "BROKEN PIPE" in err_upper
            ):
                return {
                    "account_name": account_name,
                    "ok": False,
                    "status": "checking",
                    "message": err_text,
                    "code": "CONNECTION_ERROR",
                    "checked_at": checked_at,
                    "needs_relogin": False,
                }
            return {
                "account_name": account_name,
                "ok": False,
                "status": "error",
                "message": err_text,
                "code": type(e).__name__.upper(),
                "checked_at": checked_at,
                "needs_relogin": False,
            }


    async def delete_account(self, account_name: str) -> bool:
        """
        删除账号（删除 session 文件）

        Args:
            account_name: 账号名称

        Returns:
            是否成功删除
        """
        # 确保释放资源
        account_name = self._normalize_account_name(account_name)
        from tg_signer.core import close_client_by_name

        # 尝试关闭 active client
        try:
            await close_client_by_name(account_name, workdir=self.session_dir)
        except Exception as e:
            logger.debug(f"关闭 Account Client 失败: {e}")

        session_file = self.session_dir / f"{account_name}.session"
        journal_file = self.session_dir / f"{account_name}.session-journal"
        shm_file = self.session_dir / f"{account_name}.session-shm"
        wal_file = self.session_dir / f"{account_name}.session-wal"
        session_string_file = self.session_dir / f"{account_name}.session_string"

        has_session_file = (
            session_file.exists()
            or journal_file.exists()
            or shm_file.exists()
            or wal_file.exists()
        )
        has_session_string = bool(
            get_account_session_string(account_name)
            or load_session_string_file(self.session_dir, account_name)
        )
        has_session_string_file = session_string_file.exists()
        account_in_store = account_name in list_account_names()

        if not (
            has_session_file
            or has_session_string
            or has_session_string_file
            or account_in_store
        ):
            return False

        try:
            if session_file.exists():
                session_file.unlink()

            # 同时删除可能存在的 .session-journal 文件
            if journal_file.exists():
                journal_file.unlink()

            # 删除 shm 和 wal 文件 (sqlite3)
            if shm_file.exists():
                shm_file.unlink()

            if wal_file.exists():
                wal_file.unlink()

            if session_string_file.exists():
                session_string_file.unlink()

            if has_session_string or account_in_store:
                delete_account_session_string(account_name)

            # 确保 .session_string 残留被清理
            delete_session_string_file(self.session_dir, account_name)

            # 更新缓存
            if self._accounts_cache is not None:
                self._accounts_cache = [
                    acc for acc in self._accounts_cache if acc["name"] != account_name
                ]

            return True
        except OSError:
            return False


    async def rename_account(
        self,
        account_name: str,
        new_account_name: str,
    ) -> str:
        account_name = self._normalize_account_name(account_name)
        new_account_name = self._normalize_account_name(new_account_name)
        if account_name == new_account_name:
            return account_name

        accounts = self.list_accounts(force_refresh=True)
        existing_by_lower = {
            str(item.get("name") or "").strip().lower(): str(item.get("name") or "").strip()
            for item in accounts
            if str(item.get("name") or "").strip()
        }

        actual_account_name = existing_by_lower.get(account_name.lower())
        if not actual_account_name:
            raise ValueError(f"账号 {account_name} 不存在")

        conflict_name = existing_by_lower.get(new_account_name.lower())
        if conflict_name and conflict_name.lower() != actual_account_name.lower():
            raise ValueError(f"账号 {new_account_name} 已存在")

        ordered_names = sorted(
            {actual_account_name, new_account_name},
            key=lambda value: value.lower(),
        )
        first_lock = get_account_lock(ordered_names[0])
        second_lock = get_account_lock(ordered_names[-1])

        from tg_signer.core import close_client_by_name

        async def _perform_rename() -> None:
            await close_client_by_name(
                actual_account_name,
                workdir=self.session_dir,
            )
            if new_account_name.lower() != actual_account_name.lower():
                await close_client_by_name(
                    new_account_name,
                    workdir=self.session_dir,
                )

            session_paths = [
                (
                    self.session_dir / f"{actual_account_name}.session",
                    self.session_dir / f"{new_account_name}.session",
                ),
                (
                    self.session_dir / f"{actual_account_name}.session-journal",
                    self.session_dir / f"{new_account_name}.session-journal",
                ),
                (
                    self.session_dir / f"{actual_account_name}.session-shm",
                    self.session_dir / f"{new_account_name}.session-shm",
                ),
                (
                    self.session_dir / f"{actual_account_name}.session-wal",
                    self.session_dir / f"{new_account_name}.session-wal",
                ),
                (
                    self.session_dir / f"{actual_account_name}.session_string",
                    self.session_dir / f"{new_account_name}.session_string",
                ),
            ]

            for source, target in session_paths:
                self._move_path(source, target)

            rename_account_entry(actual_account_name, new_account_name)
            self._rename_pending_login_records(actual_account_name, new_account_name)

            from backend.services.sign_tasks import get_sign_task_service

            get_sign_task_service().rename_account_references(
                actual_account_name,
                new_account_name,
            )

            self._accounts_cache = None

        async with first_lock:
            if second_lock is first_lock:
                await _perform_rename()
            else:
                async with second_lock:
                    await _perform_rename()

        return new_account_name

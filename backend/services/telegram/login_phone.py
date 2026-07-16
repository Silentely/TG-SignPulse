"""TelegramService mixin: login_phone."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional

from backend.core.config import get_settings
from backend.services.telegram.sessions import (
    _cleanup_expired_login_sessions,
    _login_sessions,
)
from backend.utils.account_locks import get_account_lock
from backend.utils.proxy import build_proxy_dict
from backend.utils.tg_session import (
    get_global_semaphore,
    get_session_mode,
    save_session_string_file,
    set_account_session_string,
    set_account_status,
)

settings = get_settings()


logger = logging.getLogger("backend.qr_login")

class TelegramPhoneLoginMixin:

    @staticmethod
    def _normalize_login_token_expires(expires: Optional[int]) -> int:
        now = int(time.time())
        if not expires:
            return now + 300
        try:
            expires_int = int(expires)
        except (TypeError, ValueError):
            return now + 300
        # 兼容 expires 为相对秒数的情况
        if expires_int < 1_000_000_000:
            expires_ts = now + max(0, expires_int)
        else:
            expires_ts = expires_int
        if expires_ts <= now + 5:
            return now + 300
        return expires_ts


    async def start_login(
        self, account_name: str, phone_number: str, proxy: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        开始登录流程（发送验证码）

        这个方法会：
        1. 创建 Pyrogram 客户端
        2. 发送验证码到手机
        3. 返回 phone_code_hash 用于后续验证

        Args:
            account_name: 账号名称
            phone_number: 手机号（国际格式，如 +8613800138000）
            proxy: 代理地址（可选）

        Returns:
            包含 phone_code_hash 的字典
        """

        account_name = self._normalize_account_name(account_name)

        from pyrogram import Client
        from pyrogram.errors import FloodWait, PhoneNumberInvalid

        from tg_signer.core import close_client_by_name

        await _cleanup_expired_login_sessions()

        account_lock = get_account_lock(account_name)
        session_mode = get_session_mode()
        global_semaphore = get_global_semaphore()

        # 1. 清理全局 _login_sessions 中可能存在的残留连接
        # _login_sessions key 格式: f"{account_name}_{phone_number}"
        keys_to_remove = []
        for key, value in _login_sessions.items():
            if key.startswith(f"{account_name}_"):
                old_client = value.get("client")
                old_lock = value.get("lock")
                if old_lock and old_lock.locked():
                    old_lock.release()
                if old_client:
                    try:
                        await old_client.disconnect()
                    except Exception:
                        pass
                keys_to_remove.append(key)

        for key in keys_to_remove:
            _login_sessions.pop(key, None)

        # 获取账号锁，避免与任务并发写 session
        await account_lock.acquire()

        def _release_account_lock() -> None:
            if account_lock.locked():
                account_lock.release()

        # 2. 确保没有后台任务占用
        try:
            await close_client_by_name(account_name, workdir=self.session_dir)
        except Exception as e:
            logger.debug(f"start_login 清理后台客户端失败: {e}")

        # 获取 API credentials
        from backend.services.config import get_config_service

        config_service = get_config_service()
        tg_config = config_service.get_telegram_config()
        api_id = tg_config.get("api_id")
        api_hash = tg_config.get("api_hash")

        env_api_id = os.getenv("TG_API_ID") or None
        env_api_hash = os.getenv("TG_API_HASH") or None
        if env_api_id:
            api_id = env_api_id
        if env_api_hash:
            api_hash = env_api_hash

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
        # 4. 如果是重新登录，尝试先清理旧的 session 文件 (避免 SQLite 锁或损坏)
        # 注意: 如果 session 有效但用户只是想重登，删除也没问题，因为反正要重新验证
        if session_mode == "file":
            session_file = self.session_dir / f"{account_name}.session"
            if session_file.exists():
                try:
                    # 尝试删除主文件
                    session_file.unlink()
                    # 顺便删掉 journal/wal/shm
                    for ext in [".session-journal", ".session-wal", ".session-shm"]:
                        aux_file = self.session_dir / f"{account_name}{ext}"
                        if aux_file.exists():
                            aux_file.unlink()
                except OSError as e:
                    # 如果删除失败，说明真的被锁得很死，或者权限问题
                    logger.debug(f"删除旧 Session 文件失败: {e} - 可能文件仍被占用")
                    # 这里不抛出异常，尝试继续，也许 Pyrogram 能处理?
                    # 但通常 "unable to open database file" 就是因为这个。
                    pass

        session_path = str(self.session_dir / account_name)
        client_kwargs = {
            "name": session_path,
            "api_id": api_id,
            "api_hash": api_hash,
            "proxy": proxy_dict,
            "in_memory": session_mode == "string",
            # 手机号验证码登录不依赖 updates，关闭可减少 flood/timeout 噪音
            "no_updates": True,
        }
        client = Client(**client_kwargs)

        try:
            async with global_semaphore:
                await client.connect()

                self._accounts_cache = None

                if hasattr(client, "storage") and getattr(client.storage, "conn", None):
                    try:
                        client.storage.conn.execute("PRAGMA journal_mode=WAL")
                        client.storage.conn.execute("PRAGMA busy_timeout=30000")
                    except Exception:
                        pass

                sent_code = await client.send_code(phone_number)

            session_key = f"{account_name}_{phone_number}"
            _login_sessions[session_key] = {
                "client": client,
                "phone_code_hash": sent_code.phone_code_hash,
                "phone_number": phone_number,
                "lock": account_lock,
                "account_name": account_name,
                "_created_at": time.monotonic(),
            }

            # 保持连接，避免 session 变化导致验证码失效 (PhoneCodeExpired)
            # 断开连接会导致服务端重新分配 Session ID，从而使之前的 hash 失效
            # try:
            #     await client.disconnect()
            # except Exception:
            #     pass

            return {
                "phone_code_hash": sent_code.phone_code_hash,
                "phone_number": phone_number,
                "account_name": account_name,
            }

        except PhoneNumberInvalid:
            try:
                await client.disconnect()
            except Exception:
                pass
            _release_account_lock()
            raise ValueError("手机号格式无效，请使用国际格式（如 +8613800138000）")
        except FloodWait as e:
            try:
                await client.disconnect()
            except Exception:
                pass
            _release_account_lock()
            raise ValueError(f"请求过于频繁，请等待 {e.value} 秒后重试")
        except Exception as e:
            import traceback

            traceback.print_exc()
            try:
                await client.disconnect()
            except Exception:
                pass
            _release_account_lock()

            error_details = str(e)
            if (
                "database is locked" in error_details
                or "unable to open database file" in error_details
            ):
                raise ValueError(
                    f"会话文件被占用，请稍后重试或重启程序。错误: {error_details}"
                )

            raise ValueError(f"发送验证码失败: {error_details}")


    async def verify_login(
        self,
        account_name: str,
        phone_number: str,
        phone_code: str,
        phone_code_hash: str,
        password: Optional[str] = None,
        proxy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        验证登录（输入验证码和可选的2FA密码）

        Args:
            account_name: 账号名称
            phone_number: 手机号
            phone_code: 验证码
            phone_code_hash: 从 start_login 返回的 hash
            password: 2FA 密码（可选）
            proxy: 代理地址（可选）

        Returns:
            登录结果
        """
        account_name = self._normalize_account_name(account_name)

        from pyrogram.errors import (
            PasswordHashInvalid,
            PhoneCodeExpired,
            PhoneCodeInvalid,
            SessionPasswordNeeded,
        )

        # 尝试从全局字典获取之前的 client
        session_key = f"{account_name}_{phone_number}"
        session_data = _login_sessions.get(session_key)

        if not session_data:
            raise ValueError("登录会话已过期，请重新发送验证码")

        client = session_data["client"]
        session_mode = get_session_mode()
        global_semaphore = get_global_semaphore()

        account_lock = session_data.get("lock")

        def _release_account_lock() -> None:
            if account_lock and account_lock.locked():
                account_lock.release()

        async def _persist_session_string() -> None:
            if session_mode != "string":
                return
            session_string = await client.export_session_string()
            if not session_string:
                raise ValueError("导出 session_string 失败")
            set_account_session_string(account_name, session_string)
            save_session_string_file(self.session_dir, account_name, session_string)
            set_account_status(
                account_name,
                status="connected",
                message="",
                code="OK",
                needs_relogin=False,
            )
            self._accounts_cache = None

        def _persist_proxy_setting() -> None:
            nonlocal proxy
            if not proxy:
                from backend.services.config import get_config_service
                global_proxy = get_config_service().get_global_settings().get("global_proxy")
                if global_proxy:
                    proxy = global_proxy
            if proxy:
                from backend.utils.tg_session import set_account_profile

                set_account_profile(account_name, proxy=proxy)

        if account_lock and not account_lock.locked():
            await account_lock.acquire()

        try:
            async with global_semaphore:
                # 重新连接 (因为 start_login 中断开了)
                if not client.is_connected:
                    await client.connect()

                # 移除验证码中的空格和横线
                phone_code = phone_code.strip().replace(" ", "").replace("-", "")

                # 尝试使用验证码登录
                try:
                    await client.sign_in(phone_number, phone_code_hash, phone_code)

                    # 登录成功，获取用户信息
                    me = await client.get_me()
                    await _persist_session_string()
                    _persist_proxy_setting()
                    set_account_status(
                        account_name,
                        status="connected",
                        message="",
                        code="OK",
                        needs_relogin=False,
                    )

                    # 断开连接并清理
                    await client.disconnect()
                    _login_sessions.pop(session_key, None)
                    _release_account_lock()

                    return {
                        "success": True,
                        "user_id": me.id,
                        "first_name": me.first_name,
                        "username": me.username,
                    }

                except SessionPasswordNeeded:
                    # 需要 2FA 密码
                    if not password:
                        # 不断开连接，等待用户输入 2FA 密码
                        raise ValueError("此账号启用了两步验证，请输入 2FA 密码")

                    # 使用 2FA 密码登录
                    try:
                        await client.check_password(password)
                        me = await client.get_me()
                        await _persist_session_string()
                        _persist_proxy_setting()
                        set_account_status(
                            account_name,
                            status="connected",
                            message="",
                            code="OK",
                            needs_relogin=False,
                        )

                        # 断开连接并清理
                        await client.disconnect()
                        _login_sessions.pop(session_key, None)
                        _release_account_lock()

                        return {
                            "success": True,
                            "user_id": me.id,
                            "first_name": me.first_name,
                            "username": me.username,
                        }
                    except PasswordHashInvalid:
                        raise ValueError("2FA 密码错误")

        except PhoneCodeInvalid:
            # 清理 session
            try:
                await client.disconnect()
            except Exception:
                pass
            _login_sessions.pop(session_key, None)
            _release_account_lock()
            raise ValueError("验证码错误，请检查验证码是否正确")
        except PhoneCodeExpired:
            # 清理 session
            try:
                await client.disconnect()
            except Exception:
                pass
            _login_sessions.pop(session_key, None)
            _release_account_lock()
            raise ValueError("验证码已过期，请重新获取")
        except ValueError as e:
            # 如果是 2FA 错误，不清理 session
            if "两步验证" not in str(e):
                try:
                    await client.disconnect()
                except Exception:
                    pass
                _login_sessions.pop(session_key, None)
                _release_account_lock()
            raise e
        except Exception as e:
            # 清理 session
            try:
                await client.disconnect()
            except Exception:
                pass
            _login_sessions.pop(session_key, None)
            _release_account_lock()

            # 更详细的错误信息
            error_msg = str(e)
            if "PHONE_CODE_INVALID" in error_msg:
                raise ValueError("验证码错误，请检查验证码是否正确")
            elif "PHONE_CODE_EXPIRED" in error_msg:
                raise ValueError("验证码已过期，请重新获取")
            elif "SESSION_PASSWORD_NEEDED" in error_msg:
                raise ValueError("此账号启用了两步验证，请输入 2FA 密码")
            else:
                raise ValueError(f"登录失败: {error_msg}")


    async def _persist_client_session(
        self, client, account_name: str, proxy: Optional[str] = None
    ) -> None:
        session_mode = get_session_mode()
        if session_mode == "string":
            session_string = await client.export_session_string()
            if not session_string:
                raise ValueError("导出 session_string 失败")
            set_account_session_string(account_name, session_string)
            save_session_string_file(self.session_dir, account_name, session_string)
            set_account_status(
                account_name,
                status="connected",
                message="",
                code="OK",
                needs_relogin=False,
            )
        else:
            # 即使在 file 模式，也尝试保存 session_string 作为降级方案
            try:
                session_string = await client.export_session_string()
            except Exception:
                session_string = None
            if session_string:
                try:
                    set_account_session_string(account_name, session_string)
                    save_session_string_file(self.session_dir, account_name, session_string)
                    set_account_status(
                        account_name,
                        status="connected",
                        message="",
                        code="OK",
                        needs_relogin=False,
                    )
                except Exception:
                    pass
        if not proxy:
            from backend.services.config import get_config_service
            global_proxy = get_config_service().get_global_settings().get("global_proxy")
            if global_proxy:
                proxy = global_proxy
        if proxy:
            from backend.utils.tg_session import set_account_profile

            set_account_profile(account_name, proxy=proxy)
        set_account_status(
            account_name,
            status="connected",
            message="",
            code="OK",
            needs_relogin=False,
        )
        self._accounts_cache = None


    def login_sync(
        self,
        account_name: str,
        phone_number: str,
        phone_code: Optional[str] = None,
        phone_code_hash: Optional[str] = None,
        password: Optional[str] = None,
        proxy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        同步版本的登录方法（用于 FastAPI）

        如果只提供 phone_number，则发送验证码
        如果提供了 phone_code，则验证登录
        """

        try:
            if phone_code is None:
                # 发送验证码
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result = loop.run_until_complete(
                        self.start_login(account_name, phone_number, proxy)
                    )
                finally:
                    loop.close()
            else:
                # 验证登录
                if not phone_code_hash:
                    raise ValueError("缺少 phone_code_hash")

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result = loop.run_until_complete(
                        self.verify_login(
                            account_name,
                            phone_number,
                            phone_code,
                            phone_code_hash,
                            password,
                            proxy,
                        )
                    )
                finally:
                    loop.close()

            return result
        except Exception as e:
            # 重新抛出异常，保留原始错误信息
            raise e



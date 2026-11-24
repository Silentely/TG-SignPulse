"""TelegramService mixin: login_phone."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any, Dict, Optional

from backend.core.config import get_settings
from backend.services.telegram.accounts import mark_account_connected
from backend.services.telegram.sessions import (
    _cleanup_expired_login_sessions,
    _login_sessions,
)
from backend.utils.account_locks import AccountLockLease, get_account_lock
from backend.utils.proxy import build_proxy_dict
from backend.utils.tg_session import (
    get_global_semaphore,
    get_session_mode,
    save_session_string_file,
    set_account_session_string,
)

settings = get_settings()


logger = logging.getLogger("backend.telegram.login_phone")


async def _discard_login_client(
    client,
    session_key: Optional[str],
    release_lock,
    *,
    staging_base=None,
) -> None:
    """登录流程的统一清理：断连（容忍已断开/失败）→ 弹出会话 → 释放账号锁。

    未持久化的登录使用暂存 Session 文件；失败清理时一并删除，绝不触碰
    账号原有的正式 Session。
    """
    session_data = _login_sessions.get(session_key) if session_key else None
    try:
        await client.disconnect()
    except Exception:
        pass
    if session_data and not session_data.get("_persisted"):
        staging_base = session_data.get("staging_base") or staging_base
    if staging_base and not (session_data and session_data.get("_persisted")):
        from backend.utils.tg_session import cleanup_staging_session

        cleanup_staging_session(staging_base)
    if session_key:
        _login_sessions.pop(session_key, None)
    if release_lock:
        release_lock()


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
        self,
        account_name: str,
        phone_number: str,
        proxy: Optional[str] = None,
        api_id: Optional[int | str] = None,
        api_hash: Optional[str] = None,
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
        phone_number = str(phone_number or "").strip().replace(" ", "").replace("-", "")
        if not phone_number:
            raise ValueError("手机号不能为空")

        from pyrogram import Client
        from pyrogram.errors import FloodWait, PhoneNumberInvalid

        from tg_signer.core import close_client_by_name

        await _cleanup_expired_login_sessions()

        account_lock = get_account_lock(account_name)
        # 本次登录流程的锁租约：后续请求接力操作同一把锁，只有本流程获取的锁才允许释放
        lock_lease = AccountLockLease(account_lock)
        session_mode = get_session_mode()
        global_semaphore = get_global_semaphore()

        # 1. 清理全局 _login_sessions 中可能存在的残留连接
        # _login_sessions key 格式: f"{account_name}_{phone_number}"
        keys_to_remove = []
        for key, value in list(_login_sessions.items()):
            if key.startswith(f"{account_name}_"):
                old_client = value.get("client")
                old_lock = value.get("lock")
                # 残留会话已被本请求接管，作废旧租约后强制放锁：
                # 不释放会让账号锁永久滞留，后续登录与签到都拿不到这把锁
                old_lease = value.get("lock_lease")
                if old_lease is not None:
                    old_lease.force_release()
                elif old_lock and old_lock.locked():
                    with contextlib.suppress(RuntimeError):
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
        try:
            await asyncio.wait_for(account_lock.acquire(), timeout=15.0)
        except asyncio.TimeoutError:
            raise ValueError(f"账号 {account_name} 正在被后台任务占用，请稍后再试")
        lock_lease.mark_owned()

        def _release_account_lock() -> None:
            lock_lease.release()

        # 2. 确保没有后台任务占用
        try:
            await close_client_by_name(account_name, workdir=self.session_dir)
        except Exception as e:
            logger.debug("start_login 清理后台客户端失败: %s", e)

        # 获取 API credentials：高级设置中显式填写的成对凭据优先，
        # 留空则沿用该账号已配置凭据或全局解析链。
        from backend.services.config import get_config_service

        config_service = get_config_service()
        tg_config = config_service.get_telegram_config()

        from backend.services.telegram.credentials import (
            parse_credential_pair,
            resolve_telegram_credentials,
        )

        try:
            provided_pair = parse_credential_pair(
                api_id, api_hash, source="account", account_name=account_name
            )
            credentials = resolve_telegram_credentials(
                tg_config,
                account_name=account_name,
                profile=(
                    {"api_id": provided_pair.api_id, "api_hash": provided_pair.api_hash}
                    if provided_pair is not None
                    else None
                ),
            )
        except ValueError as exc:
            _release_account_lock()
            raise ValueError(str(exc)) from None

        api_id_value = credentials.api_id
        api_hash_value = credentials.api_hash

        if not proxy:
            global_proxy = config_service.get_global_proxy()
            if global_proxy:
                proxy = global_proxy

        proxy_dict = build_proxy_dict(proxy) if proxy else None
        if proxy and not proxy_dict:
            _release_account_lock()
            raise ValueError(
                "PROXY_INVALID_BLOCKED: Configured proxy string is invalid"
            )
        if config_service.require_proxy_for_telegram() and not proxy_dict:
            _release_account_lock()
            raise ValueError(
                "PROXY_REQUIRED_BLOCKED: Global policy requires a proxy for Telegram connections"
            )

        if proxy_dict:
            try:
                await self.verify_account_proxy(account_name, proxy_dict)
            except Exception:
                _release_account_lock()
                raise
        # 4. 登录使用暂存 Session：验证成功后才原子替换正式文件，
        #    失败时保留账号原有 Session 不受影响。
        staging_base = None
        if session_mode == "file":
            import uuid

            staging_base = self.session_dir / (
                f".login_{account_name}_{uuid.uuid4().hex[:12]}"
            )
            session_path = str(staging_base)
        else:
            session_path = str(self.session_dir / account_name)

        client_kwargs = {
            "name": session_path,
            "api_id": api_id_value,
            "api_hash": api_hash_value,
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
                "lock_lease": lock_lease,
                "account_name": account_name,
                "api_id": api_id_value,
                "api_hash": api_hash_value,
                "api_credentials_source": credentials.source,
                "pending_credentials": (
                    (provided_pair.api_id, provided_pair.api_hash)
                    if provided_pair is not None
                    else None
                ),
                "staging_base": staging_base,
                "_persisted": False,
                "_created_at": time.monotonic(),
            }

            # 保持连接，避免 session 变化导致验证码失效 (PhoneCodeExpired)
            # 断开连接会导致服务端重新分配 Session ID，从而使之前的 hash 失效

            return {
                "phone_code_hash": sent_code.phone_code_hash,
                "phone_number": phone_number,
                "account_name": account_name,
            }

        except PhoneNumberInvalid:
            await _discard_login_client(
                client, None, _release_account_lock, staging_base=staging_base
            )
            raise ValueError("手机号格式无效，请使用国际格式（如 +8613800138000）")
        except FloodWait as e:
            await _discard_login_client(
                client, None, _release_account_lock, staging_base=staging_base
            )
            raise ValueError(f"请求过于频繁，请等待 {e.value} 秒后重试")
        except Exception as e:
            logger.exception("手机号登录发送验证码阶段异常: %s", e)
            await _discard_login_client(
                client, None, _release_account_lock, staging_base=staging_base
            )

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
        api_id: Optional[int | str] = None,
        api_hash: Optional[str] = None,
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
        phone_number = str(phone_number or "").strip().replace(" ", "").replace("-", "")
        phone_code = str(phone_code or "").strip()
        phone_code_hash = str(phone_code_hash or "").strip()

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

        # 认证事务一致性：verify 阶段必须复用 start 阶段解析出的凭据。
        # 若调用方重复提交了高级设置凭据，只允许与事务上下文完全一致。
        from backend.services.telegram.credentials import parse_credential_pair

        if api_id is not None or api_hash is not None:
            provided_pair = parse_credential_pair(
                api_id, api_hash, source="account", account_name=account_name
            )
            if provided_pair is not None and (
                int(provided_pair.api_id) != int(session_data.get("api_id") or 0)
                or str(provided_pair.api_hash)
                != str(session_data.get("api_hash") or "")
            ):
                raise ValueError(
                    "API_CREDENTIALS_CHANGED: 登录凭据在验证阶段发生变化，请重新发送验证码"
                )

        client = session_data["client"]
        global_semaphore = get_global_semaphore()

        account_lock = session_data.get("lock")
        lock_lease = session_data.get("lock_lease")
        if lock_lease is None and account_lock is not None:
            # 兼容无租约的会话结构：所有权按本次请求的实际获取结果记录
            lock_lease = AccountLockLease(account_lock)
            session_data["lock_lease"] = lock_lease

        def _release_account_lock() -> None:
            if lock_lease is not None:
                lock_lease.release()
            elif account_lock and account_lock.locked():
                with contextlib.suppress(RuntimeError):
                    account_lock.release()

        # 同一登录流程的续接请求：锁由 start_login 持有，按租约所有权决定补锁/跳过，
        # 绝不能释放他人持有的锁
        if lock_lease is not None and account_lock is not None:
            if lock_lease.owned:
                # 租约仍归本流程，但锁可能已被过期清理强制释放，补锁保证临界区完整
                if not account_lock.locked():
                    await account_lock.acquire()
            elif not account_lock.locked():
                # 锁空闲：本次请求自行获取并取得所有权
                await account_lock.acquire()
                lock_lease.mark_owned()
            else:
                # 锁被他人持有：会话已被接管，告警后跳过释放
                logger.warning(
                    "登录会话 %s 的账号锁已被其他协程持有，本次请求将以无锁方式继续",
                    session_key,
                )

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
                    # get_me 走超时保护：网络挂起时登录接口不能无限等待
                    me = await asyncio.wait_for(client.get_me(), timeout=10)
                    await self._persist_client_session(
                        client, account_name, proxy, login_session=session_data
                    )

                    # 断开连接并清理（成功路径同样容忍断连抖动，避免已登录被误报失败）
                    await _discard_login_client(
                        client, session_key, _release_account_lock
                    )

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
                        me = await asyncio.wait_for(client.get_me(), timeout=10)
                        await self._persist_client_session(
                            client, account_name, proxy, login_session=session_data
                        )

                        # 断开连接并清理
                        await _discard_login_client(
                            client, session_key, _release_account_lock
                        )

                        return {
                            "success": True,
                            "user_id": me.id,
                            "first_name": me.first_name,
                            "username": me.username,
                        }
                    except PasswordHashInvalid:
                        raise ValueError("2FA 密码错误")

        except PhoneCodeInvalid:
            await _discard_login_client(client, session_key, _release_account_lock)
            raise ValueError("验证码错误，请检查验证码是否正确")
        except PhoneCodeExpired:
            await _discard_login_client(client, session_key, _release_account_lock)
            raise ValueError("验证码已过期，请重新获取")
        except ValueError as e:
            # 如果是 2FA 错误，不清理 session
            if "两步验证" not in str(e):
                await _discard_login_client(client, session_key, _release_account_lock)
            raise e
        except Exception as e:
            await _discard_login_client(client, session_key, _release_account_lock)

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
        self,
        client,
        account_name: str,
        proxy: Optional[str] = None,
        *,
        login_session: Optional[Dict[str, Any]] = None,
        staging_base=None,
    ) -> None:
        """持久化登录结果；保证正式 Session 只在验证成功后原子替换。"""
        session_mode = get_session_mode()
        if login_session is not None:
            staging_base = login_session.get("staging_base")
            pending_credentials = login_session.get("pending_credentials")
        else:
            pending_credentials = None

        session_string = None
        try:
            session_string = await client.export_session_string()
        except Exception as exc:
            if session_mode == "string":
                raise ValueError("导出 session_string 失败") from exc

        if session_mode == "string":
            if not session_string:
                raise ValueError("导出 session_string 失败")
            set_account_session_string(account_name, session_string)
            save_session_string_file(self.session_dir, account_name, session_string)
        else:
            # 即使在 file 模式，也尝试保存 session_string 作为降级方案
            if session_string:
                try:
                    set_account_session_string(account_name, session_string)
                    save_session_string_file(
                        self.session_dir, account_name, session_string
                    )
                except Exception:
                    pass

            if staging_base is not None:
                from backend.utils.tg_session import replace_session_file

                # 先断开连接，确保 SQLite 写入落盘后再原子替换正式文件
                try:
                    if getattr(client, "is_connected", False):
                        await client.disconnect()
                except Exception:
                    pass
                replace_session_file(staging_base, account_name, self.session_dir)

        if pending_credentials:
            from backend.utils.tg_session import set_account_credentials

            # 新会话已用该凭据完成授权，无需再次提示重新登录
            set_account_credentials(
                account_name,
                int(pending_credentials[0]),
                str(pending_credentials[1]),
                mark_needs_relogin=False,
            )

        if login_session is not None:
            login_session["_persisted"] = True

        if not proxy:
            from backend.services.config import get_config_service

            global_proxy = get_config_service().get_global_proxy()
            if global_proxy:
                proxy = global_proxy
        if proxy:
            from backend.utils.tg_session import set_account_profile

            set_account_profile(account_name, proxy=proxy)
        mark_account_connected(account_name)
        self._accounts_cache = None

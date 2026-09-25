"""TelegramService mixin: accounts."""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.core.config import get_settings
from backend.services.sign_task_chats import is_invalid_session_error
from backend.services.telegram.sessions import (
    _login_sessions,
    _qr_login_sessions,
)
from backend.utils.account_locks import (
    AccountLockTimeout,
    acquire_account_lock_with_timeout,
)
from backend.utils.names import validate_storage_name
from backend.utils.proxy import build_proxy_dict
from backend.utils.storage import move_storage_path
from backend.utils.tg_session import (
    delete_account_session_string,
    delete_session_string_file,
    get_account_profile,
    get_account_session_string,
    get_account_status,
    get_session_mode,
    is_string_session_mode,
    list_account_names,
    load_account_session_string,
    load_session_string_file,
    rename_account_entry,
    set_account_status,
)
from backend.utils.time import utc_now_iso_z

# 账号列表缓存 TTL（秒）：profile 变更后最多 N 秒内自动刷新，
# 与登录/删除流程的显式置 None 失效互补
ACCOUNTS_CACHE_TTL_SECONDS = 5.0

settings = get_settings()


logger = logging.getLogger("backend.telegram.accounts")


def _session_file_info(session_file) -> tuple[bool, int]:
    """单次 stat 返回 (exists, size)，避免 exists()+stat() 双重系统调用竞态。"""
    try:
        p = Path(session_file)
        return True, p.stat().st_size
    except (OSError, ValueError, TypeError):
        return False, 0


# 与设备画像池约定的画像字段，注入 Pyrogram Client 时逐项透传
_DEVICE_PROFILE_KEYS = (
    "device_model",
    "system_version",
    "app_version",
    "lang_code",
    "system_lang_code",
)


def _resolve_proxy_and_device_kwargs(
    account_name: str,
) -> tuple[Optional[dict], Dict[str, Any]]:
    """解析账号生效代理与设备画像参数。

    代理字符串非法时抛出 ValueError("PROXY_INVALID_BLOCKED")，而不是静默降级为
    直连——静默降级等价于绕过全局代理策略与出口 IP 校验。
    """
    from backend.services.config import get_config_service

    try:
        profile = get_account_profile(account_name) or {}
    except Exception as e:
        logger.debug("读取账号 profile 失败 %s: %s", account_name, e)
        profile = {}

    proxy_value = profile.get("proxy")
    if not proxy_value:
        proxy_value = get_config_service().get_global_proxy()

    proxy_dict = None
    if proxy_value and str(proxy_value).strip():
        proxy_dict = build_proxy_dict(str(proxy_value).strip())
        if not proxy_dict:
            raise ValueError("PROXY_INVALID_BLOCKED")

    device_kwargs: Dict[str, Any] = {}
    device_profile = profile.get("device_profile")
    if isinstance(device_profile, dict):
        for key in _DEVICE_PROFILE_KEYS:
            if device_profile.get(key):
                device_kwargs[key] = device_profile[key]

    return proxy_dict, device_kwargs


def mark_account_connected(account_name: str) -> None:
    """标记账号登录成功（status=connected），供手机号/扫码登录成功路径统一调用。"""
    set_account_status(
        account_name,
        status="connected",
        message="",
        code="OK",
        needs_relogin=False,
    )


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
        # 实现上提至 backend.utils.storage，与签到任务目录改名共用同一份语义
        move_storage_path(source, target)


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


    @staticmethod
    def _account_entry(
        account_name: str,
        session_file: Path,
        session_exists: bool,
        session_size: int,
        profile: Dict[str, Any],
    ) -> Dict[str, Any]:
        """构造账号列表条目：session 文件、profile 元数据与运行状态合并为单一 dict。"""
        return {
            "name": account_name,
            "session_file": str(session_file),
            "exists": session_exists,
            "size": session_size,
            "remark": profile.get("remark"),
            "proxy": profile.get("proxy"),
            "tags": profile.get("tags") or [],
            "device_family": profile.get("device_family"),
            "device_profile": profile.get("device_profile"),
        }

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
        # 账号列表缓存带短 TTL：防止 profile（备注/代理）变更后缓存永久过期，
        # 又不至于让每次请求都重扫 session 目录
        if self._accounts_cache is not None and not force_refresh:
            if time.monotonic() - getattr(self, "_accounts_cache_ts", 0.0) < ACCOUNTS_CACHE_TTL_SECONDS:
                return [
                    {**acc, **self._account_status_payload(acc.get("name", ""))}
                    for acc in self._accounts_cache
                ]
            # TTL 过期：降级为强制重扫
            self._accounts_cache = None

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
                    if not account_name:
                        continue
                    seen.add(account_name)
                    if account_name in pending_accounts:
                        continue
                    profile = get_account_profile(account_name)
                    # 单次 stat 取两值：避免 exists/stat 双调用的开销与间隙不一致
                    session_exists, session_size = _session_file_info(session_file)
                    accounts.append(
                        {
                            **self._account_entry(
                                account_name,
                                session_file,
                                session_exists,
                                session_size,
                                profile,
                            ),
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
                    session_exists, session_size = _session_file_info(session_file)
                    accounts.append(
                        {
                            **self._account_entry(
                                account_name,
                                session_file,
                                session_exists,
                                session_size,
                                profile,
                            ),
                            **self._account_status_payload(account_name),
                        }
                    )
            else:
                for session_file in self.session_dir.glob("*.session"):
                    account_name = session_file.stem  # 文件名（不含扩展名）
                    if not account_name:
                        continue
                    profile = get_account_profile(account_name)

                    if account_name in pending_accounts:
                        continue

                    session_exists, session_size = _session_file_info(session_file)
                    accounts.append(
                        {
                            **self._account_entry(
                                account_name,
                                session_file,
                                session_exists,
                                session_size,
                                profile,
                            ),
                            **self._account_status_payload(account_name),
                        }
                    )

            self._accounts_cache = sorted(accounts, key=lambda x: x["name"])
            self._accounts_cache_ts = time.monotonic()
            return [
                {**acc, **self._account_status_payload(acc.get("name", ""))}
                for acc in self._accounts_cache
            ]
        except Exception as exc:
            # 扫描失败返回空列表是降级行为，但必须留痕：
            # 否则权限/IO/profile 损坏会表现为账号「凭空消失」且无法排查
            logger.warning("账号列表扫描失败，按空列表返回: %s", exc, exc_info=True)
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
        Raises:
            瞬时错误（网络/会话/限流）向上抛出，由调用方决定是否缓存判定
        """

        account_name = self._normalize_account_name(account_name)

        if not self.account_exists(account_name):
            return None

        try:
            client, proxy_dict = self._build_account_client(
                account_name, no_updates=True
            )
            await self.verify_account_proxy(account_name, proxy_dict)
        except ValueError:
            return None

        try:
            async with acquire_account_lock_with_timeout(account_name, timeout=15.0):
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
            # 瞬时错误（网络/限流/会话失效）不能与"无头像"混为一谈：抛出让路由层区分
            logger.warning(
                "下载账号头像失败 %s: %s", account_name, e, exc_info=True
            )
            raise


    async def download_chat_avatar(
        self, account_name: str, chat_id: int
    ) -> Optional[bytes]:
        """
        下载 Chat 对象的头像。

        Returns:
            头像的 JPEG 字节数据，如果没有头像则返回 None
        Raises:
            瞬时错误（网络/会话/限流）向上抛出，由调用方决定是否缓存判定
        """

        account_name = self._normalize_account_name(account_name)

        if not self.account_exists(account_name):
            return None

        try:
            client, proxy_dict = self._build_account_client(
                account_name, no_updates=True
            )
            await self.verify_account_proxy(account_name, proxy_dict)
        except ValueError:
            return None

        try:
            async with acquire_account_lock_with_timeout(account_name, timeout=15.0):
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
            # 瞬时错误不能与"该 chat 无头像"混为一谈：抛出让路由层区分
            logger.warning(
                "下载 Chat 头像失败 %s/%s: %s",
                account_name,
                chat_id,
                e,
                exc_info=True,
            )
            raise


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

        proxy_dict, device_kwargs = _resolve_proxy_and_device_kwargs(account_name)

        session_mode = get_session_mode()
        session_string = None
        in_memory = False
        if session_mode == "string":
            session_string = load_account_session_string(
                account_name,
                session_dir=self.session_dir,
                session_mode=session_mode,
            )
            if not session_string:
                raise ValueError("session_string 不存在或已失效")
            in_memory = True

        # 全局硬熔断检查：若开启但无任何代理，立即阻断
        from backend.services.config import get_config_service
        cfg_svc = get_config_service()
        global_settings = cfg_svc.get_global_settings() if hasattr(cfg_svc, "get_global_settings") else {}
        if bool(global_settings.get("require_proxy_for_telegram", False)) and not proxy_dict:
            raise RuntimeError("PROXY_REQUIRED_BLOCKED: Global policy requires proxy")

        client = get_client(
            account_name,
            proxy=proxy_dict,
            workdir=self.session_dir,
            session_string=session_string,
            in_memory=in_memory,
            no_updates=no_updates,
            **device_kwargs,
        )

        return client, proxy_dict

    async def verify_account_proxy(
        self,
        account_name: str,
        proxy_dict: Optional[dict] = None,
    ) -> None:
        """
        连接前置门禁（在取账号锁前执行）：
        1. 若全局 require_proxy_for_telegram 为 True 且无代理，抛出 PROXY_REQUIRED_BLOCKED；
        2. 若配置了代理，调用 probe_proxy_exit 探测出口 IP：
           - FAILED -> 抛出 RuntimeError("PROXY_PROBE_FAILED: Proxy leaks host IP")
           - UNAVAILABLE -> 若账号策略为 "warn"，记录警告并放行；若为 "strict"（默认），抛出 RuntimeError("PROXY_PROBE_UNAVAILABLE: Proxy endpoint unreachable")
           - OK -> 放行
        """
        from backend.utils.proxy import (
            ProxyProbeStatus,
            build_proxy_dict,
            probe_proxy_exit,
        )

        account_name = self._normalize_account_name(account_name)
        profile = get_account_profile(account_name) or {}

        if proxy_dict is None:
            proxy_value = profile.get("proxy")
            if not proxy_value:
                from backend.services.config import get_config_service
                proxy_value = get_config_service().get_global_proxy()
            if proxy_value and str(proxy_value).strip():
                proxy_dict = build_proxy_dict(str(proxy_value).strip())
                if not proxy_dict:
                    raise ValueError("PROXY_INVALID_BLOCKED: Configured proxy string is invalid")

        from backend.services.config import get_config_service
        cfg_svc = get_config_service()
        global_settings = cfg_svc.get_global_settings() if hasattr(cfg_svc, "get_global_settings") else {}
        if bool(global_settings.get("require_proxy_for_telegram", False)) and not proxy_dict:
            raise RuntimeError("PROXY_REQUIRED_BLOCKED: Global policy requires proxy")

        if not proxy_dict:
            return

        status, detail = await probe_proxy_exit(proxy_dict)
        if status == ProxyProbeStatus.FAILED:
            logger.error(
                "代理探测硬熔断：账号 %s 代理出口 IP 泄漏宿主机 IP: %s",
                account_name,
                detail,
            )
            raise RuntimeError("PROXY_PROBE_FAILED: Proxy leaks host IP")
        elif status == ProxyProbeStatus.UNAVAILABLE:
            policy = (profile.get("proxy_probe_policy") or "strict").strip().lower()
            if policy == "warn":
                logger.warning(
                    "代理探测不可达（warn 策略放行 MTProto 连接）：账号 %s, 详情: %s",
                    account_name,
                    detail,
                )
            else:
                logger.error(
                    "代理探测失败阻断（strict 策略）：账号 %s, 详情: %s",
                    account_name,
                    detail,
                )
                raise RuntimeError(
                    f"PROXY_PROBE_UNAVAILABLE: Proxy endpoint unreachable ({detail})"
                )



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

        session_mode = get_session_mode()
        session_string = None
        in_memory = False
        if session_mode == "string":
            session_string = load_account_session_string(
                account_name,
                session_dir=self.session_dir,
                session_mode=session_mode,
            )
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

        proxy_dict: Optional[dict] = None
        device_kwargs: Dict[str, Any] = {}
        try:
            proxy_dict, device_kwargs = _resolve_proxy_and_device_kwargs(account_name)
            await self.verify_account_proxy(account_name, proxy_dict)
        except (RuntimeError, ValueError) as e:
            err_msg = str(e)
            code = "PROXY_BLOCKED"
            if "PROXY_INVALID_BLOCKED" in err_msg:
                code = "PROXY_INVALID_BLOCKED"
            elif "PROXY_REQUIRED_BLOCKED" in err_msg:
                code = "PROXY_REQUIRED_BLOCKED"
            elif "PROXY_PROBE_FAILED" in err_msg:
                code = "PROXY_PROBE_FAILED"
            elif "PROXY_PROBE_UNAVAILABLE" in err_msg:
                code = "PROXY_PROBE_UNAVAILABLE"
            set_account_status(
                account_name,
                status="blocked",
                message=err_msg,
                code=code,
                needs_relogin=False,
            )
            return {
                "account_name": account_name,
                "ok": False,
                "status": "blocked",
                "message": err_msg,
                "code": code,
                "checked_at": checked_at,
                "needs_relogin": False,
            }

        timeout_seconds = max(1.0, min(float(timeout_seconds or 8.0), 20.0))

        try:
            client = get_client(
                account_name,
                proxy=proxy_dict,
                workdir=self.session_dir,
                session_string=session_string,
                in_memory=in_memory,
                no_updates=no_updates,
                **device_kwargs,
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
            async with acquire_account_lock_with_timeout(
                account_name, timeout=timeout_seconds
            ):
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
        except AccountLockTimeout as e:
            logger.warning("检查账号状态获取锁超时 %s: %s", account_name, e)
            return {
                "account_name": account_name,
                "ok": False,
                "status": "busy",
                "message": "ACCOUNT_BUSY",
                "code": "ACCOUNT_BUSY",
                "checked_at": checked_at,
                "needs_relogin": False,
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
            # 会话失效判定统一走 is_invalid_session_error，与任务执行路径同集合
            if is_invalid_session_error(e):
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
            logger.debug("关闭 Account Client 失败: %s", e)

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
        # session_string 判定必须与当前会话模式解耦：模式切换后遗留的
        # .session_string 文件与 accounts.json 条目同样需要可被清理
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

        # 删除 sqlite 相关的 session 文件
        for f in (session_file, journal_file, shm_file, wal_file):
            try:
                if f.exists():
                    f.unlink()
            except Exception as e:
                logger.warning("删除 session 文件 %s 失败: %s", f, e)

        # 删除 session_string 相关存储（含仅存在于账号库中的条目，
        # 否则备注/代理/标签/设备画像会永久残留）
        if has_session_string or account_in_store or has_session_string_file:
            try:
                delete_account_session_string(account_name)
            except Exception as e:
                logger.warning("从 accounts.json 删除 %s 失败: %s", account_name, e)
        try:
            delete_session_string_file(self.session_dir, account_name)
        except Exception as e:
            logger.warning("删除 session_string 文件 %s 失败: %s", account_name, e)

        # 清理该账号的登录中会话：账号删除后残留的登录轮询/QR 会话
        # 会让该账号继续出现在账号列表中，并在重建同名账号时继承旧登录状态
        for store in (_login_sessions, _qr_login_sessions):
            stale = [
                key
                for key, value in store.items()
                if str((value or {}).get("account_name") or "").strip().lower()
                == account_name.lower()
            ]
            for key in stale:
                store.pop(key, None)

        # 使缓存失效
        self._accounts_cache = None

        return True


    async def rename_account(self, old_name: str, new_name: str) -> str:
        """
        重命名账号（迁移 session 文件、profiles、签到任务引用、以及活跃 Client）。
        """
        old_name = self._normalize_account_name(old_name)
        new_name = self._normalize_account_name(new_name)

        if old_name == new_name:
            return new_name

        if not self.account_exists(old_name):
            raise ValueError(f"Account {old_name} not found")

        if self.account_exists(new_name):
            raise ValueError(f"Account {new_name} already exists")

        from backend.utils.account_locks import acquire_multi_account_locks
        from tg_signer.core import close_client_by_name

        async with acquire_multi_account_locks([old_name, new_name]):
            # 重命名前先关闭并释放活跃 Client 句柄
            try:
                await close_client_by_name(old_name, workdir=self.session_dir)
            except Exception as e:
                logger.warning("关闭旧账号 Client 句柄失败: %s", e)

            self._rename_pending_login_records(old_name, new_name)

            # 迁移 accounts.json 中的 profile 数据
            rename_account_entry(old_name, new_name)

            # 迁移文件
            for ext in (
                ".session",
                ".session-journal",
                ".session-shm",
                ".session-wal",
                ".session_string",
            ):
                src = self.session_dir / f"{old_name}{ext}"
                dst = self.session_dir / f"{new_name}{ext}"
                self._move_path(src, dst)

            # 联动迁移签到任务引用
            try:
                from backend.services.sign_tasks import get_sign_task_service

                get_sign_task_service().rename_account_references(old_name, new_name)
            except Exception as e:
                logger.warning("迁移账号签到任务引用失败: %s", e)

            # 刷新缓存
            self._accounts_cache = None

            # 改名后触发调度器同步与监听重启
            try:
                from backend.scheduler import get_scheduler

                await get_scheduler().sync_jobs()
            except Exception as e:
                logger.warning("改名后触发调度器同步失败: %s", e)

        return new_name

    async def import_session(
        self,
        account_name: str,
        payload: bytes | str,
        *,
        session_type: str = "auto",
        force: bool = False,
        proxy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """导入外部 Telegram 会话（Telethon SQLite, Pyrogram SQLite, Pyrogram StringSession）"""
        from backend.services.telegram.session_importer import (
            import_session as do_import_session,
        )

        res = await do_import_session(
            account_name=account_name,
            payload=payload,
            session_type=session_type,
            force=force,
            proxy=proxy,
            target_dir=self.session_dir,
        )
        self._accounts_cache = None
        return res

    async def import_tdata_session(
        self,
        account_name: str,
        zip_payload: bytes | Path,
        *,
        password: Optional[str] = None,
        force: bool = False,
        proxy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """导入 Telegram Desktop (TData) 归档包。"""
        from backend.services.telegram.tdata_importer import (
            import_tdata_session as do_import_tdata_session,
        )

        res = await do_import_tdata_session(
            account_name=account_name,
            zip_payload=zip_payload,
            password=password,
            force=force,
            proxy=proxy,
            target_dir=self.session_dir,
        )
        self._accounts_cache = None
        return res

    async def export_standalone_session(
        self,
        account_name: str,
        *,
        device_model: str = "TG-SignPulse Exported Session",
        timeout_seconds: float = 60.0,
    ):
        """派生独立 Session 导出（基于 auth.AcceptLoginToken 握手）。"""
        from backend.services.telegram.session_exporter import (
            create_standalone_session_export,
        )

        return await create_standalone_session_export(
            account_name=account_name,
            device_model=device_model,
            timeout_seconds=timeout_seconds,
            service=self,
        )


def get_telegram_account_service():
    from backend.services.telegram.runtime import get_telegram_service
    return get_telegram_service()

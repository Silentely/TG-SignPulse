"""登录会话临时存储与清理。"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("backend.qr_login")

# 全局存储临时的登录 session
_login_sessions: dict = {}
_qr_login_sessions: dict = {}

# 登录 session 清理常量
_LOGIN_SESSION_MAX_AGE = 1800  # 手机号登录 session 最大存活时间（30 分钟）
_QR_LOGIN_SESSION_MAX_AGE = 600  # 扫码登录 session 最大存活时间（10 分钟）
_MAX_LOGIN_SESSIONS = 50  # 每种登录 session 的最大数量


async def _release_login_session(value: Any) -> None:
    """断开登录 session 中的客户端连接并释放锁"""
    client = value.get("client")
    if client:
        try:
            if getattr(client, "is_connected", False):
                await client.disconnect()
        except Exception:
            pass
    lock = value.get("lock")
    if lock and lock.locked():
        lock.release()


async def _cleanup_expired_login_sessions() -> None:
    """清理过期的登录 session，防止内存泄漏。"""
    now = time.monotonic()

    for store, max_age in (
        (_login_sessions, _LOGIN_SESSION_MAX_AGE),
        (_qr_login_sessions, _QR_LOGIN_SESSION_MAX_AGE),
    ):
        expired_keys = [
            key
            for key, value in list(store.items())
            if value.get("_created_at") is not None
            and (now - value["_created_at"]) > max_age
        ]
        for key in expired_keys:
            value = store.pop(key, None)
            if value:
                await _release_login_session(value)

    for store in (_login_sessions, _qr_login_sessions):
        while len(store) > _MAX_LOGIN_SESSIONS:
            oldest_key = min(
                store.keys(),
                key=lambda k: store[k].get("_created_at", float("inf")),
            )
            value = store.pop(oldest_key, None)
            if value:
                await _release_login_session(value)

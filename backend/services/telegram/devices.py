"""TelegramService mixin: devices."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from backend.core.config import get_settings
from backend.utils.account_locks import get_account_lock
from backend.utils.time import utc_from_timestamp_iso_z

settings = get_settings()


logger = logging.getLogger("backend.qr_login")

class TelegramDevicesMixin:

    async def list_account_devices(
        self,
        account_name: str,
        timeout_seconds: float = 12.0,
    ) -> List[Dict[str, Any]]:
        """列出账号当前 Telegram 已登录设备/授权会话。"""
        from pyrogram import raw

        account_name = self._normalize_account_name(account_name)
        if not self.account_exists(account_name):
            raise ValueError("账号不存在")

        client, _ = self._build_account_client(account_name, no_updates=True)

        timeout_seconds = max(1.0, min(float(timeout_seconds or 12.0), 30.0))
        lock = get_account_lock(account_name)
        async with lock:
            if not getattr(client, "is_connected", False):
                await client.connect()
            result = await asyncio.wait_for(
                client.invoke(raw.functions.account.GetAuthorizations()),
                timeout=timeout_seconds,
            )

        devices = []
        for item in getattr(result, "authorizations", []) or []:
            devices.append(
                {
                    "hash": str(getattr(item, "hash", "")),
                    "current": bool(getattr(item, "current", False)),
                    "official_app": bool(getattr(item, "official_app", False)),
                    "password_pending": bool(getattr(item, "password_pending", False)),
                    "device_model": getattr(item, "device_model", "") or "",
                    "platform": getattr(item, "platform", "") or "",
                    "system_version": getattr(item, "system_version", "") or "",
                    "app_name": getattr(item, "app_name", "") or "",
                    "app_version": getattr(item, "app_version", "") or "",
                    "date_created": utc_from_timestamp_iso_z(
                        getattr(item, "date_created", 0)
                    )
                    if getattr(item, "date_created", None)
                    else None,
                    "date_active": utc_from_timestamp_iso_z(
                        getattr(item, "date_active", 0)
                    )
                    if getattr(item, "date_active", None)
                    else None,
                    "ip": getattr(item, "ip", "") or "",
                    "country": getattr(item, "country", "") or "",
                    "region": getattr(item, "region", "") or "",
                }
            )
        return devices


    async def terminate_account_device(
        self,
        account_name: str,
        auth_hash: int,
        timeout_seconds: float = 12.0,
    ) -> bool:
        """踢下线指定 Telegram 授权会话。不能踢当前正在使用的会话。"""
        from pyrogram import raw

        account_name = self._normalize_account_name(account_name)
        if not self.account_exists(account_name):
            raise ValueError("账号不存在")

        devices = await self.list_account_devices(
            account_name, timeout_seconds=timeout_seconds
        )
        target = next((d for d in devices if str(d.get("hash")) == str(auth_hash)), None)
        if not target:
            raise ValueError("设备不存在或已下线")
        if target.get("current"):
            raise ValueError("不能踢下线当前正在使用的会话")

        client, _ = self._build_account_client(account_name, no_updates=True)

        timeout_seconds = max(1.0, min(float(timeout_seconds or 12.0), 30.0))
        lock = get_account_lock(account_name)
        async with lock:
            if not getattr(client, "is_connected", False):
                await client.connect()
            result = await asyncio.wait_for(
                client.invoke(raw.functions.account.ResetAuthorization(hash=auth_hash)),
                timeout=timeout_seconds,
            )
        return bool(result)


    async def list_official_messages(
        self,
        account_name: str,
        limit: int = 20,
        timeout_seconds: float = 12.0,
    ) -> List[Dict[str, Any]]:
        """读取账号与 Telegram 官方服务号 777000 的最近消息。"""
        account_name = self._normalize_account_name(account_name)
        if not self.account_exists(account_name):
            raise ValueError("账号不存在")

        client, _ = self._build_account_client(account_name, no_updates=True)

        limit = max(1, min(int(limit or 20), 50))
        timeout_seconds = max(1.0, min(float(timeout_seconds or 12.0), 30.0))
        lock = get_account_lock(account_name)

        async def _read_messages() -> List[Dict[str, Any]]:
            if not getattr(client, "is_connected", False):
                await client.connect()

            messages: List[Dict[str, Any]] = []
            async for msg in client.get_chat_history(777000, limit=limit):
                text = getattr(msg, "text", None) or getattr(msg, "caption", None) or ""
                messages.append(
                    {
                        "id": getattr(msg, "id", None),
                        "date": msg.date.isoformat().replace("+00:00", "Z")
                        if getattr(msg, "date", None)
                        else None,
                        "text": text,
                        "outgoing": bool(getattr(msg, "outgoing", False)),
                    }
                )
            return messages

        async with lock:
            return await asyncio.wait_for(_read_messages(), timeout=timeout_seconds)

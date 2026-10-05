from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from backend.core.config import get_settings
from backend.services.config import get_config_service
from backend.services.flood_backoff import get_flood_backoff_manager
from backend.services.telegram import get_telegram_service
from backend.utils.atomic_io import read_json_safe, write_json_atomic
from backend.utils.time import utc_now, utc_now_iso_z
from tg_signer.utils import extract_flood_wait_seconds

logger = logging.getLogger("backend.device_keepalive")


class DeviceKeepaliveService:
    """定期轻量检查账号会话，防止 6 个月不活跃后被 Telegram 自动踢下线。"""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.workdir = self.settings.resolve_workdir()
        self.state_file = self.workdir / ".device_keepalive_state.json"
        self._running_lock = asyncio.Lock()

    def _load_state(self) -> Dict[str, Any]:
        data = read_json_safe(self.state_file, default={"accounts": {}})
        if isinstance(data, dict):
            if not isinstance(data.get("accounts"), dict):
                data["accounts"] = {}
            return data
        return {"accounts": {}}

    def _save_state(self, state: Dict[str, Any]) -> None:
        """原子写入状态文件，避免崩溃导致文件损坏。"""
        try:
            write_json_atomic(self.state_file, state)
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("保存设备保活状态失败: %s", exc)

    @staticmethod
    def _parse_interval_days(value: Any, default: int = 30) -> int:
        """容错解析保活间隔：非法值回落默认，结果限制在 1~170 天。"""
        try:
            days = int(value if value not in (None, "") else default)
        except (TypeError, ValueError):
            days = default
        return max(1, min(days, 170))

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            text = str(value).replace("Z", "+00:00")
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None

    def get_status(self) -> Dict[str, Any]:
        config_service = get_config_service()
        if hasattr(config_service, "get_global_settings"):
            raw_settings = config_service.get_global_settings()
        else:
            raw_settings = config_service.load_global_settings()

        enabled = bool(
            raw_settings.get(
                "device_keepalive_enabled",
                raw_settings.get("enable_device_keepalive", True),
            )
        )
        interval_days = self._parse_interval_days(
            raw_settings.get("device_keepalive_interval_days")
        )

        state = self._load_state()
        accounts_state = state.get("accounts", {})
        account_list: List[Dict[str, Any]] = []

        service = get_telegram_service()
        configured_accounts = service.list_accounts(force_refresh=False)
        for acc in configured_accounts:
            name = str(acc.get("name") or "").strip()
            if not name:
                continue
            acc_info = accounts_state.get(name, {})
            last_ok_at = acc_info.get("last_ok_at")
            last_attempt_at = acc_info.get("last_attempt_at")
            last_error = acc_info.get("last_error")

            account_list.append(
                {
                    "account_name": name,
                    "last_ok_at": last_ok_at,
                    "last_attempt_at": last_attempt_at,
                    "last_error": last_error,
                }
            )

        return {
            "enabled": enabled,
            "interval_days": interval_days,
            "last_run_at": state.get("last_run_at"),
            "accounts": account_list,
        }

    async def run_due(self, force: bool = False) -> Dict[str, Any]:
        """执行设备保活检查。force=True 时忽略上次检查时间。"""
        config_service = get_config_service()
        if hasattr(config_service, "get_global_settings"):
            raw_settings = config_service.get_global_settings()
        else:
            raw_settings = config_service.load_global_settings()

        enabled = bool(
            raw_settings.get(
                "device_keepalive_enabled",
                raw_settings.get("enable_device_keepalive", True),
            )
        )

        if self._running_lock.locked():
            return {
                "success": False,
                "enabled": enabled,
                "checked": 0,
                "kept_alive": 0,
                "skipped": 0,
                "failed": 0,
                "results": [],
                "message": "设备保活正在运行中，请稍后重试",
            }

        async with self._running_lock:
            return await self._run_due_impl(force)

    async def run_keepalive(self, force: bool = False) -> Dict[str, Any]:
        """别名兼容 run_due。"""
        return await self.run_due(force=force)

    async def _run_due_impl(self, force: bool = False) -> Dict[str, Any]:
        """实际执行设备保活检查的内部方法。"""
        config_service = get_config_service()
        if hasattr(config_service, "get_global_settings"):
            raw_settings = config_service.get_global_settings()
        else:
            raw_settings = config_service.load_global_settings()

        enabled = bool(
            raw_settings.get(
                "device_keepalive_enabled",
                raw_settings.get("enable_device_keepalive", True),
            )
        )
        interval_days = self._parse_interval_days(
            raw_settings.get("device_keepalive_interval_days")
        )

        if not enabled and not force:
            return {
                "success": True,
                "enabled": False,
                "checked": 0,
                "kept_alive": 0,
                "skipped": 0,
                "failed": 0,
                "interval_days": interval_days,
                "results": [],
            }

        state = self._load_state()
        account_state = state.setdefault("accounts", {})
        now = utc_now()
        cutoff = now - timedelta(days=interval_days)

        service = get_telegram_service()
        accounts = service.list_accounts(force_refresh=True)
        results: List[Dict[str, Any]] = []
        kept_alive = skipped = failed = 0
        flood_mgr = get_flood_backoff_manager()

        for item in accounts:
            account_name = str(item.get("name") or "").strip()
            if not account_name:
                continue

            if flood_mgr.is_account_in_flood(account_name):
                rem = flood_mgr.get_remaining_wait(account_name)
                skipped += 1
                results.append(
                    {
                        "account_name": account_name,
                        "status": "skipped",
                        "message": f"FloodWait避让中 (剩余{rem}s)",
                        "last_ok_at": account_state.get(account_name, {}).get(
                            "last_ok_at"
                        ),
                    }
                )
                continue

            last_ok = self._parse_time(
                account_state.get(account_name, {}).get("last_ok_at")
            )
            if not force and last_ok and last_ok > cutoff:
                skipped += 1
                results.append(
                    {
                        "account_name": account_name,
                        "status": "skipped",
                        "message": "未到期",
                        "last_ok_at": last_ok.isoformat().replace("+00:00", "Z"),
                    }
                )
                continue

            try:
                status = await service.check_account_status(
                    account_name, timeout_seconds=12.0, no_updates=True
                )
                ok = bool(status.get("ok"))
                entry = account_state.setdefault(account_name, {})
                entry["last_attempt_at"] = utc_now_iso_z()
                if ok:
                    entry["last_ok_at"] = utc_now_iso_z()
                    entry["last_error"] = None
                    kept_alive += 1
                    results.append(
                        {
                            "account_name": account_name,
                            "status": "ok",
                            "message": "保活成功",
                        }
                    )
                else:
                    message = str(
                        status.get("message") or status.get("code") or "保活失败"
                    )
                    wait_sec = extract_flood_wait_seconds(message)
                    if wait_sec:
                        flood_mgr.record_flood_wait(
                            account_name,
                            wait_sec,
                            reason=f"Device keepalive FloodWait: {message}",
                        )
                    entry["last_error"] = message
                    failed += 1
                    results.append(
                        {
                            "account_name": account_name,
                            "status": "failed",
                            "message": message,
                        }
                    )
            except Exception as exc:
                wait_sec = extract_flood_wait_seconds(exc)
                if wait_sec:
                    flood_mgr.record_flood_wait(
                        account_name,
                        wait_sec,
                        reason=f"Device keepalive FloodWait: {exc}",
                    )
                entry = account_state.setdefault(account_name, {})
                entry["last_attempt_at"] = utc_now_iso_z()
                entry["last_error"] = str(exc)
                failed += 1
                logger.warning("设备保活失败 %s: %s", account_name, exc)
                results.append(
                    {
                        "account_name": account_name,
                        "status": "failed",
                        "message": str(exc),
                    }
                )

        state["last_run_at"] = utc_now_iso_z()
        self._save_state(state)
        return {
            "success": failed == 0,
            "enabled": enabled,
            "checked": kept_alive + failed,
            "kept_alive": kept_alive,
            "skipped": skipped,
            "failed": failed,
            "interval_days": interval_days,
            "results": results,
        }


_device_keepalive_service: DeviceKeepaliveService | None = None
_service_lock = threading.Lock()


def get_device_keepalive_service() -> DeviceKeepaliveService:
    """获取设备保活服务单例（双重检查锁保证多线程安全）。"""
    global _device_keepalive_service
    if _device_keepalive_service is None:
        with _service_lock:
            if _device_keepalive_service is None:
                _device_keepalive_service = DeviceKeepaliveService()
    return _device_keepalive_service

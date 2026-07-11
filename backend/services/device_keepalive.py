from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from backend.core.config import get_settings
from backend.services.config import get_config_service
from backend.services.telegram import get_telegram_service
from backend.utils.time import utc_now_iso_z

logger = logging.getLogger("backend.device_keepalive")


class DeviceKeepaliveService:
    """定期轻量检查账号会话，防止 6 个月不活跃后被 Telegram 自动踢下线。"""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.workdir = self.settings.resolve_workdir()
        self.state_file = self.workdir / ".device_keepalive_state.json"
        self._running_lock = asyncio.Lock()

    def _load_state(self) -> Dict[str, Any]:
        if not self.state_file.exists():
            return {"accounts": {}}
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                accounts = data.get("accounts")
                if not isinstance(accounts, dict):
                    data["accounts"] = {}
                return data
        except (json.JSONDecodeError, OSError):
            pass
        return {"accounts": {}}

    def _save_state(self, state: Dict[str, Any]) -> None:
        """原子写入状态文件（先写临时文件再重命名，避免崩溃导致文件损坏）。"""
        import tempfile

        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            # 使用临时文件写入，然后原子重命名
            fd, tmp_path = tempfile.mkstemp(
                dir=self.state_file.parent,
                prefix=".device_keepalive_",
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, self.state_file)
            except Exception:
                # 清理临时文件
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError as exc:
            logger.warning("保存设备保活状态失败: %s", exc)

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

    async def run_due(self, force: bool = False) -> Dict[str, Any]:
        """执行设备保活检查。force=True 时忽略上次检查时间。"""
        # 防止并发执行（调度器和手动端点可能重叠）
        if self._running_lock.locked():
            return {
                "success": False,
                "enabled": True,
                "checked": 0,
                "kept_alive": 0,
                "skipped": 0,
                "failed": 0,
                "results": [],
                "message": "设备保活正在运行中，请稍后重试",
            }

        async with self._running_lock:
            return await self._run_due_impl(force)

    async def _run_due_impl(self, force: bool = False) -> Dict[str, Any]:
        """实际执行设备保活检查的内部方法。"""
        config = get_config_service().get_global_settings()
        enabled = bool(config.get("device_keepalive_enabled", True))
        interval_days = int(config.get("device_keepalive_interval_days") or 30)
        interval_days = max(1, min(interval_days, 170))

        if not enabled and not force:
            return {
                "success": True,
                "enabled": False,
                "checked": 0,
                "kept_alive": 0,
                "skipped": 0,
                "failed": 0,
                "results": [],
            }

        state = self._load_state()
        account_state = state.setdefault("accounts", {})
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=interval_days)

        service = get_telegram_service()
        accounts = service.list_accounts(force_refresh=True)
        results: List[Dict[str, Any]] = []
        kept_alive = skipped = failed = 0

        for item in accounts:
            account_name = str(item.get("name") or "").strip()
            if not account_name:
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
                        "message": "not due",
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
                            "message": "keepalive ok",
                        }
                    )
                else:
                    message = str(
                        status.get("message") or status.get("code") or "failed"
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


def get_device_keepalive_service() -> DeviceKeepaliveService:
    """获取设备保活服务单例。"""
    global _device_keepalive_service
    if _device_keepalive_service is None:
        _device_keepalive_service = DeviceKeepaliveService()
    return _device_keepalive_service

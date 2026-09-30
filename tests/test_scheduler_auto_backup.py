"""自动备份调度任务：WebDAV 上传结果透传与失败通知。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

WEBDAV_CFG = {
    "auto_backup_enabled": True,
    "auto_backup_interval_hours": 24,
    "auto_backup_keep": 2,
    "webdav_url": "https://93.184.216.34/dav",
    "webdav_username": "u",
    "webdav_password": "p",
}


def _drive(result: dict) -> object:
    """以给定 run_auto_backup 返回值驱动一次调度任务，返回其 mock。"""
    from backend.scheduler import _job_auto_backup

    with patch(
        "backend.services.backup_archive.run_auto_backup", return_value=result
    ) as run_m:
        asyncio.run(_job_auto_backup())
    return run_m


class TestAutoBackupJob:
    def test_passes_webdav_settings_and_notifies_on_failure(self, isolated_env: Path):
        from backend.services.config import get_config_service

        get_config_service().save_global_settings(dict(WEBDAV_CFG))

        with patch(
            "backend.services.push_notifications.send_auto_backup_failure_notification",
            new_callable=AsyncMock,
        ) as notify_m:
            run_m = _drive(
                {
                    "success": True,
                    "path": "https://93.184.216.34/dav/auto-1.tar.gz",
                    "size_bytes": 10,
                    "pruned": 0,
                    "remote_pruned": 1,
                    "local_removed": True,
                    "webdav": {"success": False, "error": "HTTP 502"},
                }
            )

        kwargs = run_m.call_args.kwargs
        assert kwargs["webdav_settings"]["webdav_url"] == "https://93.184.216.34/dav"
        notify_m.assert_called_once()
        assert "HTTP 502" in notify_m.call_args.kwargs["error"]

    def test_no_notification_when_webdav_upload_succeeds(self, isolated_env: Path):
        from backend.services.config import get_config_service

        get_config_service().save_global_settings(dict(WEBDAV_CFG))

        with patch(
            "backend.services.push_notifications.send_auto_backup_failure_notification",
            new_callable=AsyncMock,
        ) as notify_m:
            _drive(
                {
                    "success": True,
                    "path": "https://93.184.216.34/dav/auto-1.tar.gz",
                    "size_bytes": 10,
                    "pruned": 0,
                    "remote_pruned": 0,
                    "local_removed": True,
                    "webdav": {"success": True},
                }
            )
        notify_m.assert_not_called()

    def test_disabled_auto_backup_skips(self, isolated_env: Path):
        from backend.scheduler import _job_auto_backup
        from backend.services.config import get_config_service

        get_config_service().save_global_settings({"auto_backup_enabled": False})
        with patch("backend.services.backup_archive.run_auto_backup") as run_m:
            asyncio.run(_job_auto_backup())
        run_m.assert_not_called()

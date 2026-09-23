"""自动备份调度任务：对象存储上传结果透传与失败通知。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

S3_CFG = {
    "auto_backup_enabled": True,
    "auto_backup_interval_hours": 24,
    "auto_backup_keep": 2,
    "s3_enabled": True,
    "s3_endpoint_url": "https://s3.example.com",
    "s3_bucket": "bk",
    "s3_access_key": "AK",
    "s3_secret_key": "SK",
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
    def test_passes_s3_settings_and_notifies_on_failure(self, isolated_env: Path):
        from backend.services.config import get_config_service

        get_config_service().save_global_settings(dict(S3_CFG))

        with patch(
            "backend.services.push_notifications.send_auto_backup_failure_notification",
            new_callable=AsyncMock,
        ) as notify_m:
            run_m = _drive(
                {
                    "success": True,
                    "path": "https://s3.example.com/bk/auto-1.tar.gz",
                    "size_bytes": 10,
                    "pruned": 0,
                    "remote_pruned": 1,
                    "local_removed": True,
                    "webdav": None,
                    "s3": {"success": False, "error": "HTTP 502"},
                }
            )

        # 全局设置整体透传：对象存储字段随 cfg 一起下发给备份执行器
        kwargs = run_m.call_args.kwargs
        assert kwargs["s3_settings"]["s3_endpoint_url"] == "https://s3.example.com"
        assert kwargs["webdav_settings"]["s3_endpoint_url"] == "https://s3.example.com"
        notify_m.assert_called_once()
        assert "HTTP 502" in notify_m.call_args.kwargs["error"]

    def test_no_notification_when_s3_upload_succeeds(self, isolated_env: Path):
        from backend.services.config import get_config_service

        get_config_service().save_global_settings(dict(S3_CFG))

        with patch(
            "backend.services.push_notifications.send_auto_backup_failure_notification",
            new_callable=AsyncMock,
        ) as notify_m:
            _drive(
                {
                    "success": True,
                    "path": "https://s3.example.com/bk/auto-1.tar.gz",
                    "size_bytes": 10,
                    "pruned": 0,
                    "remote_pruned": 0,
                    "local_removed": True,
                    "webdav": None,
                    "s3": {"success": True},
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

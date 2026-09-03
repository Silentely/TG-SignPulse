from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from backend.api.routes.ops import _human_size
from backend.services.push_notifications import is_in_quiet_hours
from backend.services.sign_task_history_format import build_history_list_item
from backend.services.telegram.accounts import _session_file_info
from backend.services.telegram.login_qr import TelegramQrLoginMixin
from backend.services.webdav_client import upload_file_to_webdav


def test_is_in_quiet_hours_seconds_format():
    cfg = {
        "telegram_bot_quiet_hours_enabled": True,
        "telegram_bot_quiet_hours_start": "23:00:00",
        "telegram_bot_quiet_hours_end": "07:00:00",
        "timezone": "UTC",
    }
    # 23:30 should be in quiet hours
    assert is_in_quiet_hours(cfg, datetime(2026, 7, 18, 23, 30, tzinfo=ZoneInfo("UTC")))
    # 06:15 should be in quiet hours
    assert is_in_quiet_hours(cfg, datetime(2026, 7, 18, 6, 15, tzinfo=ZoneInfo("UTC")))
    # 12:00 should NOT be in quiet hours
    assert not is_in_quiet_hours(cfg, datetime(2026, 7, 18, 12, 0, tzinfo=ZoneInfo("UTC")))


def test_session_file_info_string_and_path(tmp_path: Path):
    f = tmp_path / "test.session"
    f.write_text("dummy")

    # Pass Path
    exists, size = _session_file_info(f)
    assert exists is True
    assert size == 5

    # Pass str
    exists, size = _session_file_info(str(f))
    assert exists is True
    assert size == 5

    # Nonexistent str
    exists, size = _session_file_info(str(tmp_path / "none.session"))
    assert exists is False
    assert size == 0


def test_build_history_list_item_handles_none_flc():
    item = {
        "time": "2026-03-29T12:00:00Z",
        "success": True,
        "message": "ok",
        "flow_logs": ["line 1", "line 2"],
        "flow_line_count": None,
    }
    out = build_history_list_item(
        item,
        task_name="t1",
        account_name="a1",
        repair=lambda s: s,
        extract_last_target=lambda _logs: "",
    )
    assert out["flow_line_count"] == 2
    assert out["task_name"] == "t1"


def test_ops_human_size():
    assert _human_size(-10) == "0 B"
    assert _human_size(None) == "0 B"  # type: ignore[arg-type]
    assert _human_size(0) == "0 B"
    assert _human_size(512) == "512 B"
    assert _human_size(1024) == "1.0 KB"
    assert _human_size(1024 * 1024 * 5) == "5.0 MB"


def test_upload_file_to_webdav_filename_traversal(tmp_path: Path):
    local_f = tmp_path / "backup.tar.gz"
    local_f.write_text("test")

    with pytest.raises(ValueError, match="非法备份文件名"):
        upload_file_to_webdav(
            base_url="https://dav.example.com",
            username="user",
            password="pwd",
            remote_dir="",
            local_path=local_f,
            filename="../../unsafe.tar.gz",
        )


@pytest.mark.asyncio
async def test_qr_login_whitespace_stripped():
    class Dummy(TelegramQrLoginMixin):
        pass

    dummy = Dummy()
    # Padded non-existent login_id should cleanly return expired/False without crash
    status = await dummy.get_qr_login_status("  not_exist  ")
    assert status["status"] == "expired"

    cancelled = await dummy.cancel_qr_login("  not_exist  ")
    assert cancelled is False

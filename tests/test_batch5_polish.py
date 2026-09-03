from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from backend.api.routes.auth import _resolve_request_ip
from backend.services.avatar_cache import cleanup_avatar_cache
from backend.services.backup_archive import (
    auto_backup_interval_hours,
    should_run_auto_backup,
)
from backend.utils.paths import is_safe_subpath
from backend.utils.time_window import is_within_time_window


def test_backup_settings_guards():
    assert should_run_auto_backup(None) is False
    assert should_run_auto_backup({}) is False
    assert should_run_auto_backup({"auto_backup_enabled": True}) is True

    assert auto_backup_interval_hours(None) == 24
    assert auto_backup_interval_hours({}) == 24
    assert auto_backup_interval_hours({"auto_backup_interval_hours": "48"}) == 48
    assert auto_backup_interval_hours({"auto_backup_interval_hours": 9999}) == 168
    assert auto_backup_interval_hours({"auto_backup_interval_hours": -10}) == 1


def test_resolve_request_ip_length_guard():
    req = MagicMock()
    req.headers = {"x-forwarded-for": "1.1.1.1" + ", 2.2.2.2" * 50}
    ip = _resolve_request_ip(req)
    assert len(ip) <= 64
    assert ip == "1.1.1.1"

    req.headers = {"x-real-ip": "a" * 100}
    ip = _resolve_request_ip(req)
    assert len(ip) <= 64


def test_is_safe_subpath(tmp_path: Path):
    parent = tmp_path / "base"
    parent.mkdir()
    child = parent / "sub" / "file.txt"
    child.parent.mkdir()
    child.touch()

    assert is_safe_subpath(parent, child) is True

    outside = tmp_path / "outside.txt"
    outside.touch()
    assert is_safe_subpath(parent, outside) is False


def test_is_within_time_window_type_safety():
    # Non-datetime returns True (safe fallback)
    assert is_within_time_window(None, "10:00", "12:00") is True  # type: ignore[arg-type]
    now = datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc)
    assert is_within_time_window(now, "10:00", "12:00") is True
    assert is_within_time_window(now, "13:00", "14:00") is False


def test_cleanup_avatar_cache_ttl_guard(tmp_path: Path):
    # Non-existent dir or invalid ttl shouldn't crash
    assert cleanup_avatar_cache(tmp_path / "missing", None) == 0  # type: ignore[arg-type]
    assert cleanup_avatar_cache(tmp_path / "missing", "bad") == 0  # type: ignore[arg-type]

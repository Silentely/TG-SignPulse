"""签到历史 IO 纯函数测试。"""
from __future__ import annotations

import json
from pathlib import Path

from backend.services.sign_task_history_io import (
    count_history_entries,
    filter_history_entries,
    history_file_path,
    load_history_entries,
    load_history_payload_from_file,
    resolve_existing_history_file,
    safe_history_key,
)


def test_safe_history_key_and_path(tmp_path: Path):
    assert safe_history_key("a/b\\c") == "a_b_c"
    p = history_file_path(tmp_path, "task1", "acc1")
    assert p.name == "acc1__task1.json"
    p2 = history_file_path(tmp_path, "task1")
    assert p2.name == "task1.json"


def test_load_and_filter_history(tmp_path: Path):
    path = tmp_path / "acc__t.json"
    path.write_text(
        json.dumps(
            [
                {"time": "2026-01-02", "account_name": "acc", "success": True},
                {"time": "2026-01-01", "account_name": "other", "success": False},
                "bad",
            ]
        ),
        encoding="utf-8",
    )
    payload = load_history_payload_from_file(path)
    assert len(payload) == 3
    filtered = filter_history_entries(payload, account_name="acc")
    assert len(filtered) == 1
    assert filtered[0]["time"] == "2026-01-02"

    # resolve prefers account-scoped file
    assert resolve_existing_history_file(tmp_path, "t", "acc") == path


def test_load_history_entries_legacy_fallback(tmp_path: Path):
    legacy = tmp_path / "taskx.json"
    legacy.write_text(
        json.dumps({"time": "t1", "account_name": "a1", "success": True}),
        encoding="utf-8",
    )
    entries = load_history_entries(tmp_path, "taskx", account_name="a1")
    assert len(entries) == 1
    assert entries[0]["time"] == "t1"


def test_count_history_entries():
    assert count_history_entries([]) == 0
    assert count_history_entries([1, 2]) == 2
    assert count_history_entries({"a": 1}) == 1
    assert count_history_entries("x") == 0


def test_cleanup_respects_max_age_days(tmp_path: Path, monkeypatch):
    import time

    from backend.services.sign_task_history_io import (
        clamp_max_age_days,
        cleanup_old_history_files,
    )

    assert clamp_max_age_days(0) == 1
    assert clamp_max_age_days("x") == 3

    old = tmp_path / "old.json"
    old.write_text("[]", encoding="utf-8")
    # 设为 10 天前
    old_mtime = time.time() - 10 * 86400
    import os

    os.utime(old, (old_mtime, old_mtime))
    fresh = tmp_path / "fresh.json"
    fresh.write_text("[]", encoding="utf-8")

    removed = cleanup_old_history_files(tmp_path, max_age_days=3)
    assert removed == 1
    assert not old.exists()
    assert fresh.exists()

"""签到历史轻量索引测试。"""
from __future__ import annotations

import json
from pathlib import Path

from backend.services.sign_task_history_index import (
    append_index_entry,
    build_index_entry,
    clear_index,
    clear_memory_cache,
    entry_from_history_item,
    index_file_path,
    list_recent_from_index,
    read_index_entries,
    rebuild_index_from_history_files,
    remove_index_entries_matching,
)


def setup_function() -> None:
    clear_memory_cache()


def test_build_and_append_roundtrip(tmp_path: Path):
    entry = build_index_entry(
        time="2026-07-26T10:00:00",
        account_name="acc1",
        task_name="daily",
        success=True,
        message="ok",
        failure_category="",
    )
    append_index_entry(tmp_path, entry)
    append_index_entry(
        tmp_path,
        build_index_entry(
            time="2026-07-26T11:00:00",
            account_name="acc1",
            task_name="daily",
            success=False,
            message="fail",
            failure_category="network",
        ),
    )
    path = index_file_path(tmp_path)
    assert path.exists()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2

    recent = read_index_entries(tmp_path, limit=10)
    assert len(recent) == 2
    assert recent[0]["time"] == "2026-07-26T11:00:00"
    assert recent[0]["success"] is False
    assert recent[1]["success"] is True


def test_list_recent_prefers_memory_after_append(tmp_path: Path):
    append_index_entry(
        tmp_path,
        build_index_entry(
            time="t1",
            account_name="a",
            task_name="t",
            success=True,
        ),
    )
    items = list_recent_from_index(tmp_path, limit=5)
    assert len(items) == 1
    assert items[0]["task_name"] == "t"


def test_filter_by_account_and_date(tmp_path: Path):
    for acc, ts in [("a1", "2026-01-01T01:00:00"), ("a2", "2026-01-02T01:00:00"), ("a1", "2026-01-02T02:00:00")]:
        append_index_entry(
            tmp_path,
            build_index_entry(
                time=ts,
                account_name=acc,
                task_name="x",
                success=True,
            ),
        )
    only_a1 = read_index_entries(tmp_path, limit=10, account_name="a1")
    assert len(only_a1) == 2
    assert all(e["account_name"] == "a1" for e in only_a1)

    day2 = read_index_entries(tmp_path, limit=10, date_prefix="2026-01-02")
    assert len(day2) == 2


def test_remove_and_clear(tmp_path: Path):
    append_index_entry(
        tmp_path,
        build_index_entry(
            time="t1", account_name="a", task_name="task", success=True
        ),
    )
    append_index_entry(
        tmp_path,
        build_index_entry(
            time="t2", account_name="a", task_name="task", success=False
        ),
    )
    n = remove_index_entries_matching(
        tmp_path, account_name="a", task_name="task", created_at="t1"
    )
    assert n == 1
    left = read_index_entries(tmp_path, limit=10)
    assert len(left) == 1
    assert left[0]["time"] == "t2"

    clear_index(tmp_path)
    assert not index_file_path(tmp_path).exists()
    assert read_index_entries(tmp_path, limit=5) == []


def test_rebuild_from_history_json(tmp_path: Path):
    hist = tmp_path / "acc1__daily.json"
    hist.write_text(
        json.dumps(
            [
                {
                    "time": "2026-03-01T00:00:00",
                    "account_name": "acc1",
                    "success": True,
                    "message": "m1",
                },
                {
                    "time": "2026-03-02T00:00:00",
                    "account_name": "acc1",
                    "success": False,
                    "message": "m2",
                    "failure_category": "timeout",
                },
            ]
        ),
        encoding="utf-8",
    )
    n = rebuild_index_from_history_files(tmp_path)
    assert n == 2
    recent = list_recent_from_index(tmp_path, limit=10, prefer_memory=False)
    assert recent[0]["time"] == "2026-03-02T00:00:00"
    assert recent[0]["failure_category"] == "timeout"


def test_entry_from_history_item():
    e = entry_from_history_item(
        {"time": "t", "success": 1, "message": "hi", "failure_category": "x"},
        task_name="tn",
        account_name="an",
    )
    assert e["task_name"] == "tn"
    assert e["account_name"] == "an"
    assert e["success"] is True

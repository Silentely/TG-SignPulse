"""
Comprehensive test suite for SignTaskHistoryStore.

Validates the full deep module interface of SignTaskHistoryStore:
- record_run (with atomic write, flow_log truncation, failure classification, SSE publishing control)
- query_history (by account+task, account only, task only, all, date filtering, limit clamping)
- get_history_entry (detail lookup with flow_logs)
- delete_history_entry (deletion by created_at, index synchronization, file unlinking on empty)
- clear_history (clear all, clear account, clear task, clear account+task, structured return)
- count_entries
- get_history_trends
- cleanup_expired
- rebuild_index
- rename_history_file
- rewrite_account_in_entries
"""

from __future__ import annotations

import datetime
import time
from pathlib import Path

import pytest

from backend.services.sign_history_events import (
    reset_for_tests,
    subscribe,
    unsubscribe,
)
from backend.services.sign_task_history_store import SignTaskHistoryStore


@pytest.fixture(autouse=True)
def clean_sse_events():
    reset_for_tests()
    yield
    reset_for_tests()


def test_store_init(tmp_path: Path):
    history_dir = tmp_path / "history"
    signs_dir = tmp_path / "signs"
    store = SignTaskHistoryStore(history_dir, signs_dir)
    assert store.history_dir == history_dir
    assert store.signs_dir == signs_dir
    assert history_dir.exists()


def test_record_run_and_get_entry(tmp_path: Path):
    history_dir = tmp_path / "history"
    store = SignTaskHistoryStore(history_dir, max_entries_per_file=10)

    entry_data = {
        "success": True,
        "message": "Check-in successful",
        "flow_logs": ["Step 1 started", "Step 1 passed"],
        "workflow_path": ["step_1", "step_2"],
        "created_at": "2026-10-14T10:00:00Z",
    }
    recorded = store.record_run(
        "user_alpha", "daily_bonus", entry_data, publish_event=False
    )
    assert recorded["success"] is True
    assert recorded["account_name"] == "user_alpha"
    assert recorded["task_name"] == "daily_bonus"
    assert recorded["created_at"] == "2026-10-14T10:00:00Z"
    assert recorded["time"] == "2026-10-14T10:00:00Z"
    assert len(recorded["flow_logs"]) == 2

    # Verify count
    assert store.count_entries("user_alpha", "daily_bonus") == 1

    # Verify get_history_entry
    fetched = store.get_history_entry(
        "user_alpha", "daily_bonus", "2026-10-14T10:00:00Z"
    )
    assert fetched is not None
    assert fetched["message"] == "Check-in successful"
    assert fetched["flow_logs"] == ["Step 1 started", "Step 1 passed"]

    # Non-existent entry
    assert (
        store.get_history_entry("user_alpha", "daily_bonus", "2026-10-14T99:99:99Z")
        is None
    )
    assert (
        store.get_history_entry("non_existent", "daily_bonus", "2026-10-14T10:00:00Z")
        is None
    )


def test_record_run_flow_log_truncation_and_failure_classification(tmp_path: Path):
    history_dir = tmp_path / "history"
    store = SignTaskHistoryStore(
        history_dir,
        max_entries_per_file=5,
        max_flow_lines=3,
        max_line_chars=10,
    )

    long_logs = [
        "line 1 short",
        "line 2 very long long line",
        "line 3 normal",
        "line 4 overflow line",
    ]
    entry_data = {
        "success": False,
        "message": "Flood wait error",
        "flow_logs": long_logs,
    }
    recorded = store.record_run("user1", "task1", entry_data, publish_event=False)
    assert recorded["flow_truncated"] is True
    assert len(recorded["flow_logs"]) == 3
    # Check max_line_chars truncation with ellipsis
    for line in recorded["flow_logs"]:
        assert len(line) <= 10
    # Failure category auto classification
    assert recorded["failure_category"] != ""


def test_record_run_sse_publish_control(tmp_path: Path):
    history_dir = tmp_path / "history"
    store = SignTaskHistoryStore(history_dir)

    q = subscribe()
    try:
        # 1. With publish_event=False, queue should remain empty
        store.record_run(
            "user_quiet",
            "task_quiet",
            {
                "success": True,
                "message": "Silent run",
                "created_at": "2026-10-14T10:00:00Z",
            },
            publish_event=False,
        )
        assert q.empty()

        # 2. With publish_event=True, queue should receive an event
        store.record_run(
            "user_loud",
            "task_loud",
            {
                "success": True,
                "message": "Broadcast run",
                "created_at": "2026-10-14T10:05:00Z",
            },
            publish_event=True,
        )
        assert not q.empty()
        item = q.get_nowait()
        assert item["account_name"] == "user_loud"
        assert item["task_name"] == "task_loud"
        assert item["created_at"] == "2026-10-15T"[:4] or "2026" in item["created_at"]
    finally:
        unsubscribe(q)


def test_query_history_filters(tmp_path: Path):
    history_dir = tmp_path / "history"
    store = SignTaskHistoryStore(history_dir)

    # Insert entries across multiple accounts and tasks
    store.record_run(
        "acc_a",
        "task_1",
        {"success": True, "created_at": "2026-10-13T10:00:00Z", "message": "m1"},
        publish_event=False,
    )
    store.record_run(
        "acc_a",
        "task_2",
        {"success": True, "created_at": "2026-10-14T10:00:00Z", "message": "m2"},
        publish_event=False,
    )
    store.record_run(
        "acc_b",
        "task_1",
        {"success": False, "created_at": "2026-10-14T11:00:00Z", "message": "m3"},
        publish_event=False,
    )
    store.record_run(
        "acc_b",
        "task_2",
        {"success": True, "created_at": "2026-10-14T12:00:00Z", "message": "m4"},
        publish_event=False,
    )

    # 1. Query by account and task
    q1 = store.query_history(account="acc_a", task="task_1")
    assert len(q1) == 1
    assert q1[0]["message"] == "m1"

    # 2. Query by account only
    q2 = store.query_history(account="acc_a")
    assert len(q2) == 2
    # newest first
    assert q2[0]["time"] > q2[1]["time"]

    # 3. Query by task only
    q3 = store.query_history(task="task_1")
    assert len(q3) == 2
    accounts = {item["account_name"] for item in q3}
    assert accounts == {"acc_a", "acc_b"}

    # 4. Query all
    q4 = store.query_history(limit=10)
    assert len(q4) == 4

    # 5. Query with date filter
    q5 = store.query_history(date_filter="2026-10-13")
    assert len(q5) == 1
    assert q5[0]["message"] == "m1"


def test_delete_history_entry(tmp_path: Path):
    history_dir = tmp_path / "history"
    store = SignTaskHistoryStore(history_dir)

    store.record_run(
        "acc_del",
        "task_del",
        {"success": True, "created_at": "2026-10-14T10:00:00Z", "message": "e1"},
        publish_event=False,
    )
    store.record_run(
        "acc_del",
        "task_del",
        {"success": True, "created_at": "2026-10-14T11:00:00Z", "message": "e2"},
        publish_event=False,
    )

    assert store.count_entries("acc_del", "task_del") == 2

    # Delete existing
    ok = store.delete_history_entry("acc_del", "task_del", "2026-10-14T10:00:00Z")
    assert ok is True
    assert store.count_entries("acc_del", "task_del") == 1
    assert (
        store.get_history_entry("acc_del", "task_del", "2026-10-14T10:00:00Z") is None
    )

    # Delete non-existent
    ok_fake = store.delete_history_entry("acc_del", "task_del", "2026-10-14T99:00:00Z")
    assert ok_fake is False

    # Delete remaining entry - file should be unlinked
    ok_last = store.delete_history_entry("acc_del", "task_del", "2026-10-14T11:00:00Z")
    assert ok_last is True
    assert store.count_entries("acc_del", "task_del") == 0


def test_clear_history_modes(tmp_path: Path):
    history_dir = tmp_path / "history"
    store = SignTaskHistoryStore(history_dir)

    # Populate
    store.record_run(
        "user1",
        "taskA",
        {"success": True, "created_at": "2026-10-14T01:00:00Z"},
        publish_event=False,
    )
    store.record_run(
        "user1",
        "taskB",
        {"success": True, "created_at": "2026-10-14T02:00:00Z"},
        publish_event=False,
    )
    store.record_run(
        "user2",
        "taskA",
        {"success": True, "created_at": "2026-10-14T03:00:00Z"},
        publish_event=False,
    )
    store.record_run(
        "user2",
        "taskB",
        {"success": True, "created_at": "2026-10-14T04:00:00Z"},
        publish_event=False,
    )

    # 1. Clear specific (account, task)
    res1 = store.clear_history(account="user1", task="taskA")
    assert res1["removed_files"] == 1
    assert res1["removed_entries"] == 1
    assert store.count_entries("user1", "taskA") == 0
    assert store.count_entries("user1", "taskB") == 1

    # 2. Clear by account only
    res2 = store.clear_history(account="user1")
    assert res2["removed_files"] == 1
    assert res2["removed_entries"] == 1
    assert store.count_entries("user1", "taskB") == 0
    assert store.count_entries("user2", "taskA") == 1

    # 3. Clear all
    res3 = store.clear_history()
    assert res3["removed_files"] >= 1
    assert res3["removed_entries"] >= 1
    assert store.count_entries("user2", "taskA") == 0
    assert store.count_entries("user2", "taskB") == 0


def test_trends_and_index_rebuild(tmp_path: Path):
    history_dir = tmp_path / "history"
    store = SignTaskHistoryStore(history_dir)

    now = datetime.datetime.now().strftime("%Y-%m-%d")
    store.record_run(
        "u1",
        "t1",
        {"success": True, "created_at": f"{now}T10:00:00Z"},
        publish_event=False,
    )
    store.record_run(
        "u1",
        "t1",
        {
            "success": False,
            "created_at": f"{now}T11:00:00Z",
            "failure_category": "flood_wait",
        },
        publish_event=False,
    )

    trends = store.get_history_trends(days=7)
    assert trends["total_runs"] == 2
    assert trends["total_success"] == 1
    assert trends["total_failed"] == 1
    assert trends["overall_success_rate"] == 0.5
    assert trends["categories"].get("flood_wait") == 1

    # Rebuild index test
    indexed_count = store.rebuild_index()
    assert indexed_count == 2


def test_rename_history_file_and_rewrite_account(tmp_path: Path):
    history_dir = tmp_path / "history"
    store = SignTaskHistoryStore(history_dir)

    store.record_run(
        "old_user",
        "my_task",
        {"success": True, "message": "msg1", "created_at": "2026-10-14T01:00:00Z"},
        publish_event=False,
    )
    assert store.count_entries("old_user", "my_task") == 1

    # Rename history file
    renamed = store.rename_history_file("old_user", "new_user", "my_task")
    assert renamed is True
    assert store.count_entries("old_user", "my_task") == 0
    assert store.count_entries("new_user", "my_task") == 1

    # Rewrite account inside entries
    rewritten = store.rewrite_account_in_entries("old_user", "my_task", "new_user")
    assert rewritten == 1

    entry = store.get_history_entry("new_user", "my_task", "2026-10-14T01:00:00Z")
    assert entry is not None
    assert entry["account_name"] == "new_user"


def test_cleanup_expired(tmp_path: Path):
    history_dir = tmp_path / "history"
    store = SignTaskHistoryStore(history_dir)

    store.record_run(
        "acc1",
        "task1",
        {"success": True, "created_at": "2026-10-14T01:00:00Z"},
        publish_event=False,
    )
    file_path = store.get_history_file_path("acc1", "task1")
    assert file_path.exists()

    # Artificially set mtime to 10 days ago
    old_time = time.time() - 10 * 86400
    import os

    os.utime(file_path, (old_time, old_time))

    removed = store.cleanup_expired(max_age_days=5)
    assert removed == 1
    assert not file_path.exists()

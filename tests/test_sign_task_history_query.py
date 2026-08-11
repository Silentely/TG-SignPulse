"""sign_task_history_query 纯函数测试。"""
from __future__ import annotations

from backend.services.sign_task_history_query import (
    collect_formatted_history_items,
    find_history_item_by_time,
    sort_history_items_desc,
)


def _repair(s: str) -> str:
    return s


def _extract(_lines: list) -> str:
    return ""


def test_collect_formatted_history_items_filters_and_formats():
    raw = [
        {"time": "2026-07-01T10:00:00", "success": True, "message": "ok"},
        {"time": "2026-07-02T11:00:00", "success": False, "message": "fail"},
        "skip-me",
        {"time": "2026-07-01T12:00:00", "success": True, "message": "ok2"},
    ]
    items = collect_formatted_history_items(
        raw,
        task_name="t1",
        account_name="a1",
        repair=_repair,
        extract_last_target=_extract,
        date_prefix="2026-07-01",
    )
    assert len(items) == 2
    assert all(i["task_name"] == "t1" for i in items)
    assert all(i["account_name"] == "a1" for i in items)
    assert all(str(i["time"]).startswith("2026-07-01") for i in items)


def test_sort_history_items_desc_with_limit():
    items = [
        {"time": "2026-07-01T10:00:00"},
        {"time": "2026-07-03T10:00:00"},
        {"time": "2026-07-02T10:00:00"},
    ]
    out = sort_history_items_desc(items, limit=2)
    assert [x["time"] for x in out] == [
        "2026-07-03T10:00:00",
        "2026-07-02T10:00:00",
    ]


def test_find_history_item_by_time():
    raw = [
        {"time": "2026-07-01T10:00:00", "success": True, "message": "a"},
        {"time": "2026-07-01T11:00:00", "success": False, "message": "b"},
    ]
    found = find_history_item_by_time(
        raw,
        target_time="2026-07-01T11:00:00",
        task_name="t",
        account_name="acc",
        repair=_repair,
        extract_last_target=_extract,
    )
    assert found is not None
    assert found["message"] == "b"
    assert found["success"] is False
    assert (
        find_history_item_by_time(
            raw,
            target_time="missing",
            task_name="t",
            account_name="acc",
            repair=_repair,
            extract_last_target=_extract,
        )
        is None
    )


def test_prefer_entry_account():
    raw = [
        {
            "time": "2026-07-01T10:00:00",
            "success": True,
            "message": "ok",
            "account_name": "other",
        }
    ]
    items = collect_formatted_history_items(
        raw,
        task_name="t1",
        account_name="fallback",
        repair=_repair,
        extract_last_target=_extract,
        prefer_entry_account=True,
    )
    assert items[0]["account_name"] == "other"

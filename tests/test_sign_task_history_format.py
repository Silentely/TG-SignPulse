"""历史条目格式化纯函数测试。"""
from __future__ import annotations

from backend.services.sign_task_history_format import (
    build_history_list_item,
    clamp_limit,
    normalize_flow_logs,
)


def test_clamp_limit():
    assert clamp_limit(0) == 1
    assert clamp_limit(50) == 50
    assert clamp_limit(9999, maximum=200) == 200
    assert clamp_limit("x") == 1


def test_normalize_flow_logs():
    assert normalize_flow_logs(None) == []
    assert normalize_flow_logs(["a"]) == ["a"]


def test_build_history_list_item():
    item = {
        "time": "2026-07-16T10:00:00",
        "success": False,
        "message": "fail",
        "flow_logs": ["line1"],
        "failure_category": "timeout",
    }
    out = build_history_list_item(
        item,
        task_name="t1",
        account_name="a1",
        repair=lambda s: s,
        extract_last_target=lambda logs: "target",
    )
    assert out["task_name"] == "t1"
    assert out["account_name"] == "a1"
    assert out["created_at"] == "2026-07-16T10:00:00"
    assert out["failure_category"] == "timeout"
    assert out["last_target_message"] == "target"

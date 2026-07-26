"""sign_task_config_build 纯函数测试。"""
from __future__ import annotations

from backend.services.sign_task_config_build import (
    apply_account_rename_to_config,
    build_sign_task_config,
    next_task_group_id,
    resolve_update_field_values,
)


def test_build_sign_task_config_defaults():
    cfg = build_sign_task_config(
        account_name="acc1",
        account_names=["acc1"],
        sign_at="09:00",
        chats=[{"chat_id": 1}],
    )
    assert cfg["_version"] == 4
    assert cfg["account_name"] == "acc1"
    assert cfg["enabled"] is True
    assert cfg["retry_count"] == 3
    assert "last_run" not in cfg


def test_build_sign_task_config_with_last_run():
    cfg = build_sign_task_config(
        account_name="a",
        account_names=["a", "b"],
        task_group_id="g1",
        sign_at="08:00",
        chats=[],
        last_run={"success": True},
    )
    assert cfg["task_group_id"] == "g1"
    assert cfg["last_run"]["success"] is True


def test_resolve_update_field_values_merges():
    existing = {
        "sign_at": "08:00",
        "random_seconds": 5,
        "sign_interval": 2,
        "chats": [{"chat_id": 1}],
        "execution_mode": "fixed",
        "range_start": "",
        "range_end": "",
        "notify_on_failure": True,
        "notify_on_success": False,
        "enabled": True,
        "retry_count": 1,
    }
    merged = resolve_update_field_values(existing, sign_at="10:00", enabled=False)
    assert merged["sign_at"] == "10:00"
    assert merged["enabled"] is False
    assert merged["retry_count"] == 1
    assert merged["chats"] == [{"chat_id": 1}]


def test_next_task_group_id():
    assert next_task_group_id("abc", 1) == ""
    assert next_task_group_id("abc", 2) == "abc"
    gid = next_task_group_id("", 3)
    assert len(gid) == 32


def test_apply_account_rename_to_config():
    cfg = {
        "account_name": "old",
        "account_names": ["old", "other", "old"],
    }
    assert apply_account_rename_to_config(cfg, "old", "new") is True
    assert cfg["account_name"] == "new"
    assert cfg["account_names"] == ["new", "other"]
    assert apply_account_rename_to_config(cfg, "missing", "x") is False

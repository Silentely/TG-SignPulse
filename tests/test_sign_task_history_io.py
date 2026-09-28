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
    assert safe_history_key("a/b\\c") == "a%5Fb%5Fc"
    assert safe_history_key(".foo") != safe_history_key("foo")
    assert history_file_path(tmp_path, ".foo").name != history_file_path(tmp_path, "foo").name
    p = history_file_path(tmp_path, "task1", "acc1")
    assert p.name == "acc1__task1.json"
    p2 = history_file_path(tmp_path, "task1")
    assert p2.name == "task1.json"


def test_safe_history_key_is_injective_across_separator():
    """编码必须可逆且单射：(a__b, c) 与 (a, b__c) 不得撞到同一文件名。"""
    left = history_file_path("/tmp/h", "c", "a__b")
    right = history_file_path("/tmp/h", "b__c", "a")
    assert left != right
    assert left.name == "a%5F%5Fb__c.json"
    assert right.name == "a__b%5F%5Fc.json"


def test_safe_history_key_roundtrip():
    """safe_history_key / unsafe_history_key 必须无损互逆。"""
    from backend.services.sign_task_history_io import unsafe_history_key

    # / 与 \ 在编码前已归一为 _（存储名本就不允许含路径分隔符），不参与互逆
    for raw in ("a__b", "a%b", "plain", "%5F", "x_y_z", "%25"):
        assert unsafe_history_key(safe_history_key(raw)) == raw, raw


def test_history_file_owner_roundtrip():
    """从文件名可反查账号宿主；旧版单账号布局返回 None。"""
    from backend.services.sign_task_history_io import history_file_owner

    p = history_file_path("/tmp/h", "task", "a__b")
    assert history_file_owner(p) == "a__b"
    assert history_file_owner(Path("/tmp/h/plain_task.json")) is None


def test_legacy_encoded_history_file_still_resolves(tmp_path: Path):
    """升级前落盘（未转义 _ / %）的文件仍可被解析，历史不凭空消失。"""
    from backend.services.sign_task_history_io import legacy_history_file_path

    legacy = legacy_history_file_path(tmp_path, "task", "a_b")
    legacy.write_text("[]", encoding="utf-8")
    resolved = resolve_existing_history_file(tmp_path, "task", "a_b")
    assert resolved == legacy


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


def test_resolve_task_config_dir_and_cache_patch(tmp_path: Path):
    from backend.services.sign_task_history_io import (
        patch_tasks_cache_last_run,
        resolve_task_config_dir,
    )

    acc_dir = tmp_path / "acc" / "task"
    acc_dir.mkdir(parents=True)
    assert resolve_task_config_dir(tmp_path, "acc", "task") == acc_dir

    legacy = tmp_path / "legacy_task"
    legacy.mkdir()
    assert resolve_task_config_dir(tmp_path, "missing", "legacy_task") == legacy

    cache = [
        {"name": "t1", "account_name": "a1"},
        {"name": "t1", "account_name": "a2", "last_run": {"old": 1}},
    ]
    assert patch_tasks_cache_last_run(
        cache, task_name="t1", account_name="a2", last_run={"new": 2}
    )
    assert cache[1]["last_run"] == {"new": 2}
    assert patch_tasks_cache_last_run(
        cache, task_name="t1", account_name="a2", last_run=None
    )
    assert "last_run" not in cache[1]
    assert patch_tasks_cache_last_run(None, task_name="t", account_name="a", last_run={}) is False


def test_plan_legacy_history_clear():
    from backend.services.sign_task_history_io import plan_legacy_history_clear

    # 无 account 字段：整文件删除
    plan = plan_legacy_history_clear(
        [{"time": "1"}, {"time": "2"}],
        "acc",
    )
    assert plan["remove_file"] is True
    assert plan["removed_entries"] == 2

    # 多账号共享：只删目标账号
    plan2 = plan_legacy_history_clear(
        [
            {"time": "1", "account_name": "acc"},
            {"time": "2", "account_name": "other"},
            "bad",
        ],
        "acc",
    )
    assert plan2["remove_file"] is False
    assert plan2["removed_entries"] == 1
    assert len(plan2["kept"]) == 1
    assert plan2["kept"][0]["account_name"] == "other"

    # 全部属于目标：删文件
    plan3 = plan_legacy_history_clear(
        [{"time": "1", "account_name": "acc"}],
        "acc",
    )
    assert plan3["remove_file"] is True

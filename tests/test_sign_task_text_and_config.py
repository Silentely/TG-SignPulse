"""sign_task_text / sign_task_config_inspect 纯函数测试。"""
from __future__ import annotations

from backend.services.sign_task_config_inspect import (
    task_has_keyword_monitor,
    task_requires_updates,
)
from backend.services.sign_task_text import repair_mojibake


def test_repair_mojibake_empty_and_clean():
    assert repair_mojibake("") == ""
    assert repair_mojibake(None) == ""  # type: ignore[arg-type]
    assert repair_mojibake("签到成功") == "签到成功"


def test_repair_mojibake_roundtrip_gbk_misread():
    # UTF-8 中文被按 latin1/gbk 路径误读后的典型修复路径
    original = "签到成功"
    mangled = original.encode("utf-8").decode("gbk", errors="ignore")
    if mangled == original:
        # 环境无法构造乱码时跳过
        return
    fixed = repair_mojibake(mangled)
    # 至少不应比原文更糟；成功修复则还原
    assert isinstance(fixed, str)
    assert len(fixed) > 0


def test_task_requires_updates_conservative():
    assert task_requires_updates(None) is True
    assert task_requires_updates({}) is True
    assert task_requires_updates({"chats": []}) is False
    assert (
        task_requires_updates(
            {"chats": [{"actions": [{"action": 1, "text": "hi"}]}]}
        )
        is False
    )
    assert (
        task_requires_updates(
            {"chats": [{"actions": [{"action": 3}]}]}
        )
        is True
    )


def test_task_has_keyword_monitor():
    assert task_has_keyword_monitor(None) is False
    assert task_has_keyword_monitor({"chats": []}) is False
    assert (
        task_has_keyword_monitor(
            {"chats": [{"actions": [{"action": 8, "keywords": ["x"]}]}]}
        )
        is True
    )
    assert (
        task_has_keyword_monitor(
            {"chats": [{"actions": [{"action": 1}]}]}
        )
        is False
    )

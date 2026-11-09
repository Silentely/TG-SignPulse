"""
测试会话列表刷新合并 chats_cache.json 与正负合法 chat_id 校验。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.api.routes.sign_tasks_v2 import ChatConfig, validate_chat_id
from backend.services.sign_task_chats import (
    load_chats_cache_file,
    merge_chats_cache,
    save_chats_cache_file,
)


def test_merge_chats_cache_preserves_historical_chats():
    """合并时保留不在最新 dialogs 列表中的历史频道/群组。"""
    existing = [
        {"id": -1001112223334, "title": "Historical Channel", "type": "channel"},
        {"id": 12345, "title": "Old Bot", "type": "bot"},
    ]
    fresh = [
        {"id": 67890, "title": "Fresh Supergroup", "type": "supergroup"},
    ]

    merged = merge_chats_cache(existing, fresh)
    ids = [c["id"] for c in merged]
    assert 67890 in ids
    assert -1001112223334 in ids
    assert 12345 in ids
    assert len(merged) == 3
    # 新拉取会话排在前面
    assert merged[0]["id"] == 67890


def test_merge_chats_cache_fresh_overwrites_existing():
    """相同 id 时，最新拉取的数据覆盖旧缓存。"""
    existing = [
        {"id": -1001234567890, "title": "Old Channel Title", "username": "old_name"},
    ]
    fresh = [
        {"id": -1001234567890, "title": "New Channel Title", "username": "new_name"},
    ]

    merged = merge_chats_cache(existing, fresh)
    assert len(merged) == 1
    assert merged[0]["id"] == -1001234567890
    assert merged[0]["title"] == "New Channel Title"
    assert merged[0]["username"] == "new_name"


def test_merge_chats_cache_string_and_int_id_dedup():
    """支持 int 与 str 表示的 chat_id 去重与统一。"""
    existing = [
        {"id": "-1001234567890", "title": "String ID Channel"},
    ]
    fresh = [
        {"id": -1001234567890, "title": "Int ID Channel"},
    ]

    merged = merge_chats_cache(existing, fresh)
    assert len(merged) == 1
    assert merged[0]["id"] == -1001234567890
    assert merged[0]["title"] == "Int ID Channel"


def test_merge_chats_cache_updated_at_precedence():
    """带有 updated_at 时，更新的时间戳优先，相等或无时间戳时 fresh 胜出。"""
    # 1. fresh updated_at 较新 -> fresh 胜出
    merged = merge_chats_cache(
        [{"id": 1, "title": "Old", "updated_at": 100}],
        [{"id": 1, "title": "New", "updated_at": 200}],
    )
    assert merged[0]["title"] == "New"

    # 2. existing updated_at 较新 -> existing 胜出
    merged = merge_chats_cache(
        [{"id": 1, "title": "Old", "updated_at": 300}],
        [{"id": 1, "title": "New", "updated_at": 200}],
    )
    assert merged[0]["title"] == "Old"

    # 3. existing 有 updated_at，fresh 无 -> fresh 作为最新拉取数据胜出
    merged = merge_chats_cache(
        [{"id": 1, "title": "Old", "updated_at": 300}],
        [{"id": 1, "title": "New"}],
    )
    assert merged[0]["title"] == "New"

    # 4. updated_at 相同 -> fresh 胜出
    merged = merge_chats_cache(
        [{"id": 1, "title": "Old", "updated_at": 100}],
        [{"id": 1, "title": "New", "updated_at": 100}],
    )
    assert merged[0]["title"] == "New"


def test_merge_chats_cache_empty_and_none_handling():
    """测试边界：None、空列表等入参。"""
    fresh = [{"id": 1, "title": "A"}]
    assert merge_chats_cache(None, fresh) == [{"id": 1, "title": "A"}]
    assert merge_chats_cache([], fresh) == [{"id": 1, "title": "A"}]
    assert merge_chats_cache(fresh, []) == [{"id": 1, "title": "A"}]
    assert merge_chats_cache(None, []) == []


def test_save_chats_cache_file_merges_with_existing(tmp_path: Path):
    """save_chats_cache_file 写入前自动与磁盘已有缓存合并。"""
    cache_file = tmp_path / "chats_cache.json"

    # 预先写入包含旧频道的缓存
    initial_chats = [
        {"id": -100999, "title": "Preserved Channel"},
    ]
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(initial_chats, f)

    # 刷新时仅拉取到了新对话
    fresh_chats = [
        {"id": 12345, "title": "Fresh Bot"},
    ]
    assert save_chats_cache_file(cache_file, fresh_chats) is True

    loaded = load_chats_cache_file(cache_file)
    assert loaded is not None
    loaded_ids = [c["id"] for c in loaded]
    assert -100999 in loaded_ids
    assert 12345 in loaded_ids


@pytest.mark.parametrize(
    "valid_id,expected_int",
    [
        (123456, 123456),
        ("123456", 123456),
        (-1001234567890, -1001234567890),
        ("-1001234567890", -1001234567890),
        (-1, -1),
        ("-1", -1),
    ],
)
def test_validate_chat_id_valid(valid_id, expected_int):
    """支持正数（用户/机器人）与负数（超级群/频道）。严禁 gt=0 误拦负数频道。"""
    result = validate_chat_id(valid_id)
    assert result == expected_int


@pytest.mark.parametrize(
    "invalid_id",
    [
        0,
        "0",
        None,
        "",
        "   ",
        "invalid_text",
        True,
        False,
    ],
)
def test_validate_chat_id_invalid(invalid_id):
    """0、None、空字符、非数字字符串和布尔值均被拦截。"""
    with pytest.raises(ValueError):
        validate_chat_id(invalid_id)


def test_chat_config_pydantic_validation():
    """测试 ChatConfig 模型对 chat_id 的校验。"""
    # 合法负数频道 ID
    c1 = ChatConfig(chat_id=-1001234567890, name="Channel")
    assert c1.chat_id == -1001234567890

    # 合法正数用户/机器人 ID
    c2 = ChatConfig(chat_id=123456, name="User")
    assert c2.chat_id == 123456

    # 字符串形式负数频道 ID
    c3 = ChatConfig(chat_id="-1001234567890", name="ChannelStr")
    assert c3.chat_id == -1001234567890

    # 非法 0
    with pytest.raises(ValidationError):
        ChatConfig(chat_id=0, name="Zero")

    # 非法 "0"
    with pytest.raises(ValidationError):
        ChatConfig(chat_id="0", name="ZeroStr")

    # 非法字符串
    with pytest.raises(ValidationError):
        ChatConfig(chat_id="abc", name="NonNumeric")

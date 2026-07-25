"""签到任务配置探测纯函数测试。

覆盖 sign_task_config_inspect 的 task_requires_updates /
task_has_keyword_monitor，正常流程 + 边界条件 + 错误恢复。
"""
from __future__ import annotations

from backend.services.sign_task_config_inspect import (
    task_has_keyword_monitor,
    task_requires_updates,
)

# ─── task_requires_updates ───


def test_requires_updates_none_config_returns_true():
    """None 配置保守返回 True。"""
    assert task_requires_updates(None) is True


def test_requires_updates_non_dict_returns_true():
    assert task_requires_updates("not a dict") is True  # type: ignore[arg-type]
    assert task_requires_updates(123) is True  # type: ignore[arg-type]


def test_requires_updates_no_chats_key_returns_true():
    """缺 chats 键保守返回 True。"""
    assert task_requires_updates({}) is True


def test_requires_updates_chats_not_list_returns_true():
    assert task_requires_updates({"chats": "not list"}) is True


def test_requires_updates_empty_chats_returns_false():
    """空 chats 列表无依赖动作 → False。"""
    assert task_requires_updates({"chats": []}) is False


def test_requires_updates_send_text_only_returns_false():
    """action=1（发送文本）不依赖 update → False。"""
    config = {"chats": [{"actions": [{"action": 1}]}]}
    assert task_requires_updates(config) is False


def test_requires_updates_action_3_returns_true():
    """action=3（按文本点击键盘）依赖 update。"""
    config = {"chats": [{"actions": [{"action": 3}]}]}
    assert task_requires_updates(config) is True


def test_requires_updates_action_8_returns_true():
    """action=8（关键词监听）依赖 update。"""
    config = {"chats": [{"actions": [{"action": 8}]}]}
    assert task_requires_updates(config) is True


def test_requires_updates_mixed_actions_returns_true():
    """只要有一个依赖动作就返回 True。"""
    config = {"chats": [{"actions": [{"action": 1}, {"action": 5}]}]}
    assert task_requires_updates(config) is True


def test_requires_updates_multiple_chats_any_dep_returns_true():
    """多 chat 中任一含依赖动作即 True。"""
    config = {
        "chats": [
            {"actions": [{"action": 1}]},
            {"actions": [{"action": 6}]},
        ]
    }
    assert task_requires_updates(config) is True


def test_requires_updates_chat_not_dict_skipped():
    """非 dict 的 chat 项应被跳过（不报错）。"""
    config = {"chats": ["not dict", {"actions": [{"action": 1}]}]}
    assert task_requires_updates(config) is False


def test_requires_updates_actions_not_list_skipped():
    """非 list 的 actions 应被跳过。"""
    config = {"chats": [{"actions": "not list"}]}
    assert task_requires_updates(config) is False


def test_requires_updates_action_not_dict_skipped():
    """非 dict 的 action 应被跳过。"""
    config = {"chats": [{"actions": ["not dict", 1]}]}
    assert task_requires_updates(config) is False


def test_requires_updates_action_non_int_skipped():
    """action 值非数字应被跳过，不报错。"""
    config = {"chats": [{"actions": [{"action": "abc"}]}]}
    assert task_requires_updates(config) is False


def test_requires_updates_action_none_skipped():
    config = {"chats": [{"actions": [{"action": None}]}]}
    assert task_requires_updates(config) is False


def test_requires_updates_all_response_action_ids():
    """3-8 所有依赖动作都应返回 True。"""
    for action_id in (3, 4, 5, 6, 7, 8):
        config = {"chats": [{"actions": [{"action": action_id}]}]}
        assert task_requires_updates(config) is True, f"action={action_id} 应依赖 update"


def test_requires_updates_action_2_returns_false():
    """action=2（发送骰子）不依赖 update。"""
    config = {"chats": [{"actions": [{"action": 2}]}]}
    assert task_requires_updates(config) is False


# ─── task_has_keyword_monitor ───


def test_has_keyword_monitor_none_config_returns_false():
    assert task_has_keyword_monitor(None) is False


def test_has_keyword_monitor_non_dict_returns_false():
    assert task_has_keyword_monitor("not dict") is False  # type: ignore[arg-type]


def test_has_keyword_monitor_no_chats_returns_false():
    assert task_has_keyword_monitor({}) is False


def test_has_keyword_monitor_empty_chats_returns_false():
    assert task_has_keyword_monitor({"chats": []}) is False


def test_has_keyword_monitor_action_8_returns_true():
    config = {"chats": [{"actions": [{"action": 8}]}]}
    assert task_has_keyword_monitor(config) is True


def test_has_keyword_monitor_other_actions_returns_false():
    config = {"chats": [{"actions": [{"action": 1}, {"action": 3}]}]}
    assert task_has_keyword_monitor(config) is False


def test_has_keyword_monitor_mixed_returns_true():
    """含 action=8 即 True。"""
    config = {"chats": [{"actions": [{"action": 1}, {"action": 8}]}]}
    assert task_has_keyword_monitor(config) is True


def test_has_keyword_monitor_multiple_chats_any():
    config = {
        "chats": [
            {"actions": [{"action": 1}]},
            {"actions": [{"action": 8}]},
        ]
    }
    assert task_has_keyword_monitor(config) is True


def test_has_keyword_monitor_chat_not_dict_skipped():
    config = {"chats": ["not dict", {"actions": [{"action": 8}]}]}
    assert task_has_keyword_monitor(config) is True


def test_has_keyword_monitor_actions_not_list_skipped():
    config = {"chats": [{"actions": "not list"}]}
    assert task_has_keyword_monitor(config) is False


def test_has_keyword_monitor_action_not_dict_skipped():
    config = {"chats": [{"actions": ["not dict"]}]}
    assert task_has_keyword_monitor(config) is False


def test_has_keyword_monitor_action_non_int_skipped():
    config = {"chats": [{"actions": [{"action": "abc"}]}]}
    assert task_has_keyword_monitor(config) is False


def test_has_keyword_monitor_action_none_skipped():
    config = {"chats": [{"actions": [{"action": None}]}]}
    assert task_has_keyword_monitor(config) is False

"""
签到任务配置探测

判断动作是否依赖 update、是否含关键词监听等纯函数。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# 依赖消息回包/按钮/AI 的动作类型（与 SignAction 编号对齐）
_RESPONSE_ACTION_IDS = frozenset({3, 4, 5, 6, 7, 8})
_KEYWORD_MONITOR_ACTION_ID = 8


def task_requires_updates(task_config: Optional[Dict[str, Any]]) -> bool:
    """
    任务是否依赖 update handlers。

    无法解析配置时保守返回 True，避免漏挂监听。
    """
    if not isinstance(task_config, dict):
        return True
    chats = task_config.get("chats")
    if not isinstance(chats, list):
        return True
    for chat in chats:
        if not isinstance(chat, dict):
            continue
        actions = chat.get("actions")
        if not isinstance(actions, list):
            continue
        for action in actions:
            if not isinstance(action, dict):
                continue
            try:
                action_id = int(action.get("action"))
            except (TypeError, ValueError):
                continue
            if action_id in _RESPONSE_ACTION_IDS:
                return True
    return False


def task_has_keyword_monitor(task_config: Optional[Dict[str, Any]]) -> bool:
    """任务动作中是否包含关键词监听（action=8）。"""
    if not isinstance(task_config, dict):
        return False
    for chat in task_config.get("chats") or []:
        if not isinstance(chat, dict):
            continue
        for action in chat.get("actions") or []:
            if not isinstance(action, dict):
                continue
            try:
                if int(action.get("action")) == _KEYWORD_MONITOR_ACTION_ID:
                    return True
            except (TypeError, ValueError):
                continue
    return False

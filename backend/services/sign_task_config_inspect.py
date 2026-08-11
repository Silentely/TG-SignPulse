"""
签到任务配置探测

判断动作是否依赖 update、是否含关键词监听等纯函数。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# 依赖消息回包/按钮/AI 的动作类型（与 SignAction 编号对齐）
_RESPONSE_ACTION_IDS = frozenset({3, 4, 5, 6, 7, 8})
_KEYWORD_MONITOR_ACTION_ID = 8


def _iter_chat_actions(task_config: Optional[Dict[str, Any]]):
    """遍历配置中所有 (chat, action) 对；跳过非法结构，供探测函数复用。"""
    if not isinstance(task_config, dict):
        return
    for chat in task_config.get("chats") or []:
        if not isinstance(chat, dict):
            continue
        for action in chat.get("actions") or []:
            if isinstance(action, dict):
                yield action


def task_requires_updates(task_config: Optional[Dict[str, Any]]) -> bool:
    """
    任务是否依赖 update handlers。

    无法解析配置（非 dict 或 chats 非 list）时保守返回 True，避免漏挂监听。
    """
    if not isinstance(task_config, dict):
        return True
    if not isinstance(task_config.get("chats"), list):
        return True
    for action in _iter_chat_actions(task_config):
        try:
            action_id = int(action.get("action"))
        except (TypeError, ValueError):
            continue
        if action_id in _RESPONSE_ACTION_IDS:
            return True
    return False


def task_has_keyword_monitor(task_config: Optional[Dict[str, Any]]) -> bool:
    """任务动作中是否包含关键词监听（action=8）。"""
    for action in _iter_chat_actions(task_config):
        try:
            if int(action.get("action")) == _KEYWORD_MONITOR_ACTION_ID:
                return True
        except (TypeError, ValueError):
            continue
    return False

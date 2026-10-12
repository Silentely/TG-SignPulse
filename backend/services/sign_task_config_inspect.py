"""
签到任务配置探测

判断动作是否依赖 update、是否含关键词监听等纯函数。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# 依赖消息回包/按钮/AI 的动作类型（与 SignAction 编号对齐）
_RESPONSE_ACTION_IDS = frozenset({3, 4, 5, 6, 7, 8})
_KEYWORD_MONITOR_ACTION_ID = 8


def _iter_graph_items(graph_dict: Any, visited: Optional[set] = None):
    """递归遍历执行图节点，使用 visited 防止环形引用导致的 RecursionError。"""
    if not isinstance(graph_dict, dict):
        return
    if visited is None:
        visited = set()
    graph_id = id(graph_dict)
    if graph_id in visited:
        return
    visited.add(graph_id)

    nodes = graph_dict.get("nodes")
    if isinstance(nodes, dict):
        node_iterable = nodes.values()
    elif isinstance(nodes, (list, tuple)):
        node_iterable = nodes
    else:
        node_iterable = []

    for node in node_iterable:
        if not isinstance(node, dict):
            continue
        yield node
        subflow = node.get("subflow_graph")
        if isinstance(subflow, dict):
            yield from _iter_graph_items(subflow, visited)
        branches = node.get("branches")
        if isinstance(branches, (list, tuple)):
            for b in branches:
                if isinstance(b, dict):
                    yield from _iter_graph_items(b, visited)


def _iter_chat_actions(task_config: Optional[Dict[str, Any]]):
    """遍历 actions、workflow steps 与 flow_graph 的统一动作/节点描述。"""
    if not isinstance(task_config, dict):
        return
    chats = task_config.get("chats")
    if not isinstance(chats, (list, tuple)):
        return
    visited: set = set()
    for chat in chats:
        if not isinstance(chat, dict):
            continue
        actions = chat.get("actions")
        if isinstance(actions, (list, tuple)):
            for action in actions:
                if isinstance(action, dict) or hasattr(action, "action"):
                    yield action

        steps = chat.get("steps")
        if isinstance(steps, (list, tuple)):
            for step in steps:
                if not isinstance(step, dict):
                    continue
                config = step.get("config")
                config = config if isinstance(config, dict) else {}
                item = {
                    "action": step.get("action_type"),
                    "mode": config.get("mode"),
                    "node_type": step.get("node_type"),
                }
                yield item
                subflow = step.get("subflow_graph")
                if isinstance(subflow, dict):
                    yield from _iter_graph_items(subflow, visited)
                branches = step.get("branches")
                if isinstance(branches, (list, tuple)):
                    for b in branches:
                        if isinstance(b, dict):
                            yield from _iter_graph_items(b, visited)

        flow_graph = chat.get("flow_graph")
        if isinstance(flow_graph, dict):
            yield from _iter_graph_items(flow_graph, visited)


def task_requires_updates(task_config: Optional[Dict[str, Any]]) -> bool:
    """
    任务是否依赖 update handlers。

    无法解析配置（非 dict 或 chats 非 list）时保守返回 True，避免漏挂监听。
    """
    if not isinstance(task_config, dict):
        return True
    if not isinstance(task_config.get("chats"), list):
        return True
    for item in _iter_chat_actions(task_config):
        node_type = str(
            (item.get("node_type") if isinstance(item, dict) else getattr(item, "node_type", None))
            or (item.get("type") if isinstance(item, dict) else getattr(item, "type", None))
            or ""
        ).strip().lower()
        if node_type == "wait_event":
            return True

        raw_act = (
            item.get("action")
            if isinstance(item, dict) and "action" in item
            else (item.get("action_type") if isinstance(item, dict) else getattr(item, "action", None))
        )
        if raw_act is None and hasattr(item, "action_type"):
            raw_act = getattr(item, "action_type", None)

        try:
            if isinstance(raw_act, str):
                from tg_signer.config import SupportAction

                try:
                    action_id = int(SupportAction[raw_act].value)
                except KeyError:
                    action_id = int(raw_act)
            else:
                action_id = int(raw_act)
        except (TypeError, ValueError):
            continue
        if action_id in _RESPONSE_ACTION_IDS:
            return True
        if action_id == 99:
            mode = (
                item.get("mode")
                if isinstance(item, dict)
                else getattr(item, "mode", "reactive")
            )
            if (mode or "reactive") == "reactive":
                return True
    return False


def task_has_keyword_monitor(task_config: Optional[Dict[str, Any]]) -> bool:
    """任务动作中是否包含关键词监听（action=8）。"""
    for action in _iter_chat_actions(task_config):
        raw_act = (
            action.get("action")
            if isinstance(action, dict) and "action" in action
            else (action.get("action_type") if isinstance(action, dict) else getattr(action, "action", None))
        )
        try:
            if isinstance(raw_act, str):
                from tg_signer.config import SupportAction

                try:
                    act_int = int(SupportAction[raw_act].value)
                except KeyError:
                    act_int = int(raw_act)
            else:
                act_int = int(raw_act)
            if act_int == _KEYWORD_MONITOR_ACTION_ID:
                return True
        except (TypeError, ValueError):
            continue
    return False

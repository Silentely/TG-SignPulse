"""
签到历史查询装配纯函数

从 SignTaskService 多处 get_*_history_logs 路径抽离：条目格式化、日期过滤与排序截断。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional

from backend.services.sign_task_history_format import build_history_list_item


RepairFn = Callable[[str], str]
ExtractTargetFn = Callable[[List[Any]], str]


def collect_formatted_history_items(
    raw_entries: Iterable[Any],
    *,
    task_name: str,
    account_name: str,
    repair: RepairFn,
    extract_last_target: ExtractTargetFn,
    date_prefix: str = "",
    prefer_entry_account: bool = False,
) -> List[Dict[str, Any]]:
    """将原始 history 条目转为列表展示结构，可按时间前缀过滤。

    prefer_entry_account=True 时优先使用条目内 account_name（多账号共享历史文件）。
    """
    items: List[Dict[str, Any]] = []
    prefix = str(date_prefix or "").strip()
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        if prefix:
            timestamp = str(item.get("time") or "")
            if not timestamp.startswith(prefix):
                continue
        entry_account = account_name
        if prefer_entry_account:
            entry_account = str(item.get("account_name") or account_name)
        items.append(
            build_history_list_item(
                item,
                task_name=task_name,
                account_name=entry_account,
                repair=repair,
                extract_last_target=extract_last_target,
            )
        )
    return items


def sort_history_items_desc(
    items: List[Dict[str, Any]],
    *,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """按 time 倒序排序，可选截断。"""
    sorted_items = sorted(
        items, key=lambda x: str(x.get("time") or ""), reverse=True
    )
    if limit is None:
        return sorted_items
    try:
        n = int(limit)
    except (TypeError, ValueError):
        return sorted_items
    if n < 0:
        return sorted_items
    return sorted_items[:n]


def find_history_item_by_time(
    raw_entries: Iterable[Any],
    *,
    target_time: str,
    task_name: str,
    account_name: str,
    repair: RepairFn,
    extract_last_target: ExtractTargetFn,
) -> Optional[Dict[str, Any]]:
    """按精确时间匹配一条历史并格式化；未命中返回 None。"""
    want = str(target_time or "").strip()
    if not want:
        return None
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        if str(item.get("time") or "") != want:
            continue
        return build_history_list_item(
            item,
            task_name=task_name,
            account_name=account_name,
            repair=repair,
            extract_last_target=extract_last_target,
        )
    return None

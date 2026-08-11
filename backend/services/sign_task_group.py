"""
签到任务聚合与关联查找纯函数

从 SignTaskService._aggregate_tasks / _find_related_task_infos 抽离，
normalize 账号名由调用方注入以复用校验规则。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence

NormalizeFn = Callable[[Optional[Sequence[Any]], Optional[str]], List[str]]


def first_real_account(names: Sequence[str], fallback: str = "") -> str:
    """跳过通配符，返回第一个真实账号名。"""
    for n in names:
        if n and n != "*":
            return str(n)
    return fallback if fallback and fallback != "*" else ""


def select_latest_last_run(
    current: Optional[Dict[str, Any]],
    candidate: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """按 time 字符串比较，返回较新的 last_run。"""
    if not candidate:
        return current
    if not current:
        return candidate
    current_time = str(current.get("time") or "")
    candidate_time = str(candidate.get("time") or "")
    return candidate if candidate_time > current_time else current


def task_group_key(task: Dict[str, Any]) -> str:
    """聚合键：优先 task_group_id，否则 single:account:name。"""
    group_id = str(task.get("task_group_id") or "").strip()
    if group_id:
        return f"group:{group_id}"
    account_name = str(task.get("account_name") or "").strip()
    task_name = str(task.get("name") or "").strip()
    return f"single:{account_name}:{task_name}"


def aggregate_tasks(
    tasks: List[Dict[str, Any]],
    *,
    normalize_account_names: NormalizeFn,
) -> List[Dict[str, Any]]:
    """按 group key 合并多账号同名任务。"""
    grouped: Dict[str, Dict[str, Any]] = {}

    for task in tasks:
        key = task_group_key(task)
        existing = grouped.get(key)
        if existing is None:
            merged = {
                **task,
                "account_names": normalize_account_names(
                    task.get("account_names"),  # type: ignore[arg-type]
                    task.get("account_name") if isinstance(task.get("account_name"), str) else None,
                ),
            }
            if not merged.get("account_name") or merged.get("account_name") == "*":
                merged["account_name"] = first_real_account(
                    merged["account_names"],
                    str(task.get("account_name") or ""),
                )
            grouped[key] = merged
            continue

        merged_accounts = normalize_account_names(
            [
                *existing.get("account_names", []),
                *list(task.get("account_names") or []),
            ],
            (
                str(existing.get("account_name") or task.get("account_name") or "")
                or None
            ),
        )
        latest_last_run = select_latest_last_run(
            existing.get("last_run") if isinstance(existing.get("last_run"), dict) else None,
            task.get("last_run") if isinstance(task.get("last_run"), dict) else None,
        )
        latest_last_run_account_name = str(existing.get("last_run_account_name") or "")
        if latest_last_run is task.get("last_run"):
            latest_last_run_account_name = str(task.get("account_name") or "")

        existing["account_names"] = merged_accounts
        existing["account_name"] = first_real_account(
            merged_accounts,
            str(existing.get("account_name") or task.get("account_name") or ""),
        )
        existing["last_run"] = latest_last_run
        existing["last_run_account_name"] = latest_last_run_account_name

    return sorted(
        grouped.values(),
        key=lambda item: (
            ",".join(item.get("account_names", [])),
            str(item.get("name") or ""),
        ),
    )


def filter_related_task_infos(
    raw_tasks: List[Dict[str, Any]],
    task_name: str,
    account_name: Optional[str] = None,
    *,
    normalize_account_names: NormalizeFn,
) -> List[Dict[str, Any]]:
    """
    从已加载的 raw 任务列表中筛选与 task_name 关联的条目。

    逻辑与 SignTaskService._find_related_task_infos 一致（不含 list_tasks IO）。
    """
    if account_name:
        current = next(
            (
                task
                for task in raw_tasks
                if task.get("name") == task_name
                and task.get("account_name") == account_name
            ),
            None,
        )
        if current is None:
            return []

        group_id = str(current.get("task_group_id") or "").strip()
        if group_id:
            return [
                task
                for task in raw_tasks
                if task.get("name") == task_name
                and str(task.get("task_group_id") or "").strip() == group_id
            ]

        current_accounts = normalize_account_names(
            current.get("account_names"),  # type: ignore[arg-type]
            current.get("account_name") if isinstance(current.get("account_name"), str) else None,
        )
        if len(current_accounts) > 1:
            return [
                task
                for task in raw_tasks
                if task.get("name") == task_name
                and normalize_account_names(
                    task.get("account_names"),  # type: ignore[arg-type]
                    task.get("account_name") if isinstance(task.get("account_name"), str) else None,
                )
                == current_accounts
            ]
        return [current]

    exact_matches = [task for task in raw_tasks if task.get("name") == task_name]
    if not exact_matches:
        return []
    if len(exact_matches) == 1:
        return exact_matches

    grouped = aggregate_tasks(
        exact_matches, normalize_account_names=normalize_account_names
    )
    if len(grouped) == 1:
        target_key = task_group_key(grouped[0])
        return [task for task in exact_matches if task_group_key(task) == target_key]
    return [exact_matches[0]]

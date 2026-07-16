"""
签到历史文件 IO 纯函数

路径安全化、JSON 加载与条目过滤，供 SignTaskService 复用。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def safe_history_key(name: str) -> str:
    return str(name or "").replace("/", "_").replace("\\", "_")


def history_file_path(
    run_history_dir: Path, task_name: str, account_name: str = ""
) -> Path:
    if account_name:
        safe_account = safe_history_key(account_name)
        safe_task = safe_history_key(task_name)
        return run_history_dir / f"{safe_account}__{safe_task}.json"
    return run_history_dir / f"{safe_history_key(task_name)}.json"


def load_history_payload_from_file(history_file: Path) -> List[Any]:
    try:
        with open(history_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def resolve_existing_history_file(
    run_history_dir: Path, task_name: str, account_name: str = ""
) -> Optional[Path]:
    history_file = history_file_path(run_history_dir, task_name, account_name)
    legacy_file = run_history_dir / f"{safe_history_key(task_name)}.json"
    if history_file.exists():
        return history_file
    if legacy_file.exists():
        return legacy_file
    return None


def filter_history_entries(
    data_list: List[Any],
    *,
    account_name: str = "",
) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for item in data_list:
        if not isinstance(item, dict):
            continue
        if account_name:
            item_account = item.get("account_name")
            if item_account and item_account != account_name:
                continue
        entries.append(item)
    entries.sort(key=lambda x: str(x.get("time") or ""), reverse=True)
    return entries


def load_history_entries(
    run_history_dir: Path,
    task_name: str,
    account_name: str = "",
) -> List[Dict[str, Any]]:
    history_file = history_file_path(run_history_dir, task_name, account_name)
    legacy_file = run_history_dir / f"{safe_history_key(task_name)}.json"

    if not history_file.exists():
        if account_name and legacy_file.exists():
            history_file = legacy_file
        elif not account_name and legacy_file.exists():
            history_file = legacy_file
        else:
            return []

    payload = load_history_payload_from_file(history_file)
    return filter_history_entries(payload, account_name=account_name)


def count_history_entries(data: Any) -> int:
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        return 1
    return 0


def clamp_max_age_days(max_age_days: int, *, default: int = 3, minimum: int = 1) -> int:
    try:
        value = int(max_age_days)
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def cleanup_old_history_files(run_history_dir: Path, *, max_age_days: int = 3) -> int:
    """删除过期历史文件，返回删除数量。"""
    from datetime import datetime, timedelta

    if not run_history_dir.exists():
        return 0
    days = clamp_max_age_days(max_age_days)
    limit = datetime.now() - timedelta(days=days)
    removed = 0
    for log_file in run_history_dir.glob("*.json"):
        try:
            if log_file.stat().st_mtime < limit.timestamp():
                log_file.unlink()
                removed += 1
        except Exception:
            continue
    return removed

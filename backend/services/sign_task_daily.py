"""签到任务「当日已成功」判定。

执行器的非手动去重门与调度器的启动补跑共用同一口径，避免两处实现漂移。
判定只读取项目已有的执行记录（任务配置的 last_run 与历史文件），不新增状态。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional


def parse_run_timestamp(
    raw_time: Any, *, now: Optional[datetime] = None
) -> Optional[datetime]:
    """解析执行记录中的时间戳；无法解析时返回 None。"""
    if not raw_time:
        return None
    try:
        ran_at = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if ran_at.tzinfo is not None:
        # 统一到与“今天”相同的时区，避免 UTC 记录在本地跨日时误判
        target_tz = now.tzinfo if now is not None and now.tzinfo is not None else None
        ran_at = (
            ran_at.astimezone(target_tz)
            if target_tz is not None
            else ran_at.astimezone()
        )
    return ran_at


def last_run_succeeded_today(last_run: Any, *, now: Optional[datetime] = None) -> bool:
    """最近一次执行记录是否为当天成功。"""
    if not isinstance(last_run, dict) or last_run.get("success") is not True:
        return False
    reference = now or datetime.now()
    ran_at = parse_run_timestamp(
        last_run.get("time") or last_run.get("created_at"), now=reference
    )
    return ran_at is not None and ran_at.date() == reference.date()


def history_succeeded_today(
    svc: Any,
    task_name: str,
    account_name: str,
    *,
    now: Optional[datetime] = None,
) -> bool:
    """历史记录中当天是否已有成功条目（覆盖“成功后又失败重试”的情况）。"""
    getter = getattr(svc, "get_task_history", None)
    if not callable(getter):
        return False
    try:
        entries = getter(task_name, account_name=account_name, limit=200)
    except Exception:
        return False
    if not isinstance(entries, (list, tuple)):
        return False
    reference = now or datetime.now()
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("success") is not True:
            continue
        ran_at = parse_run_timestamp(
            entry.get("time") or entry.get("created_at"), now=reference
        )
        if ran_at is not None and ran_at.date() == reference.date():
            return True
    return False


def task_succeeded_today(
    svc: Any,
    task_config: Optional[dict],
    task_name: str,
    account_name: str,
    *,
    now: Optional[datetime] = None,
) -> bool:
    """账号当天是否已有成功执行记录（last_run 或历史文件任一命中）。"""
    last_run = (task_config or {}).get("last_run")
    if last_run_succeeded_today(last_run, now=now):
        return True
    return history_succeeded_today(svc, task_name, account_name, now=now)

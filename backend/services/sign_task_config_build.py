"""
签到配置字典构造与账号引用改名

从 SignTaskService create/update/rename 路径抽离的纯函数。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping, Optional


def build_sign_task_config(
    *,
    account_name: str,
    account_names: List[str],
    task_group_id: str = "",
    sign_at: str,
    random_seconds: int = 0,
    sign_interval: int = 1,
    chats: List[Dict[str, Any]],
    execution_mode: str = "fixed",
    range_start: str = "",
    range_end: str = "",
    notify_on_failure: bool = True,
    notify_on_success: bool = True,
    retry_count: int = 3,
    enabled: bool = True,
    last_run: Any = None,
    version: int = 4,
) -> Dict[str, Any]:
    """构造写入 config.json 的标准任务配置。"""
    config: Dict[str, Any] = {
        "_version": version,
        "task_group_id": task_group_id or "",
        "account_name": account_name,
        "account_names": list(account_names),
        "sign_at": sign_at,
        "random_seconds": random_seconds,
        "sign_interval": sign_interval,
        "chats": chats,
        "execution_mode": execution_mode,
        "range_start": range_start,
        "range_end": range_end,
        "notify_on_failure": notify_on_failure,
        "notify_on_success": notify_on_success,
        "retry_count": retry_count,
        "enabled": enabled,
    }
    if last_run is not None:
        config["last_run"] = last_run
    return config


def resolve_update_field_values(
    existing: Mapping[str, Any],
    *,
    sign_at: Optional[str] = None,
    chats: Optional[List[Dict[str, Any]]] = None,
    random_seconds: Optional[int] = None,
    sign_interval: Optional[int] = None,
    execution_mode: Optional[str] = None,
    range_start: Optional[str] = None,
    range_end: Optional[str] = None,
    notify_on_failure: Optional[bool] = None,
    notify_on_success: Optional[bool] = None,
    retry_count: Optional[int] = None,
    enabled: Optional[bool] = None,
) -> Dict[str, Any]:
    """合并更新入参与既有配置，返回下一版字段值。"""
    try:
        prev_random = int(existing["random_seconds"])
    except (KeyError, TypeError, ValueError):
        prev_random = 0
    try:
        prev_interval = int(existing["sign_interval"])
    except (KeyError, TypeError, ValueError):
        prev_interval = 1
    try:
        prev_retry = int(existing.get("retry_count", 3))
    except (TypeError, ValueError):
        prev_retry = 3

    return {
        "sign_at": sign_at if sign_at is not None else str(existing.get("sign_at") or "08:00"),
        "random_seconds": random_seconds if random_seconds is not None else prev_random,
        "sign_interval": sign_interval if sign_interval is not None else prev_interval,
        "chats": chats if chats is not None else list(existing.get("chats") or []),
        "execution_mode": (
            execution_mode
            if execution_mode is not None
            else str(existing.get("execution_mode", "fixed"))
        ),
        "range_start": (
            range_start if range_start is not None else str(existing.get("range_start", ""))
        ),
        "range_end": range_end if range_end is not None else str(existing.get("range_end", "")),
        "notify_on_failure": (
            notify_on_failure
            if notify_on_failure is not None
            else bool(existing.get("notify_on_failure", True))
        ),
        "notify_on_success": (
            notify_on_success
            if notify_on_success is not None
            else bool(existing.get("notify_on_success", True))
        ),
        "enabled": enabled if enabled is not None else bool(existing.get("enabled", True)),
        "retry_count": retry_count if retry_count is not None else prev_retry,
    }


def next_task_group_id(existing_group_id: str, account_count: int) -> str:
    """多账号保留或生成 group id；单账号清空。"""
    import uuid

    current = str(existing_group_id or "").strip()
    if account_count > 1:
        return current or uuid.uuid4().hex
    return ""


def apply_account_rename_to_config(
    config: MutableMapping[str, Any],
    old_account_name: str,
    new_account_name: str,
) -> bool:
    """
    就地改写 config 中的账号引用。
    返回是否有变更。
    """
    if not isinstance(config, MutableMapping):
        return False
    changed = False
    if str(config.get("account_name") or "").strip() == old_account_name:
        config["account_name"] = new_account_name
        changed = True

    account_names = config.get("account_names")
    if isinstance(account_names, list):
        next_names: List[str] = []
        for item in account_names:
            current_name = str(item or "").strip()
            if not current_name:
                continue
            if current_name == old_account_name:
                current_name = new_account_name
            if current_name not in next_names:
                next_names.append(current_name)
        if next_names != account_names:
            config["account_names"] = next_names
            changed = True
    return changed

"""
签到配置字典构造与账号引用改名

从 SignTaskService create/update/rename 路径抽离的纯函数。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping, Optional

# 共享默认值：build_sign_task_config 与 resolve_update_field_values 统一引用，
# 避免两处默认值漂移。
_DEFAULT_TASK_FIELDS: Dict[str, Any] = {
    "random_seconds": 0,
    "jitter_seconds": 0,
    "sign_interval": 1,
    "execution_mode": "fixed",
    "range_start": "",
    "range_end": "",
    "notify_on_failure": True,
    "notify_on_success": True,
    "retry_count": 3,
    "enabled": True,
    "sign_at": "08:00",
    "chats": [],
    "tags": [],
    "adaptive_schedule_enabled": False,
    "adaptive_schedule_patterns": [],
    "adaptive_schedule_padding_seconds": 30,
}

MAX_TASK_TAGS = 20
MAX_TASK_TAG_LENGTH = 50
MAX_TASK_TAGS_TOTAL_LENGTH = 500


def normalize_task_tags(tags: Optional[List[str]]) -> List[str]:
    """清洗并限制任务标签，统一保护 API、服务和文件写入路径。"""
    if tags is None:
        return []
    if len(tags) > MAX_TASK_TAGS:
        raise ValueError(f"任务标签最多允许 {MAX_TASK_TAGS} 个")
    result: List[str] = []
    total_length = 0
    for raw in tags:
        value = str(raw or "").strip()
        if not value:
            continue
        if len(value) > MAX_TASK_TAG_LENGTH:
            raise ValueError(f"单个任务标签最多允许 {MAX_TASK_TAG_LENGTH} 个字符")
        if value not in result:
            result.append(value)
            total_length += len(value)
    if total_length > MAX_TASK_TAGS_TOTAL_LENGTH:
        raise ValueError(f"任务标签总长度最多允许 {MAX_TASK_TAGS_TOTAL_LENGTH} 个字符")
    return result


def build_sign_task_config(
    *,
    account_name: str,
    account_names: List[str],
    task_group_id: str = "",
    sign_at: str = _DEFAULT_TASK_FIELDS["sign_at"],
    random_seconds: int = _DEFAULT_TASK_FIELDS["random_seconds"],
    jitter_seconds: int = _DEFAULT_TASK_FIELDS["jitter_seconds"],
    sign_interval: int = _DEFAULT_TASK_FIELDS["sign_interval"],
    chats: List[Dict[str, Any]] = _DEFAULT_TASK_FIELDS["chats"],
    execution_mode: str = _DEFAULT_TASK_FIELDS["execution_mode"],
    range_start: str = _DEFAULT_TASK_FIELDS["range_start"],
    range_end: str = _DEFAULT_TASK_FIELDS["range_end"],
    notify_on_failure: bool = _DEFAULT_TASK_FIELDS["notify_on_failure"],
    notify_on_success: bool = _DEFAULT_TASK_FIELDS["notify_on_success"],
    retry_count: int = _DEFAULT_TASK_FIELDS["retry_count"],
    enabled: bool = _DEFAULT_TASK_FIELDS["enabled"],
    tags: Optional[List[str]] = None,
    adaptive_schedule_enabled: bool = _DEFAULT_TASK_FIELDS["adaptive_schedule_enabled"],
    adaptive_schedule_patterns: Optional[List[str]] = None,
    adaptive_schedule_padding_seconds: int = _DEFAULT_TASK_FIELDS["adaptive_schedule_padding_seconds"],
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
        "jitter_seconds": jitter_seconds,
        "sign_interval": sign_interval,
        "chats": chats,
        "execution_mode": execution_mode,
        "range_start": range_start,
        "range_end": range_end,
        "notify_on_failure": notify_on_failure,
        "notify_on_success": notify_on_success,
        "retry_count": retry_count,
        "enabled": enabled,
        "tags": normalize_task_tags(tags),
        "adaptive_schedule_enabled": bool(adaptive_schedule_enabled),
        "adaptive_schedule_patterns": list(adaptive_schedule_patterns or []),
        "adaptive_schedule_padding_seconds": int(adaptive_schedule_padding_seconds),
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
    jitter_seconds: Optional[int] = None,
    sign_interval: Optional[int] = None,
    execution_mode: Optional[str] = None,
    range_start: Optional[str] = None,
    range_end: Optional[str] = None,
    notify_on_failure: Optional[bool] = None,
    notify_on_success: Optional[bool] = None,
    retry_count: Optional[int] = None,
    enabled: Optional[bool] = None,
    tags: Optional[List[str]] = None,
    adaptive_schedule_enabled: Optional[bool] = None,
    adaptive_schedule_patterns: Optional[List[str]] = None,
    adaptive_schedule_padding_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    """合并更新入参与既有配置，返回下一版字段值。"""
    return {
        "sign_at": sign_at if sign_at is not None else str(existing.get("sign_at") or _DEFAULT_TASK_FIELDS["sign_at"]),
        "random_seconds": random_seconds if random_seconds is not None else int(existing.get("random_seconds", _DEFAULT_TASK_FIELDS["random_seconds"])),
        "jitter_seconds": int(jitter_seconds) if jitter_seconds is not None else int(existing.get("jitter_seconds", _DEFAULT_TASK_FIELDS["jitter_seconds"]) or 0),
        "sign_interval": sign_interval if sign_interval is not None else int(existing.get("sign_interval", _DEFAULT_TASK_FIELDS["sign_interval"])),
        "chats": chats if chats is not None else list(existing.get("chats") or _DEFAULT_TASK_FIELDS["chats"]),
        "execution_mode": execution_mode if execution_mode is not None else str(existing.get("execution_mode", _DEFAULT_TASK_FIELDS["execution_mode"])),
        "range_start": range_start if range_start is not None else str(existing.get("range_start", _DEFAULT_TASK_FIELDS["range_start"])),
        "range_end": range_end if range_end is not None else str(existing.get("range_end", _DEFAULT_TASK_FIELDS["range_end"])),
        "notify_on_failure": notify_on_failure if notify_on_failure is not None else bool(existing.get("notify_on_failure", _DEFAULT_TASK_FIELDS["notify_on_failure"])),
        "notify_on_success": notify_on_success if notify_on_success is not None else bool(existing.get("notify_on_success", _DEFAULT_TASK_FIELDS["notify_on_success"])),
        "enabled": enabled if enabled is not None else bool(existing.get("enabled", _DEFAULT_TASK_FIELDS["enabled"])),
        "retry_count": retry_count if retry_count is not None else int(existing.get("retry_count", _DEFAULT_TASK_FIELDS["retry_count"])),
        "tags": normalize_task_tags(
            tags if tags is not None else existing.get("tags") or _DEFAULT_TASK_FIELDS["tags"]
        ),
        "adaptive_schedule_enabled": bool(existing.get("adaptive_schedule_enabled", _DEFAULT_TASK_FIELDS["adaptive_schedule_enabled"])) if adaptive_schedule_enabled is None else bool(adaptive_schedule_enabled),
        "adaptive_schedule_patterns": list(existing.get("adaptive_schedule_patterns", _DEFAULT_TASK_FIELDS["adaptive_schedule_patterns"]) or []) if adaptive_schedule_patterns is None else list(adaptive_schedule_patterns),
        "adaptive_schedule_padding_seconds": int(existing.get("adaptive_schedule_padding_seconds", _DEFAULT_TASK_FIELDS["adaptive_schedule_padding_seconds"])) if adaptive_schedule_padding_seconds is None else int(adaptive_schedule_padding_seconds),
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


def resolve_schedule_plan(
    execution_mode: str,
    *,
    sign_at: str = "08:00",
    range_start: str = "",
) -> Dict[str, Any]:
    """根据执行模式决定是否调度及 cron 触发表达式。"""
    mode = str(execution_mode or "fixed")
    should_schedule = mode != "listen"
    if mode == "range":
        trigger = str(range_start or sign_at or "08:00")
    else:
        trigger = str(sign_at or "08:00")
    return {
        "should_schedule": should_schedule,
        "trigger_cron": trigger,
        "execution_mode": mode,
    }


def removed_accounts_diff(
    existing_accounts: List[str],
    target_accounts: List[str],
) -> List[str]:
    """计算更新后需要移除的账号列表（保持 existing 顺序）。"""
    target_set = set(target_accounts)
    return [a for a in existing_accounts if a not in target_set]


def last_run_map_from_related(
    related_tasks: List[Mapping[str, Any]],
) -> Dict[str, Any]:
    """从 related task infos 提取 account_name -> last_run。"""
    out: Dict[str, Any] = {}
    for task in related_tasks:
        if not isinstance(task, Mapping):
            continue
        acc = str(task.get("account_name") or "")
        out[acc] = task.get("last_run")
    return out

def create_task_group_id(account_count: int) -> str:
    """新建任务：多账号生成 group id，单账号为空。"""
    import uuid

    return uuid.uuid4().hex if account_count > 1 else ""


def pick_task_write_response(
    related: List[Dict[str, Any]],
    *,
    target_accounts: List[str],
    aggregate_fn,
    get_task_fn,
    not_found_message: str,
) -> Dict[str, Any]:
    """
    create/update 写盘后的统一响应：多账号聚合，否则取首账号任务。
    aggregate_fn(related) -> list; get_task_fn(name, account) -> dict|None
    此处 name 由 related[0] 或调用方在 get_task_fn 闭包中绑定。
    """
    if len(target_accounts) > 1:
        grouped = aggregate_fn(related)
        if grouped:
            return grouped[0]
    if not target_accounts:
        raise ValueError(not_found_message)
    task = get_task_fn(target_accounts[0])
    if task is None:
        raise ValueError(not_found_message)
    return task

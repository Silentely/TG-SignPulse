"""
签到历史文件 IO 纯函数

路径安全化、JSON 加载与条目过滤，供 SignTaskService 复用。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.utils.atomic_io import read_json_safe

_logger = logging.getLogger("backend.sign_task_history_io")


def safe_history_key(name: str) -> str:
    """把账号/任务名编码为文件系统安全且**可逆**的键。

    `_` 是 history 文件名里 account 与 task 的分隔符，若直接把名称中的 `_`
    也留在键中，`(a__b, c)` 与 `(a, b__c)` 会撞到同一个文件名，导致清账号
    `a` 的历史时误删 `a__b` 的数据。故对 `_` 与 `%` 做百分号编码：
    `%` → `%25`，`_` → `%5F`，保证编码结果不含裸 `_`/`%`，可无损还原。
    """
    cleaned = (
        str(name or "")
        .strip()
        .replace(chr(0), "")
        .replace("/", "_")
        .replace("\\", "_")
    )
    if cleaned in {".", ".."}:
        return "default"
    # 先编码 % 再编码 _，避免二次编码把 %25 的 % 又变成 %2525
    encoded = cleaned.replace("%", "%25").replace("_", "%5F")
    return encoded or "default"


def unsafe_history_key(name: str) -> str:
    """safe_history_key 的逆运算：把编码键还原为原始名称。

    仅供按文件名反查账号/任务名时使用；普通业务路径应直接持有原始名称。
    """
    text = str(name or "")
    out: List[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "%" and i + 3 <= len(text):
            code = text[i + 1 : i + 3]
            if code == "25":
                out.append("%")
                i += 3
                continue
            if code == "5F":
                out.append("_")
                i += 3
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _legacy_history_key(name: str) -> str:
    """旧版编码：不做 _ / % 转义（保留用于读取升级前落盘的历史文件）。"""
    cleaned = (
        str(name or "")
        .strip()
        .replace(chr(0), "")
        .replace("/", "_")
        .replace("\\", "_")
    )
    if cleaned in {".", ".."}:
        return "default"
    return cleaned or "default"


def history_file_path(
    run_history_dir: Path | str, task_name: str, account_name: str = ""
) -> Path:
    base = Path(run_history_dir)
    if account_name:
        safe_account = safe_history_key(account_name)
        safe_task = safe_history_key(task_name)
        return base / f"{safe_account}__{safe_task}.json"
    return base / f"{safe_history_key(task_name)}.json"


def legacy_history_file_path(
    run_history_dir: Path | str, task_name: str, account_name: str = ""
) -> Path:
    """升级前（未对 _ / % 转义）落盘的历史文件路径，仅用于兼容读取。"""
    base = Path(run_history_dir)
    if account_name:
        return base / f"{_legacy_history_key(account_name)}__{_legacy_history_key(task_name)}.json"
    return base / f"{_legacy_history_key(task_name)}.json"


def history_file_owner(history_file: Path) -> Optional[str]:
    """从历史文件名反查其账号宿主。

    文件名为 `{account}__{task}.json`（account/task 均经 safe_history_key 编码），
    因此可逆；旧版单账号布局 `{task}.json` 无账号段，返回 None。
    """
    stem = Path(history_file).stem
    if "__" not in stem:
        return None
    account_part = stem.split("__", 1)[0]
    decoded = unsafe_history_key(account_part)
    return decoded or None


def load_history_payload_from_file(history_file: Path) -> List[Any]:
    # 历史文件损坏或读取失败时表现为历史凭空消失，read_json_safe 会留下告警线索
    data = read_json_safe(history_file, default=None)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def resolve_existing_history_file(
    run_history_dir: Path, task_name: str, account_name: str = ""
) -> Optional[Path]:
    history_file = history_file_path(run_history_dir, task_name, account_name)
    if history_file.exists():
        return history_file
    # 兼容升级前落盘的文件：旧编码（不转义 _ / %）路径仍可读，
    # 避免换编码后既有历史凭空消失
    legacy_encoded = legacy_history_file_path(run_history_dir, task_name, account_name)
    if legacy_encoded != history_file and legacy_encoded.exists():
        return legacy_encoded
    legacy_file = run_history_dir / f"{safe_history_key(task_name)}.json"
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
    history_file = resolve_existing_history_file(
        run_history_dir, task_name, account_name
    )
    if history_file is None:
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


def cleanup_old_history_files(run_history_dir: Path | str, *, max_age_days: int = 3) -> int:
    """删除过期历史文件，返回删除数量。"""
    from datetime import timedelta

    from backend.utils.time import utc_now

    base_dir = Path(run_history_dir)
    if not base_dir.exists():
        return 0
    days = clamp_max_age_days(max_age_days)
    limit = utc_now() - timedelta(days=days)
    removed = 0
    for log_file in base_dir.glob("*.json"):
        try:
            if log_file.stat().st_mtime < limit.timestamp():
                log_file.unlink()
                removed += 1
        except OSError as exc:
            _logger.debug("清理过期历史文件失败: %s (%s)", log_file, exc)
            continue
    return removed


def resolve_task_config_dir(
    signs_dir: Path,
    account_name: str,
    task_name: str,
) -> Path:
    """优先 account/task 目录，回退到 legacy signs/task。"""
    preferred = signs_dir / account_name / task_name
    if preferred.exists():
        return preferred
    legacy = signs_dir / task_name
    if legacy.exists():
        return legacy
    return preferred


def patch_tasks_cache_last_run(
    tasks_cache: Optional[List[Any]],
    *,
    task_name: str,
    account_name: str,
    last_run: Any,
) -> bool:
    """就地更新内存任务缓存中的 last_run；命中返回 True。"""
    if not isinstance(tasks_cache, list):
        return False
    for item in tasks_cache:
        if not isinstance(item, dict):
            continue
        if item.get("name") != task_name:
            continue
        if item.get("account_name") != account_name:
            continue
        if last_run is None:
            item.pop("last_run", None)
        else:
            item["last_run"] = last_run
        return True
    return False


def plan_legacy_history_clear(
    data_list: List[Any],
    account_name: str,
) -> Dict[str, Any]:
    """
    规划清理 legacy 共享 history 文件中某一账号的条目。

    返回:
      remove_file: 是否应删除整个文件
      removed_entries: 被移除条数
      kept: 保留条目（仅当 remove_file=False）
    """
    if not data_list:
        return {"remove_file": True, "removed_entries": 0, "kept": []}

    # 旧版单账号场景：条目无 account_name 字段，整文件归属该账号
    has_account_field = any(
        isinstance(item, dict) and "account_name" in item for item in data_list
    )
    if not has_account_field:
        return {
            "remove_file": True,
            "removed_entries": len(data_list),
            "kept": [],
        }

    kept: List[Dict[str, Any]] = []
    removed = 0
    for item in data_list:
        if not isinstance(item, dict):
            continue
        if item.get("account_name") == account_name:
            removed += 1
        else:
            kept.append(item)

    if not kept:
        return {"remove_file": True, "removed_entries": removed, "kept": []}
    return {"remove_file": False, "removed_entries": removed, "kept": kept}

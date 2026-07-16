"""
签到历史条目格式化

从 SignTaskService 历史查询路径抽出的纯函数，减少重复拼装逻辑。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List


def normalize_flow_logs(raw: Any) -> List[Any]:
    if isinstance(raw, list):
        return raw
    return []


def build_history_list_item(
    item: Dict[str, Any],
    *,
    task_name: str,
    account_name: str,
    repair: Callable[[str], str],
    extract_last_target: Callable[[List[Any]], str],
) -> Dict[str, Any]:
    """构造列表/最近日志用的统一结构。"""
    flow_logs = normalize_flow_logs(item.get("flow_logs"))
    repaired_flows = [repair(str(line)) for line in flow_logs]
    timestamp = str(item.get("time") or "")
    return {
        "time": timestamp,
        "created_at": timestamp,
        "success": bool(item.get("success", False)),
        "message": repair(str(item.get("message", "") or "")),
        "flow_logs": repaired_flows,
        "flow_truncated": bool(item.get("flow_truncated", False)),
        "flow_line_count": int(item.get("flow_line_count", len(flow_logs))),
        "task_name": task_name,
        "account_name": account_name,
        "last_target_message": str(item.get("last_target_message") or "").strip()
        or extract_last_target(flow_logs),
        "failure_category": str(item.get("failure_category") or ""),
    }


def clamp_limit(limit: int, *, minimum: int = 1, maximum: int = 200) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = minimum
    return max(minimum, min(value, maximum))

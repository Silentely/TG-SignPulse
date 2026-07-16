"""
签到历史条目格式化

从 SignTaskService 历史查询路径抽出的纯函数，减少重复拼装逻辑。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional


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


def normalize_and_trim_flow_logs(
    flow_logs: Any,
    *,
    repair: Callable[[str], str],
    max_lines: Optional[int] = None,
    max_line_chars: Optional[int] = None,
) -> tuple[List[str], bool, int]:
    """
    规范化 flow_logs：修复乱码、去换行，可选截断行数/行长。

    返回 (trimmed_lines, truncated, original_count)。
    """
    if not isinstance(flow_logs, list):
        return [], False, 0

    total = len(flow_logs)
    source = flow_logs
    truncated = False
    if max_lines is not None and max_lines > 0 and total > max_lines:
        source = flow_logs[-max_lines:]
        truncated = True

    trimmed: List[str] = []
    for line in source:
        text = repair(str(line)).replace("\r", "").rstrip("\n")
        if max_line_chars is not None and max_line_chars > 0 and len(text) > max_line_chars:
            text = text[: max_line_chars - 1] + "…"
            truncated = True
        trimmed.append(text)
    return trimmed, truncated, total


def build_history_run_entry(
    *,
    success: bool,
    message: str,
    account_name: str,
    timestamp: str,
    normalized_logs: List[str],
    flow_truncated: bool,
    flow_line_count: int,
    last_target_message: str,
    failure_category: str,
    repair: Callable[[str], str],
) -> Dict[str, Any]:
    """构造写入 history 文件的单条执行记录。"""
    return {
        "time": timestamp,
        "success": bool(success),
        "message": repair(str(message or "")),
        "account_name": account_name,
        "flow_logs": list(normalized_logs),
        "flow_truncated": bool(flow_truncated),
        "flow_line_count": int(flow_line_count),
        "last_target_message": str(last_target_message or "").strip(),
        "failure_category": str(failure_category or ""),
    }


def prepend_history_entry(
    history: Any,
    entry: Dict[str, Any],
    *,
    max_entries: int,
) -> List[Dict[str, Any]]:
    """将新记录插入列表头部并截断。"""
    if isinstance(history, list):
        items: List[Any] = list(history)
    elif isinstance(history, dict):
        items = [history]
    else:
        items = []
    items.insert(0, entry)
    limit = max(1, int(max_entries or 1))
    # 保留既有结构；调用方写入 JSON 时允许混入历史脏数据
    return items[:limit]  # type: ignore[return-value]

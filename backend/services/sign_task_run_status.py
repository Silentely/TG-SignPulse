"""
签到任务运行状态结构

纯函数构造 run status 字典，供 SignTaskService 内存状态复用。
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


def make_task_key(account_name: str, task_name: str) -> Tuple[str, str]:
    return str(account_name or ""), str(task_name or "")


def build_run_status(
    *,
    run_id: str,
    state: str,
    success: Optional[bool] = None,
    error: str = "",
    output: str = "",
    started_at: Optional[str] = None,
    finished_at: Optional[str] = None,
    default_started_at: str = "",
) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "state": state,
        "success": success,
        "error": str(error or ""),
        "output": str(output or ""),
        "started_at": started_at or default_started_at,
        "finished_at": finished_at,
    }


def idle_running_placeholder(*, started_at: str) -> Dict[str, Any]:
    """任务已标记运行但尚无完整 status 时的占位。"""
    return build_run_status(
        run_id="",
        state="running",
        success=None,
        error="",
        output="",
        started_at=started_at,
        finished_at=None,
    )


def resolve_stored_run_status(
    status: Optional[Dict[str, Any]],
    *,
    requested_run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    解析内存中的 run status。

    - 无记录 → idle
    - 请求了 run_id 且与当前不一致 → stale
    - 否则返回副本
    """
    if not status:
        return {
            "run_id": requested_run_id or "",
            "state": "idle",
            "success": None,
            "error": "",
            "output": "",
            "started_at": None,
            "finished_at": None,
        }
    if requested_run_id and status.get("run_id") != requested_run_id:
        return {
            "run_id": requested_run_id,
            "state": "stale",
            "success": None,
            "error": "",
            "output": "",
            "started_at": None,
            "finished_at": None,
        }
    return dict(status)


def build_runner_failure_result(
    *,
    cancelled: bool = False,
    error: str = "",
) -> Dict[str, Any]:
    """start_task_run 后台 runner 失败/取消时的统一结果。"""
    if cancelled:
        return {
            "success": False,
            "error": "Task execution cancelled",
            "output": "",
        }
    return {
        "success": False,
        "error": str(error or "Task execution failed"),
        "output": "",
    }

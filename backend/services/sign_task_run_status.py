"""
签到任务运行状态结构

纯函数构造 run status 字典，供 SignTaskService 内存状态复用。
state 粗粒度兼容；phase 细粒度供面板展示。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

# 粗粒度 state（向后兼容 + timeout）
RUN_STATE_IDLE = "idle"
RUN_STATE_RUNNING = "running"
RUN_STATE_FINISHED = "finished"
RUN_STATE_CANCELLED = "cancelled"
RUN_STATE_STALE = "stale"
RUN_STATE_TIMEOUT = "timeout"

# 细粒度 phase（仅 state=running 时有意义）
PHASE_STARTING = "starting"
PHASE_CHECKING_ACCOUNT = "checking_account"
PHASE_WAITING_LOCK = "waiting_lock"
PHASE_COOLDOWN = "cooldown"
PHASE_RUNNING = "running"
PHASE_FINALIZING = "finalizing"

def make_task_key(account_name: str, task_name: str) -> Tuple[str, str]:
    return str(account_name or ""), str(task_name or "")


def resolve_effective_retry_count(
    task_cfg: Optional[Mapping[str, Any]],
    global_default: int,
    *,
    min_v: int = 0,
    max_v: int = 99,
) -> int:
    """
    任务 JSON 存在 retry_count 键 → 用任务值；否则用全局默认。

    全局默认通常来自 get_flow_retry_attempts()。
    """
    try:
        fallback = int(global_default)
    except (TypeError, ValueError):
        fallback = 1
    fallback = max(min_v, min(max_v, fallback))

    if not isinstance(task_cfg, Mapping) or "retry_count" not in task_cfg:
        return fallback
    try:
        value = int(task_cfg.get("retry_count"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    return max(min_v, min(max_v, value))


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
    phase: Optional[str] = None,
    phase_detail: str = "",
    wait_seconds: Optional[float] = None,
    account_name: str = "",
    task_name: str = "",
    failure_category: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
    retry_count_effective: Optional[int] = None,
) -> Dict[str, Any]:
    """构造统一 run status 字典。终态时 phase 强制为 None。"""
    normalized_state = str(state or RUN_STATE_IDLE)
    # 终态不展示 phase；进行中缺省 starting
    if normalized_state == RUN_STATE_RUNNING:
        normalized_phase: Optional[str] = phase or PHASE_STARTING
    else:
        normalized_phase = None

    if started_at is not None:
        resolved_started: Optional[str] = started_at
    elif default_started_at:
        resolved_started = default_started_at
    else:
        resolved_started = None

    payload: Dict[str, Any] = {
        "run_id": run_id,
        "state": normalized_state,
        "success": success,
        "error": str(error or ""),
        "output": str(output or ""),
        "started_at": resolved_started,
        "finished_at": finished_at,
        "phase": normalized_phase,
        "phase_detail": str(phase_detail or ""),
        "wait_seconds": wait_seconds,
        "account_name": str(account_name or ""),
        "task_name": str(task_name or ""),
        "failure_category": failure_category,
        "timeout_seconds": timeout_seconds,
        "retry_count_effective": retry_count_effective,
    }
    return payload


def idle_running_placeholder(*, started_at: str) -> Dict[str, Any]:
    """任务已标记运行但尚无完整 status 时的占位。"""
    return build_run_status(
        run_id="",
        state=RUN_STATE_RUNNING,
        success=None,
        error="",
        output="",
        started_at=started_at,
        finished_at=None,
        phase=PHASE_STARTING,
        phase_detail="",
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
    - 否则返回副本（透传扩展字段）
    """
    if not status:
        return build_run_status(
            run_id=requested_run_id or "",
            state=RUN_STATE_IDLE,
            success=None,
            error="",
            output="",
            started_at=None,
            finished_at=None,
            phase=None,
        )
    if requested_run_id and status.get("run_id") != requested_run_id:
        return build_run_status(
            run_id=requested_run_id,
            state=RUN_STATE_STALE,
            success=None,
            error="",
            output="",
            started_at=None,
            finished_at=None,
            phase=None,
        )
    return dict(status)


def summarize_active_run(status: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """列表 / active-runs 用的瘦身字段；非 running 返回 None。"""
    if not status:
        return None
    if str(status.get("state") or "") != RUN_STATE_RUNNING:
        return None
    return {
        "run_id": str(status.get("run_id") or ""),
        "state": RUN_STATE_RUNNING,
        "phase": status.get("phase"),
        "phase_detail": str(status.get("phase_detail") or ""),
        "account_name": str(status.get("account_name") or ""),
        "task_name": str(status.get("task_name") or ""),
        "started_at": status.get("started_at"),
        "wait_seconds": status.get("wait_seconds"),
    }


def is_timeout_error_message(error: str) -> bool:
    """根据错误文案判断是否执行超时。"""
    text = str(error or "").lower()
    return "任务执行超时" in text or "execution timeout" in text or (
        "timeout" in text and "强制终止" in str(error or "")
    )


def build_runner_failure_result(
    *,
    cancelled: bool = False,
    error: str = "",
    timed_out: bool = False,
) -> Dict[str, Any]:
    """start_task_run 后台 runner 失败/取消/超时时的统一结果。"""
    if cancelled:
        return {
            "success": False,
            "error": "Task execution cancelled",
            "output": "",
            "timed_out": False,
        }
    if timed_out or is_timeout_error_message(error):
        return {
            "success": False,
            "error": str(error or "Task execution timeout"),
            "output": "",
            "timed_out": True,
        }
    return {
        "success": False,
        "error": str(error or "Task execution failed"),
        "output": "",
        "timed_out": False,
    }

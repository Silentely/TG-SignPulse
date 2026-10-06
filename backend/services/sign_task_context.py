from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from backend.services.sign_tasks import SignTaskService


class TaskPhase(str, Enum):
    STARTING = "STARTING"
    WAITING_LOCK = "WAITING_LOCK"
    RUNNING = "RUNNING"
    FINALIZING = "FINALIZING"
    FINISHED = "FINISHED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


_ALLOWED_TRANSITIONS: dict[TaskPhase, set[TaskPhase]] = {
    TaskPhase.STARTING: {TaskPhase.WAITING_LOCK},
    TaskPhase.WAITING_LOCK: {TaskPhase.RUNNING},
    TaskPhase.RUNNING: {TaskPhase.FINALIZING},
    TaskPhase.FINALIZING: {
        TaskPhase.FINISHED,
        TaskPhase.FAILED,
        TaskPhase.CANCELLED,
    },
    TaskPhase.FINISHED: set(),
    TaskPhase.FAILED: set(),
    TaskPhase.CANCELLED: set(),
}

_TERMINAL_PHASES: set[TaskPhase] = {
    TaskPhase.FINISHED,
    TaskPhase.FAILED,
    TaskPhase.CANCELLED,
}


@dataclass
class TaskExecutionContext:
    """Strongly typed execution context with state machine lifecycle validation.

    Lifecycle sequence:
    STARTING -> WAITING_LOCK -> RUNNING -> FINALIZING -> (FINISHED | FAILED | CANCELLED)
    """

    account_name: str
    task_name: str
    run_id: Optional[str] = None
    task_key: str = ""
    svc: Optional[SignTaskService] = None
    account_lock: Any = None
    settings: Any = None
    BackendUserSigner: Any = None
    TaskLogHandler: Any = None
    visited_chain: List[str] = field(default_factory=list)

    # State machine phase
    phase: TaskPhase = TaskPhase.STARTING

    # Execution flags & results
    success: bool = False
    error_msg: str = ""
    error_raw: str = ""
    output_str: str = ""
    account_invalid_detected: bool = False
    flood_wait_cooling: bool = False
    timed_out: bool = False
    lock_acquired: bool = False
    cancelled: bool = False
    task_timeout: float = 120.0
    failure_category: Optional[str] = None

    # Config & signer parameters
    task_cfg: Optional[Dict[str, Any]] = None
    raw_task_cfg: Optional[Dict[str, Any]] = None
    requires_updates: bool = False
    has_keyword_monitor: bool = False
    signer_no_updates: bool = True
    task_notify_on_failure: bool = True
    task_notify_on_success: bool = True

    signer: Any = None
    tg_logger: Any = None
    log_handler: Any = None
    api_id: Any = None
    api_hash: Any = None
    session_dir: Any = None
    session_string: Optional[str] = None
    use_in_memory: bool = False
    proxy_dict: Optional[Dict[str, Any]] = None

    # Logs and replies
    final_logs: List[str] = field(default_factory=list)
    last_reply: str = ""
    last_target_message: str = ""

    # Observability
    persistence_error: Optional[Dict[str, Any]] = None
    notification_error: Optional[Dict[str, Any]] = None
    workflow_path: Optional[List[str]] = None

    def transition_to(self, target: TaskPhase) -> None:
        """Advance the execution context state machine to target phase.

        Raises ValueError on invalid skips, backward transitions, or terminal mutations.
        """
        if not isinstance(target, TaskPhase):
            try:
                target = TaskPhase(target)
            except ValueError:
                raise ValueError(f"Invalid target phase: {target}")

        if self.phase in _TERMINAL_PHASES:
            raise ValueError(
                f"Cannot transition from terminal phase {self.phase.value} to {target.value}"
            )

        allowed = _ALLOWED_TRANSITIONS.get(self.phase, set())
        if target not in allowed:
            raise ValueError(
                f"Disallowed phase transition from {self.phase.value} to {target.value}. "
                f"Allowed transitions from {self.phase.value}: {[p.value for p in allowed]}"
            )

        self.phase = target

    def start_finalizing(self) -> None:
        """进入收尾阶段，保证任意非终态都能走到 FINALIZING。

        正常路径为 RUNNING -> FINALIZING；若任务在达到 RUNNING 之前即失败
        （配置加载失败、账号失效、冷却短路等），也允许从 STARTING/WAITING_LOCK
        直接进入收尾，否则该运行将永远停留在启动阶段、无法落到终态。
        已是 FINALIZING 或终态时为幂等空操作。
        """
        if self.phase in _TERMINAL_PHASES or self.phase == TaskPhase.FINALIZING:
            return
        self.phase = TaskPhase.FINALIZING

    def finish(self, *, cancelled: bool, success: bool) -> None:
        """收尾结束，按结果落到 FINISHED / FAILED / CANCELLED。

        必须在 start_finalizing() 之后调用；处于终态时为幂等空操作。
        """
        if self.phase in _TERMINAL_PHASES:
            return
        if self.phase != TaskPhase.FINALIZING:
            raise ValueError(
                f"Cannot finish from phase {self.phase.value}; call start_finalizing() first"
            )
        if cancelled:
            target = TaskPhase.CANCELLED
        elif success:
            target = TaskPhase.FINISHED
        else:
            target = TaskPhase.FAILED
        self.phase = target

    # Read-only dictionary adapter for backwards compatibility with legacy readers
    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        raise TypeError(
            "TaskExecutionContext does not support item assignment; mutate attributes directly."
        )

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        return default

    def __contains__(self, key: object) -> bool:
        if isinstance(key, str):
            return hasattr(self, key)
        return False

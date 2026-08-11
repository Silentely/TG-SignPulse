from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any


def compute_backoff(attempt: int, *, cap: float = 8.0, shift: int = 0) -> float:
    """瞬态错误指数退避：``2**(attempt-1+shift)`` 封顶 ``cap``，attempt 从 1 起。

    - ``shift=0``：1,2,4,8…（compat / monitor 的语义）
    - ``shift=1``：2,4,8…（signer_actions / continue_actions 的语义）

    统一各模块散落的 `min(2**attempt, cap)` 写法，避免同公式多套实现；
    不同场景通过 cap 与 shift 表达差异，行为保持与既有代码一致。
    """
    if attempt < 1:
        attempt = 1
    return min(2 ** (attempt - 1 + shift), cap)


def create_logged_task(
    awaitable: Awaitable[Any],
    *,
    logger: logging.Logger | None = None,
    description: str = "background task",
    on_done: Callable[[asyncio.Task[Any]], None] | None = None,
) -> asyncio.Task[Any]:
    task = asyncio.create_task(awaitable)
    task_logger = logger or logging.getLogger(__name__)

    def _handle_done(completed: asyncio.Task[Any]) -> None:
        try:
            if on_done is not None:
                on_done(completed)
        except Exception:
            task_logger.exception("收尾回调执行失败 %s", description)
            # 不提前返回：即使 on_done 异常，也需取出任务异常，避免
            # "Task exception was never retrieved" 告警与异常丢失

        if completed.cancelled():
            return

        try:
            exc = completed.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            task_logger.error("%s 执行失败: %s", description, exc, exc_info=exc)

    task.add_done_callback(_handle_done)
    return task

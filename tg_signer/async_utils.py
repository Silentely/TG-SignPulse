from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Hashable
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


def schedule_deferred_cleanup(
    *,
    task_key: Hashable,
    delay_seconds: float,
    registry: dict[Hashable, asyncio.Task[Any]],
    active: dict[Hashable, bool],
    target: dict[Hashable, Any],
    logger: logging.Logger | None = None,
    description: str = "deferred cleanup",
) -> None:
    """注册延迟清理任务：延迟结束后若条目不再活跃则从 target 弹出并自动注销。

    收敛 sign_task_runner / sign_tasks 中同构的清理协程：
    - 先取消同 key 的旧清理任务，避免重复注册导致多个睡眠并存；
    - finally 用身份比较移除自身，避免被取消的旧任务在下一轮事件循环
      执行 finally 时误删新注册的清理任务。
    """
    old = registry.get(task_key)
    if old is not None and not old.done():
        old.cancel()

    cleanup_task: asyncio.Task[Any] | None = None

    async def cleanup() -> None:
        try:
            await asyncio.sleep(delay_seconds)
            if not active.get(task_key):
                target.pop(task_key, None)
        finally:
            if registry.get(task_key) is cleanup_task:
                registry.pop(task_key, None)

    cleanup_task = create_logged_task(
        cleanup(),
        logger=logger,
        description=description,
    )
    registry[task_key] = cleanup_task


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

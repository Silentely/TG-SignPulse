from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any


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
            task_logger.exception("Failed to finalize %s", description)
            return

        if completed.cancelled():
            return

        try:
            exc = completed.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            task_logger.error("%s failed: %s", description, exc, exc_info=exc)

    task.add_done_callback(_handle_done)
    return task

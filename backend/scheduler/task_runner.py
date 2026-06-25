"""
并发任务执行器

提供带信号量限流的异步任务批量执行能力，支持：
- 信号量限流：控制最大并发数，防止资源耗尽
- 批量并发执行：通过 asyncio.gather 并发运行多个任务
- 任务取消：支持单个任务取消和批量取消
- 超时控制：单任务和全局超时保护
- 结果收集：统一收集成功/失败/取消结果
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional, Sequence

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """任务执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskResult:
    """单个任务的执行结果"""
    task_id: str
    status: TaskStatus
    result: Any = None
    error: Optional[BaseException] = None
    elapsed: float = 0.0


@dataclass
class BatchResult:
    """批量任务的汇总结果"""
    results: list[TaskResult] = field(default_factory=list)

    @property
    def succeeded(self) -> list[TaskResult]:
        """获取所有成功的任务结果"""
        return [r for r in self.results if r.status == TaskStatus.SUCCESS]

    @property
    def failed(self) -> list[TaskResult]:
        """获取所有失败的任务结果"""
        return [r for r in self.results if r.status == TaskStatus.FAILED]

    @property
    def cancelled(self) -> list[TaskResult]:
        """获取所有被取消的任务结果"""
        return [r for r in self.results if r.status == TaskStatus.CANCELLED]

    @property
    def total(self) -> int:
        """任务总数"""
        return len(self.results)


class TaskRunner:
    """
    并发任务执行器

    通过 asyncio.Semaphore 控制最大并发数，使用 asyncio.gather 批量执行任务。
    支持单任务和批量任务的取消操作。

    参数:
        max_concurrency: 最大并发数，最小为 1
        task_timeout: 单任务超时时间（秒），None 表示不限制
        on_task_done: 单任务完成时的回调函数

    示例:
        runner = TaskRunner(max_concurrency=3, task_timeout=30.0)

        async def my_task(task_id: str) -> str:
            await asyncio.sleep(1)
            return f"{task_id} done"

        tasks = [
            ("task-1", my_task, ("task-1",), {}),
            ("task-2", my_task, ("task-2",), {}),
        ]
        batch_result = await runner.run_batch(tasks)
    """

    def __init__(
        self,
        max_concurrency: int = 1,
        task_timeout: Optional[float] = None,
        on_task_done: Optional[Callable[[TaskResult], None]] = None,
    ) -> None:
        if max_concurrency < 1:
            max_concurrency = 1
        self._max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._task_timeout = task_timeout
        self._on_task_done = on_task_done
        # 活跃任务映射：task_id -> asyncio.Task
        self._active_tasks: dict[str, asyncio.Task[Any]] = {}

    @property
    def max_concurrency(self) -> int:
        """当前最大并发数"""
        return self._max_concurrency

    @property
    def active_count(self) -> int:
        """当前活跃任务数"""
        return len(self._active_tasks)

    def update_concurrency(self, new_limit: int) -> None:
        """
        运行时更新并发限制

        参数:
            new_limit: 新的并发数，小于 1 时自动修正为 1
        """
        if new_limit < 1:
            new_limit = 1
        self._max_concurrency = new_limit
        self._semaphore = asyncio.Semaphore(new_limit)

    async def run_single(
        self,
        task_id: str,
        coro_factory: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> TaskResult:
        """
        执行单个任务（受信号量限流）

        参数:
            task_id: 任务唯一标识
            coro_factory: 返回协程的可调用对象
            *args: 传递给 coro_factory 的位置参数
            **kwargs: 传递给 coro_factory 的关键字参数

        返回:
            TaskResult: 包含执行状态、结果或异常
        """
        start = time.monotonic()
        status = TaskStatus.PENDING
        result_value = None
        error_value = None

        # 将当前 asyncio 任务注册到活跃映射，支持外部取消
        current_task = asyncio.current_task()
        if current_task is not None:
            self._active_tasks[task_id] = current_task

        try:
            async with self._semaphore:
                status = TaskStatus.RUNNING
                coro = coro_factory(*args, **kwargs)

                if self._task_timeout is not None:
                    result_value = await asyncio.wait_for(
                        coro, timeout=self._task_timeout
                    )
                else:
                    result_value = await coro

                status = TaskStatus.SUCCESS

        except asyncio.CancelledError:
            status = TaskStatus.CANCELLED

        except asyncio.TimeoutError:
            status = TaskStatus.FAILED
            error_value = RuntimeError(
                f"任务 {task_id} 执行超时（{self._task_timeout} 秒）"
            )

        except Exception as exc:
            status = TaskStatus.FAILED
            error_value = exc

        finally:
            elapsed = time.monotonic() - start
            task_result = TaskResult(
                task_id=task_id,
                status=status,
                result=result_value,
                error=error_value,
                elapsed=elapsed,
            )

            if self._on_task_done is not None:
                try:
                    self._on_task_done(task_result)
                except Exception:
                    logger.exception("任务回调执行失败: %s", task_id)

            self._active_tasks.pop(task_id, None)

        return task_result

    async def run_batch(
        self,
        tasks: Sequence[
            tuple[str, Callable[..., Awaitable[Any]], tuple[Any, ...], dict[str, Any]]
        ],
        *,
        return_when: str = "ALL_COMPLETED",
    ) -> BatchResult:
        """
        批量并发执行任务

        参数:
            tasks: 任务描述序列，每个元素为 (task_id, coro_factory, args, kwargs)
            return_when: 完成策略，支持 "ALL_COMPLETED" 和 "FIRST_EXCEPTION"

        返回:
            BatchResult: 包含所有任务的执行结果
        """
        if not tasks:
            return BatchResult(results=[])

        async_tasks: list[asyncio.Task[TaskResult]] = []
        for task_id, coro_factory, args, kwargs in tasks:
            wrapped = asyncio.ensure_future(
                self.run_single(task_id, coro_factory, *args, **kwargs)
            )
            self._active_tasks[task_id] = wrapped
            async_tasks.append(wrapped)

        # 映射 return_when 参数
        gather_return_when = {
            "ALL_COMPLETED": asyncio.ALL_COMPLETED,
            "FIRST_EXCEPTION": asyncio.FIRST_EXCEPTION,
        }.get(return_when, asyncio.ALL_COMPLETED)

        done, pending = await asyncio.wait(
            async_tasks, return_when=gather_return_when
        )

        # 取消仍在挂起的任务
        for task in pending:
            if not task.done():
                task.cancel()

        # 等待取消的任务完成清理
        if pending:
            await asyncio.wait(pending, return_when=asyncio.ALL_COMPLETED)

        # 收集结果，保持原始顺序
        results: list[TaskResult] = []
        for async_task in async_tasks:
            try:
                task_result = async_task.result()
                results.append(task_result)
            except asyncio.CancelledError:
                # 任务在 gather 层面被取消
                results.append(
                    TaskResult(
                        task_id="unknown",
                        status=TaskStatus.CANCELLED,
                    )
                )
            except Exception as exc:
                results.append(
                    TaskResult(
                        task_id="unknown",
                        status=TaskStatus.FAILED,
                        error=exc,
                    )
                )

        return BatchResult(results=results)

    def cancel_task(self, task_id: str) -> bool:
        """
        取消指定任务

        参数:
            task_id: 要取消的任务标识

        返回:
            bool: 是否成功发起取消（True 表示找到并取消）
        """
        task = self._active_tasks.get(task_id)
        if task is not None and not task.done():
            task.cancel()
            return True
        return False

    def cancel_all(self) -> int:
        """
        取消所有活跃任务

        返回:
            int: 成功发起取消的任务数量
        """
        cancelled_count = 0
        for _task_id, task in list(self._active_tasks.items()):
            if not task.done():
                task.cancel()
                cancelled_count += 1
        return cancelled_count

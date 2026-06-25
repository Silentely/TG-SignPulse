"""
批量操作 API 路由

提供任务的批量启用、禁用、删除和执行功能。
所有端点均需认证。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.models.user import User
from backend.scheduler import sync_jobs
from backend.schemas.batch import (
    BatchAction,
    BatchTaskRequest,
    BatchTaskResponse,
    BatchTaskResult,
)
from backend.services import tasks as task_service

router = APIRouter()


@router.post("/tasks", response_model=BatchTaskResponse)
async def batch_task_operation(
    payload: BatchTaskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    批量任务操作

    支持的操作类型：
    - enable: 批量启用任务
    - disable: 批量禁用任务
    - delete: 批量删除任务
    - run: 批量执行任务
    """
    results: list[BatchTaskResult] = []
    success_count = 0
    fail_count = 0

    for task_id in payload.task_ids:
        try:
            task = task_service.get_task(db, task_id)
            if not task:
                results.append(
                    BatchTaskResult(
                        task_id=task_id,
                        success=False,
                        message="任务不存在",
                    )
                )
                fail_count += 1
                continue

            if payload.action == BatchAction.ENABLE:
                task_service.update_task(db, task, enabled=True)
                results.append(
                    BatchTaskResult(task_id=task_id, success=True, message="已启用")
                )
                success_count += 1

            elif payload.action == BatchAction.DISABLE:
                task_service.update_task(db, task, enabled=False)
                results.append(
                    BatchTaskResult(task_id=task_id, success=True, message="已禁用")
                )
                success_count += 1

            elif payload.action == BatchAction.DELETE:
                task_service.delete_task(db, task)
                results.append(
                    BatchTaskResult(task_id=task_id, success=True, message="已删除")
                )
                success_count += 1

            elif payload.action == BatchAction.RUN:
                await task_service.run_task_once(db, task)
                results.append(
                    BatchTaskResult(task_id=task_id, success=True, message="已执行")
                )
                success_count += 1

        except Exception as e:
            results.append(
                BatchTaskResult(
                    task_id=task_id,
                    success=False,
                    message=f"操作失败: {str(e)}",
                )
            )
            fail_count += 1

    # 非 run 操作需要同步调度器
    if payload.action in (
        BatchAction.ENABLE,
        BatchAction.DISABLE,
        BatchAction.DELETE,
    ):
        await sync_jobs()

    return BatchTaskResponse(
        total=len(payload.task_ids),
        success_count=success_count,
        fail_count=fail_count,
        results=results,
    )

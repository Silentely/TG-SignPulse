"""
批量操作 API 路由

- POST /batch/sign-tasks ：新版签到任务（文件存储）批量操作（推荐）
- POST /batch/tasks      ：旧版 ORM 任务批量操作（已弃用，仅兼容）
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Response
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
from backend.schemas.sign_batch import (
    SignBatchAction,
    SignBatchTaskRequest,
    SignBatchTaskResponse,
    SignBatchTaskResult,
)
from backend.services import tasks as task_service
from backend.services.sign_tasks import get_sign_task_service

logger = logging.getLogger("backend.batch")

router = APIRouter()

_LEGACY_DEPRECATION = (
    "Legacy /api/batch/tasks and /api/tasks are deprecated. "
    "Use /api/batch/sign-tasks and /api/sign-tasks instead."
)


async def _restart_keyword_monitors() -> None:
    try:
        from backend.services.keyword_monitor import get_keyword_monitor_service

        await get_keyword_monitor_service().restart_from_tasks()
    except Exception as exc:
        logger.warning("批量操作后重启关键词监控失败: %s", exc)


def _resolve_sign_account(task_name: str, account_name: Optional[str]) -> Optional[str]:
    """解析可用于 update/run 的账号名。"""
    service = get_sign_task_service()
    effective = account_name if (account_name and account_name != "*") else None
    existing = service.get_task(
        task_name,
        account_name=effective,
        aggregate=effective is None,
    )
    if not existing:
        return None
    resolved = effective or ""
    if not resolved:
        for name in existing.get("account_names") or []:
            if name and name != "*":
                resolved = name
                break
        if not resolved:
            resolved = str(existing.get("account_name") or "")
        if resolved == "*":
            resolved = ""
    return resolved or None


@router.post("/sign-tasks", response_model=SignBatchTaskResponse)
async def batch_sign_task_operation(
    payload: SignBatchTaskRequest,
    current_user: User = Depends(get_current_user),
):
    """
    新版签到任务批量操作（文件存储体系）。

    支持 enable / disable / delete / run。
    """
    service = get_sign_task_service()
    results: list[SignBatchTaskResult] = []
    success_count = 0
    fail_count = 0
    needs_sync = payload.action in (
        SignBatchAction.ENABLE,
        SignBatchAction.DISABLE,
        SignBatchAction.DELETE,
    )

    for item in payload.tasks:
        name = item.name
        try:
            if payload.action == SignBatchAction.RUN:
                run_account = (
                    payload.run_account_name
                    or item.account_name
                    or _resolve_sign_account(name, item.account_name)
                )
                if not run_account or run_account == "*":
                    results.append(
                        SignBatchTaskResult(
                            name=name,
                            account_name=item.account_name or "",
                            success=False,
                            message="无法确定执行账号",
                        )
                    )
                    fail_count += 1
                    continue
                await service.start_task_run(run_account, name)
                results.append(
                    SignBatchTaskResult(
                        name=name,
                        account_name=run_account,
                        success=True,
                        message="已启动执行",
                    )
                )
                success_count += 1
                continue

            resolved = _resolve_sign_account(name, item.account_name)
            existing = service.get_task(
                name,
                account_name=resolved,
                aggregate=resolved is None,
            )
            if not existing:
                results.append(
                    SignBatchTaskResult(
                        name=name,
                        account_name=item.account_name or "",
                        success=False,
                        message="任务不存在",
                    )
                )
                fail_count += 1
                continue

            if payload.action == SignBatchAction.ENABLE:
                service.update_task(
                    task_name=name,
                    account_name=resolved,
                    enabled=True,
                )
                results.append(
                    SignBatchTaskResult(
                        name=name,
                        account_name=resolved or "",
                        success=True,
                        message="已启用",
                    )
                )
                success_count += 1
            elif payload.action == SignBatchAction.DISABLE:
                service.update_task(
                    task_name=name,
                    account_name=resolved,
                    enabled=False,
                )
                results.append(
                    SignBatchTaskResult(
                        name=name,
                        account_name=resolved or "",
                        success=True,
                        message="已禁用",
                    )
                )
                success_count += 1
            elif payload.action == SignBatchAction.DELETE:
                service.delete_task(name, account_name=resolved)
                results.append(
                    SignBatchTaskResult(
                        name=name,
                        account_name=resolved or "",
                        success=True,
                        message="已删除",
                    )
                )
                success_count += 1
        except Exception as exc:
            logger.warning("批量签到任务 %s 操作失败: %s", name, exc)
            results.append(
                SignBatchTaskResult(
                    name=name,
                    account_name=item.account_name or "",
                    success=False,
                    message=str(exc) or "操作失败",
                )
            )
            fail_count += 1

    if needs_sync:
        try:
            await sync_jobs()
            await _restart_keyword_monitors()
        except Exception as exc:
            logger.warning("批量操作后同步调度失败: %s", exc)

    return SignBatchTaskResponse(
        total=len(payload.tasks),
        success_count=success_count,
        fail_count=fail_count,
        results=results,
    )


@router.post(
    "/tasks",
    response_model=BatchTaskResponse,
    deprecated=True,
    summary="[Deprecated] 旧版 ORM 任务批量操作",
)
async def batch_task_operation(
    payload: BatchTaskRequest,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    批量任务操作（旧版 ORM `tasks` 表）。

    **已弃用**：请改用 `POST /api/batch/sign-tasks`。
    与 `/api/tasks` 一致：默认只读时返回 410。
    """
    from fastapi import HTTPException, status

    from backend.api.routes.tasks import _legacy_writes_allowed

    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "true"
    response.headers["X-API-Warn"] = _LEGACY_DEPRECATION
    logger.warning("调用了已弃用的 /api/batch/tasks：%s", _LEGACY_DEPRECATION)

    if not _legacy_writes_allowed():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=(
                "Legacy ORM /api/batch/tasks is disabled by default "
                "(APP_LEGACY_TASKS_READONLY=1). Use /api/batch/sign-tasks."
            ),
        )

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
                try:
                    await task_service.run_task_once(db, task)
                    results.append(
                        BatchTaskResult(
                            task_id=task_id, success=True, message="已执行"
                        )
                    )
                    success_count += 1
                except Exception as run_exc:
                    logger.warning(
                        "批量执行任务 %d 失败: %s", task_id, run_exc
                    )
                    results.append(
                        BatchTaskResult(
                            task_id=task_id,
                            success=False,
                            message="任务执行失败",
                        )
                    )
                    fail_count += 1

        except Exception as e:
            logger.error("批量操作任务 %d 异常: %s", task_id, e)
            db.rollback()
            results.append(
                BatchTaskResult(
                    task_id=task_id,
                    success=False,
                    message="操作失败",
                )
            )
            fail_count += 1

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

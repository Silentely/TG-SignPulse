"""
批量操作 API 路由

- POST /batch/sign-tasks ：签到任务（文件存储）批量操作
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends

from backend.core.auth import get_current_user
from backend.models.user import User
from backend.scheduler import sync_jobs
from backend.schemas.sign_batch import (
    SignBatchAction,
    SignBatchTaskRequest,
    SignBatchTaskResponse,
    SignBatchTaskResult,
)
from backend.services.sign_tasks import get_sign_task_service

logger = logging.getLogger("backend.batch")

router = APIRouter()

async def _restart_keyword_monitors() -> None:
    from backend.services.sync_helpers import restart_keyword_monitors

    await restart_keyword_monitors(context="批量操作")


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
    if effective:
        return effective
    from backend.services.sign_task_group import first_real_account

    resolved = first_real_account(
        existing.get("account_names") or [],
        fallback=str(existing.get("account_name") or ""),
    )
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

    # 批量写期间挂起每次写后的全量缓存重扫，循环结束统一刷一次
    with service.defer_cache_refresh():
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
                # 详情进服务端日志；对外仅给稳定文案，避免内部异常细节（路径/SQL 等）透出
                logger.warning("批量签到任务 %s 操作失败: %s", name, exc, exc_info=True)
                results.append(
                    SignBatchTaskResult(
                        name=name,
                        account_name=item.account_name or "",
                        success=False,
                        message="操作失败",
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

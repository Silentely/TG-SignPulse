from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.orm import Session

from backend.core.auth import get_current_user, verify_token
from backend.core.database import get_db
from backend.models.task_log import TaskLog
from backend.schemas.task import TaskCreate, TaskOut, TaskUpdate
from backend.schemas.task_log import TaskLogOut
from backend.schemas.task_stats import TaskStatsOut
from backend.services import tasks as task_service

router = APIRouter()

# 旧版 ORM 任务路由：仅兼容存量客户端，新功能请使用 /api/sign-tasks
_LEGACY_WARN = (
    "Deprecated: /api/tasks uses legacy ORM storage. Prefer /api/sign-tasks."
)


def _mark_deprecated(response: Response) -> None:
    response.headers["Deprecation"] = "true"
    response.headers["X-API-Warn"] = _LEGACY_WARN


def _legacy_writes_allowed() -> bool:
    """
    旧版 ORM 任务写路径已永久关闭。

    历史环境变量 APP_LEGACY_TASKS_READONLY 不再开启写能力，
    仅保留函数名供 ops/边界检查引用。新功能请使用 /api/sign-tasks。
    """
    return False


def _reject_legacy_writes() -> None:
    """所有写操作统一 410（稳定错误码 LEGACY_TASKS_READONLY）。"""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="LEGACY_TASKS_READONLY",
    )


@router.get("/legacy-status")
def legacy_tasks_status(
    response: Response,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """旧版 ORM 任务存量与写路径下线状态（用于迁移自查）。"""
    _mark_deprecated(response)
    tasks = task_service.list_tasks(db)
    enabled = sum(1 for t in tasks if getattr(t, "enabled", False))
    writes_allowed = _legacy_writes_allowed()  # 恒为 False
    ready_for_route_removal = len(tasks) == 0
    if ready_for_route_removal:
        removal_stage = "writes_removed_ready"
    else:
        removal_stage = "writes_removed_with_stock"
    checklist = [
        "写路径已永久关闭（POST/PUT/DELETE/run 与 /api/batch/tasks 均 410）",
        "确认无外部脚本依赖旧写接口",
        "运行 tools/check_legacy_tasks.py 确认 orm_task_count=0",
        "确认面板与调度仅使用 /api/sign-tasks",
        "ready_for_route_removal=true 后可评估删除只读路由与 ORM Task 表",
    ]
    return {
        "legacy_writes_allowed": writes_allowed,
        "legacy_writes_removed": True,
        "readonly_default": True,
        "task_count": len(tasks),
        "enabled_count": enabled,
        "preferred_api": "/api/sign-tasks",
        "batch_api": "/api/batch/sign-tasks",
        "removal_stage": removal_stage,
        "ready_for_route_removal": ready_for_route_removal,
        "removal_checklist": checklist,
        "check_tool": "python tools/check_legacy_tasks.py --json",
        "hint": (
            "新功能请使用 sign-tasks；"
            "旧 /api/tasks 写路径已永久移除（410）；"
            "仅保留只读列表/详情/日志与 legacy-status"
        ),
    }


@router.get("", response_model=list[TaskOut], deprecated=True)
def list_tasks(
    response: Response,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _mark_deprecated(response)
    return task_service.list_tasks(db)


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED, deprecated=True)
async def create_task(
    response: Response,
    payload: TaskCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _mark_deprecated(response)
    _reject_legacy_writes()


@router.get("/stats", response_model=TaskStatsOut, deprecated=True)
def get_task_stats(
    response: Response,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """获取任务统计信息（聚合查询）"""
    _mark_deprecated(response)
    return task_service.get_task_stats(db)


@router.get("/{task_id}", response_model=TaskOut, deprecated=True)
def get_task(
    response: Response,
    task_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _mark_deprecated(response)
    task = task_service.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.put("/{task_id}", response_model=TaskOut, deprecated=True)
async def update_task(
    response: Response,
    task_id: int,
    payload: TaskUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _mark_deprecated(response)
    _reject_legacy_writes()


@router.delete("/{task_id}", status_code=status.HTTP_200_OK, deprecated=True)
async def delete_task(
    response: Response,
    task_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _mark_deprecated(response)
    _reject_legacy_writes()


@router.post("/{task_id}/run", response_model=TaskLogOut, deprecated=True)
async def run_task(
    response: Response,
    task_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _mark_deprecated(response)
    _reject_legacy_writes()


@router.get("/{task_id}/logs", response_model=list[TaskLogOut], deprecated=True)
def list_logs(
    response: Response,
    task_id: int,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _mark_deprecated(response)
    task = task_service.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    logs = task_service.list_task_logs(db, task_id, limit=limit)
    return logs


@router.websocket("/ws/{task_id}")
async def task_logs_ws(
    websocket: WebSocket,
    task_id: int,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """
    WebSocket 实时推送数据库任务日志
    """
    # 验证 Token
    try:
        user = verify_token(token, db)
        if not user:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    last_idx = 0
    try:
        while True:
            # 获取当前所有日志
            active_logs = task_service.get_active_logs(task_id)

            # 如果有新内容，则推送
            if len(active_logs) > last_idx:
                new_logs = active_logs[last_idx:]
                await websocket.send_json(
                    {
                        "type": "logs",
                        "data": new_logs,
                        "is_running": task_service.is_task_running(task_id),
                    }
                )
                last_idx = len(active_logs)

            # 如果任务已结束且日志已推完
            if not task_service.is_task_running(task_id) and last_idx >= len(
                active_logs
            ):
                await websocket.send_json({"type": "done", "is_running": False})
                break

            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logging.getLogger("backend.api.tasks").warning(
            "WS Error for Task %s: %s", task_id, e
        )
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@router.get("/logs/{log_id}/output")
def get_log_output(
    log_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """获取任务日志的完整输出文件内容"""
    log = db.query(TaskLog).filter(TaskLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Log not found")

    if not log.log_path or not Path(log.log_path).exists():
        return {"output": log.output or "No detailed log file available."}

    try:
        with open(log.log_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"output": content}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to read log file: {str(e)}"
        )

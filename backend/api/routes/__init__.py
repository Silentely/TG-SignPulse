from fastapi import APIRouter

from backend.api.routes import (
    accounts,
    auth,
    batch,
    config,
    events,
    keyword_hits,
    logs,
    ops,
    sign_tasks_v2,
    tasks,
    user,
)

router = APIRouter()
router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(user.router, prefix="/user", tags=["user"])
router.include_router(accounts.router, prefix="/accounts", tags=["accounts"])
# 旧版 ORM 任务 API：保留兼容，新功能请使用 /sign-tasks
router.include_router(tasks.router, prefix="/tasks", tags=["tasks-legacy"])
router.include_router(sign_tasks_v2.router, prefix="/sign-tasks", tags=["sign-tasks"])
router.include_router(logs.router, prefix="/logs", tags=["logs"])
router.include_router(config.router, prefix="/config", tags=["config"])
router.include_router(events.router, prefix="/events", tags=["events"])
router.include_router(batch.router, prefix="/batch", tags=["batch"])
router.include_router(ops.router, prefix="/ops", tags=["ops"])
router.include_router(
    keyword_hits.router, prefix="/keyword-hits", tags=["keyword-hits"]
)

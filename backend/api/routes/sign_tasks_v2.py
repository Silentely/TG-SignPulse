"""
Clean sign-task routes with shared multi-account task support.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import JSONResponse

try:
    from pydantic import BaseModel, Field, field_validator
    validator = None
except ImportError:  # pragma: no cover - pydantic v1 compatibility
    from pydantic import BaseModel, Field, validator
    field_validator = None
from sqlalchemy.orm import Session

from backend.core.auth import get_current_user, verify_token
from backend.core.database import get_db
from backend.services.sign_tasks import get_sign_task_service

router = APIRouter()

_sync_logger = logging.getLogger("backend.sign_tasks_api")


async def _safe_background_sync() -> None:
    """后台执行调度同步和监控重启，捕获异常避免静默丢失"""
    try:
        from backend.scheduler import sync_jobs
        await sync_jobs()
        await _restart_keyword_monitors()
    except Exception as e:
        _sync_logger.warning(f"后台调度同步失败: {e}")


def _model_dump(model: BaseModel) -> Dict[str, Any]:
    from backend.core.pydantic_compat import model_dump

    return model_dump(model)


async def _restart_keyword_monitors() -> None:
    try:
        from backend.services.keyword_monitor import get_keyword_monitor_service

        await get_keyword_monitor_service().restart_from_tasks()
    except Exception as exc:
        _sync_logger.warning("重启关键词监控失败: %s", exc)


class ChatConfig(BaseModel):
    chat_id: int = Field(..., description="Chat ID")
    name: str = Field("", description="Chat name")
    actions: List[Dict[str, Any]] = Field(..., description="Actions")
    delete_after: Optional[int] = Field(None, description="Delete delay seconds")
    action_interval: int = Field(1, description="Action interval seconds")
    message_thread_id: Optional[int] = Field(None, description="Thread ID")
    source_account: Optional[str] = Field(None, description="Account used to look up this chat (for avatar)")

    class Config:
        extra = "allow"


class SignTaskCreate(BaseModel):
    name: str = Field(..., description="Task name")
    account_name: str = Field("", description="Primary account name for compatibility")
    account_names: List[str] = Field(default_factory=list, description="Associated accounts")
    sign_at: str = Field(..., description="Schedule cron")
    chats: List[ChatConfig] = Field(..., description="Chat configs")
    random_seconds: int = Field(0, description="Random delay seconds")
    sign_interval: Optional[int] = Field(None, description="Action interval seconds")
    execution_mode: Optional[str] = Field("fixed", description="fixed/range")
    range_start: Optional[str] = Field(None, description="Range start")
    range_end: Optional[str] = Field(None, description="Range end")
    notify_on_failure: bool = Field(True, description="Failure notification switch")
    notify_on_success: bool = Field(True, description="Success notification switch")
    retry_count: Optional[int] = Field(None, ge=0, le=99, description="Retry count per task, default 3")

    if field_validator is not None:
        @field_validator("name")
        @classmethod
        def name_must_be_valid_filename(cls, v: str) -> str:
            if not v or not v.strip():
                raise ValueError("任务名称不能为空")
            if '/' in v or '\\' in v:
                raise ValueError('任务名称不能包含路径分隔符: / \\')
            return v.strip()
    else:
        @validator("name", allow_reuse=True)
        def name_must_be_valid_filename(cls, v: str) -> str:
            if not v or not v.strip():
                raise ValueError("任务名称不能为空")
            if '/' in v or '\\' in v:
                raise ValueError('任务名称不能包含路径分隔符: / \\')
            return v.strip()


class SignTaskUpdate(BaseModel):
    account_names: Optional[List[str]] = Field(None, description="Associated accounts")
    sign_at: Optional[str] = Field(None, description="Schedule cron")
    chats: Optional[List[ChatConfig]] = Field(None, description="Chat configs")
    random_seconds: Optional[int] = Field(None, description="Random delay seconds")
    sign_interval: Optional[int] = Field(None, description="Action interval seconds")
    execution_mode: Optional[str] = Field(None, description="fixed/range")
    range_start: Optional[str] = Field(None, description="Range start")
    range_end: Optional[str] = Field(None, description="Range end")
    notify_on_failure: Optional[bool] = Field(None, description="Failure notification switch")
    notify_on_success: Optional[bool] = Field(None, description="Success notification switch")
    retry_count: Optional[int] = Field(None, ge=0, le=99, description="Retry count per task")


class LastRunInfo(BaseModel):
    time: str
    success: bool
    message: str = ""


class ActiveRunSummary(BaseModel):
    """任务列表 / 活跃运行轻量摘要。"""

    run_id: str = ""
    state: str = "running"
    phase: Optional[str] = None
    phase_detail: str = ""
    account_name: str = ""
    task_name: str = ""
    started_at: Optional[str] = None
    wait_seconds: Optional[float] = None


class ActiveRunsResponse(BaseModel):
    runs: List[ActiveRunSummary] = Field(default_factory=list)


class SignTaskOut(BaseModel):
    name: str
    account_name: str = ""
    account_names: List[str] = Field(default_factory=list)
    sign_at: str
    chats: List[Dict[str, Any]]
    random_seconds: int
    sign_interval: int
    enabled: bool
    last_run: Optional[LastRunInfo] = None
    execution_mode: Optional[str] = "fixed"
    range_start: Optional[str] = None
    range_end: Optional[str] = None
    notify_on_failure: bool = True
    notify_on_success: bool = True
    task_group_id: str = ""
    last_run_account_name: str = ""
    retry_count: int = 3
    active_run: Optional[ActiveRunSummary] = None


class ChatOut(BaseModel):
    id: int
    title: Optional[str] = None
    username: Optional[str] = None
    type: str
    first_name: Optional[str] = None


class ChatSearchResponse(BaseModel):
    items: List[ChatOut]
    total: int
    limit: int
    offset: int


class RunTaskResult(BaseModel):
    success: bool
    output: str
    error: str


class RunTaskStartResult(BaseModel):
    run_id: str
    state: str
    success: Optional[bool] = None
    error: str = ""
    output: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    phase: Optional[str] = None
    phase_detail: str = ""
    wait_seconds: Optional[float] = None
    account_name: str = ""
    task_name: str = ""
    failure_category: Optional[str] = None
    timeout_seconds: Optional[float] = None
    retry_count_effective: Optional[int] = None


class RunTaskStatusResult(BaseModel):
    run_id: str
    state: str
    success: Optional[bool] = None
    error: str = ""
    output: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    phase: Optional[str] = None
    phase_detail: str = ""
    wait_seconds: Optional[float] = None
    account_name: str = ""
    task_name: str = ""
    failure_category: Optional[str] = None
    timeout_seconds: Optional[float] = None
    retry_count_effective: Optional[int] = None


class CancelRunResult(BaseModel):
    ok: bool
    cancelled: bool = False
    error: str = ""
    status: Optional[RunTaskStatusResult] = None


class TaskHistoryItem(BaseModel):
    time: str
    success: bool
    message: str = ""
    flow_logs: List[str] = Field(default_factory=list)
    flow_truncated: bool = False
    flow_line_count: int = 0
    account_name: str = ""
    last_target_message: str = ""


@router.get("", response_model=List[SignTaskOut])
def list_sign_tasks(
    account_name: Optional[str] = None,
    aggregate: bool = Query(False),
    force_refresh: bool = Query(False),
    current_user=Depends(get_current_user),
):
    return get_sign_task_service().list_tasks(
        account_name=account_name,
        aggregate=aggregate,
        force_refresh=force_refresh,
    )


@router.get("/runs/active", response_model=ActiveRunsResponse)
def list_active_sign_task_runs(
    current_user=Depends(get_current_user),
):
    """当前内存中进行中的签到运行（供 Dashboard / 列表短轮询）。"""
    runs = get_sign_task_service().list_active_runs()
    return ActiveRunsResponse(runs=runs)


@router.post("", response_model=SignTaskOut, status_code=status.HTTP_201_CREATED)
async def create_sign_task(
    payload: SignTaskCreate,
    current_user=Depends(get_current_user),
):
    try:
        chats_dict = [_model_dump(chat) for chat in payload.chats]
        task = get_sign_task_service().create_task(
            task_name=payload.name,
            account_name=payload.account_name,
            account_names=payload.account_names,
            sign_at=payload.sign_at,
            chats=chats_dict,
            random_seconds=payload.random_seconds,
            sign_interval=payload.sign_interval,
            execution_mode=payload.execution_mode or "fixed",
            range_start=payload.range_start or "",
            range_end=payload.range_end or "",
            notify_on_failure=payload.notify_on_failure,
            notify_on_success=payload.notify_on_success,
            retry_count=payload.retry_count,
        )

        # 调度同步和监控重启放到后台执行，避免阻塞 HTTP 响应
        asyncio.ensure_future(_safe_background_sync())
        return task
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建任务失败: {str(e)}")


@router.get("/{task_name}", response_model=SignTaskOut)
def get_sign_task(
    task_name: str,
    account_name: Optional[str] = None,
    aggregate: bool = Query(False),
    current_user=Depends(get_current_user),
):
    try:
        task = get_sign_task_service().get_task(
            task_name,
            account_name=account_name,
            aggregate=aggregate,
        )
        if not task:
            raise HTTPException(status_code=404, detail=f"任务 {task_name} 不存在")
        return task
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e


@router.put("/{task_name}", response_model=SignTaskOut)
async def update_sign_task(
    task_name: str,
    payload: SignTaskUpdate,
    account_name: Optional[str] = None,
    current_user=Depends(get_current_user),
):
    try:
        # Normalize: treat empty string and wildcard as None for lookup
        effective_account = account_name if (account_name and account_name != "*") else None
        existing = get_sign_task_service().get_task(
            task_name,
            account_name=effective_account,
            aggregate=effective_account is None,
        )
        if not existing:
            raise HTTPException(status_code=404, detail=f"任务 {task_name} 不存在")

        # Resolve a real account_name for update_task (skip wildcard)
        resolved_account = effective_account or ""
        if not resolved_account:
            for name in existing.get("account_names", []):
                if name and name != "*":
                    resolved_account = name
                    break
            if not resolved_account:
                resolved_account = existing.get("account_name", "")
            if resolved_account == "*":
                resolved_account = ""

        chats_dict = (
            [_model_dump(chat) for chat in payload.chats]
            if payload.chats is not None
            else None
        )
        task = get_sign_task_service().update_task(
            task_name=task_name,
            account_name=resolved_account or None,
            account_names=payload.account_names,
            sign_at=payload.sign_at,
            chats=chats_dict,
            random_seconds=payload.random_seconds,
            sign_interval=payload.sign_interval,
            execution_mode=payload.execution_mode,
            range_start=payload.range_start,
            range_end=payload.range_end,
            notify_on_failure=payload.notify_on_failure,
            notify_on_success=payload.notify_on_success,
            retry_count=payload.retry_count,
        )

        # 调度同步和监控重启放到后台执行，避免阻塞 HTTP 响应
        asyncio.ensure_future(_safe_background_sync())
        return task
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新任务失败: {str(e)}")


@router.delete("/{task_name}", status_code=status.HTTP_200_OK)
async def delete_sign_task(
    task_name: str,
    account_name: Optional[str] = None,
    current_user=Depends(get_current_user),
):
    try:
        success = get_sign_task_service().delete_task(task_name, account_name=account_name)
        if not success:
            raise HTTPException(status_code=404, detail=f"任务 {task_name} 不存在")

        # 调度同步和监控重启放到后台执行，避免阻塞 HTTP 响应
        asyncio.ensure_future(_safe_background_sync())
        return {"ok": True}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e


@router.patch("/{task_name}/toggle-enabled", response_model=SignTaskOut)
async def toggle_sign_task_enabled(
    task_name: str,
    account_name: Optional[str] = None,
    current_user=Depends(get_current_user),
):
    """切换任务的启用/暂停状态"""
    try:
        effective_account = account_name if (account_name and account_name != "*") else None
        existing = get_sign_task_service().get_task(
            task_name,
            account_name=effective_account,
            aggregate=effective_account is None,
        )
        if not existing:
            raise HTTPException(status_code=404, detail=f"任务 {task_name} 不存在")

        resolved_account = effective_account or ""
        if not resolved_account:
            for name in existing.get("account_names", []):
                if name and name != "*":
                    resolved_account = name
                    break
            if not resolved_account:
                resolved_account = existing.get("account_name", "")
            if resolved_account == "*":
                resolved_account = ""

        current_enabled = bool(existing.get("enabled", True))
        task = get_sign_task_service().update_task(
            task_name=task_name,
            account_name=resolved_account or None,
            enabled=not current_enabled,
        )

        # 调度同步和监控重启放到后台执行，避免阻塞 HTTP 响应
        asyncio.ensure_future(_safe_background_sync())
        return task
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"切换任务状态失败: {str(e)}")


class CloneTaskRequest(BaseModel):
    new_name: str = Field(..., description="Cloned task name")
    account_name: Optional[str] = Field(None, description="Source account hint")


@router.post(
    "/{task_name}/clone",
    response_model=SignTaskOut,
    status_code=status.HTTP_201_CREATED,
)
async def clone_sign_task(
    task_name: str,
    payload: CloneTaskRequest,
    current_user=Depends(get_current_user),
):
    try:
        task = get_sign_task_service().clone_task(
            task_name=task_name,
            new_name=payload.new_name,
            account_name=payload.account_name,
        )
        return task
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"克隆任务失败: {e}",
        )


@router.post("/{task_name}/run", response_model=RunTaskResult)
async def run_sign_task(
    task_name: str,
    account_name: Optional[str] = None,
    current_user=Depends(get_current_user),
):
    try:
        resolved_account = account_name
        if not resolved_account or resolved_account == "*":
            task = get_sign_task_service().get_task(task_name, aggregate=True)
            if not task:
                raise HTTPException(status_code=404, detail=f"任务 {task_name} 不存在")
            for name in task.get("account_names", []):
                if name and name != "*":
                    resolved_account = name
                    break
            if not resolved_account or resolved_account == "*":
                resolved_account = task.get("account_name", "")
            if not resolved_account or resolved_account == "*":
                raise HTTPException(status_code=400, detail="无法确定执行账号")
        else:
            task = get_sign_task_service().get_task(task_name, account_name=resolved_account)
            if not task:
                raise HTTPException(status_code=404, detail=f"任务 {task_name} 不存在")
        return await get_sign_task_service().run_task_with_logs(resolved_account, task_name)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e


@router.post("/{task_name}/run/start", response_model=RunTaskStartResult)
async def start_sign_task_run(
    task_name: str,
    account_name: Optional[str] = None,
    current_user=Depends(get_current_user),
):
    try:
        # Resolve account_name: if not provided or wildcard, find first real account
        resolved_account = account_name
        if not resolved_account or resolved_account == "*":
            task = get_sign_task_service().get_task(task_name, aggregate=True)
            if not task:
                raise HTTPException(status_code=404, detail=f"任务 {task_name} 不存在")
            # Find first real account from account_names
            for name in task.get("account_names", []):
                if name and name != "*":
                    resolved_account = name
                    break
            if not resolved_account or resolved_account == "*":
                resolved_account = task.get("account_name", "")
            if not resolved_account or resolved_account == "*":
                raise HTTPException(status_code=400, detail="无法确定执行账号")
        else:
            task = get_sign_task_service().get_task(task_name, account_name=resolved_account)
            if not task:
                raise HTTPException(status_code=404, detail=f"任务 {task_name} 不存在")
        return await get_sign_task_service().start_task_run(resolved_account, task_name)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e


def _resolve_task_account(task_name: str, account_name: Optional[str]) -> str:
    """解析执行账号；无法确定时抛 HTTPException。"""
    resolved_account = account_name
    if not resolved_account or resolved_account == "*":
        task = get_sign_task_service().get_task(task_name, aggregate=True)
        if not task:
            raise HTTPException(status_code=404, detail=f"任务 {task_name} 不存在")
        for name in task.get("account_names", []):
            if name and name != "*":
                resolved_account = name
                break
        if not resolved_account or resolved_account == "*":
            resolved_account = task.get("account_name", "")
        if not resolved_account or resolved_account == "*":
            raise HTTPException(status_code=400, detail="无法确定执行账号")
    else:
        task = get_sign_task_service().get_task(task_name, account_name=resolved_account)
        if not task:
            raise HTTPException(status_code=404, detail=f"任务 {task_name} 不存在")
    return str(resolved_account)


@router.get("/{task_name}/run/status", response_model=RunTaskStatusResult)
def get_sign_task_run_status(
    task_name: str,
    account_name: Optional[str] = None,
    run_id: Optional[str] = None,
    current_user=Depends(get_current_user),
):
    try:
        resolved_account = _resolve_task_account(task_name, account_name)
        return get_sign_task_service().get_task_run_status(
            resolved_account,
            task_name,
            run_id=run_id,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e


@router.post("/{task_name}/run/cancel", response_model=CancelRunResult)
def cancel_sign_task_run(
    task_name: str,
    account_name: Optional[str] = None,
    run_id: Optional[str] = None,
    current_user=Depends(get_current_user),
):
    """取消进行中的签到运行。"""
    try:
        resolved_account = _resolve_task_account(task_name, account_name)
        result = get_sign_task_service().cancel_task_run(
            resolved_account,
            task_name,
            run_id=run_id,
        )
        # status 可能为纯 dict；校验失败时降级为 None，避免 500
        status_raw = result.get("status")
        status_model = None
        if isinstance(status_raw, dict) and status_raw.get("state") is not None:
            try:
                status_model = RunTaskStatusResult(**status_raw)
            except Exception:
                status_model = None
        return CancelRunResult(
            ok=bool(result.get("ok")),
            cancelled=bool(result.get("cancelled")),
            error=str(result.get("error") or ""),
            status=status_model,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e


@router.get("/{task_name}/logs", response_model=List[str])
def get_sign_task_logs(
    task_name: str,
    account_name: str | None = None,
    current_user=Depends(get_current_user),
):
    effective_account = account_name if (account_name and account_name != "*") else None
    return get_sign_task_service().get_active_logs(task_name, account_name=effective_account)


@router.get("/{task_name}/history", response_model=List[TaskHistoryItem])
def get_sign_task_history(
    task_name: str,
    account_name: Optional[str] = None,
    limit: int = Query(20, ge=1, le=200),
    current_user=Depends(get_current_user),
):
    try:
        # Treat empty string and wildcard as None (aggregate mode)
        effective_account = account_name if (account_name and account_name != "*") else None
        task = get_sign_task_service().get_task(
            task_name,
            account_name=effective_account,
            aggregate=effective_account is None,
        )
        if not task:
            raise HTTPException(status_code=404, detail=f"任务 {task_name} 不存在")

        return get_sign_task_service().get_task_history_logs(
            task_name=task_name,
            account_name=effective_account,
            limit=limit,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e


@router.get("/chats/{account_name}", response_model=List[ChatOut])
async def get_account_chats(
    account_name: str,
    force_refresh: bool = False,
    current_user=Depends(get_current_user),
):
    try:
        return await get_sign_task_service().get_account_chats(
            account_name,
            force_refresh=force_refresh,
        )
    except ValueError as e:
        detail = str(e)
        if (
            "登录已失效" in detail
            or "session_string" in detail
            or "Session 文件不存在" in detail
        ):
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"detail": detail, "code": "ACCOUNT_SESSION_INVALID"},
            )
        raise HTTPException(status_code=404, detail=detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取对话列表失败: {str(e)}")


@router.get("/chats/{account_name}/search", response_model=ChatSearchResponse)
def search_account_chats(
    account_name: str,
    q: str = "",
    limit: int = 50,
    offset: int = 0,
    current_user=Depends(get_current_user),
):
    try:
        return get_sign_task_service().search_account_chats(
            account_name,
            q,
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索对话列表失败: {str(e)}")


@router.get("/chats/{account_name}/avatar/{chat_id}")
async def get_chat_avatar(
    account_name: str,
    chat_id: int,
    current_user=Depends(get_current_user),
):
    """获取 Chat 对象的头像（带本地缓存）

    Cache strategy: avatar is keyed by chat_id only since the same chat
    has the same avatar regardless of which account fetches it.
    If the requested account can't find the chat, fall back to trying
    other available accounts.
    """
    import time

    from fastapi.responses import FileResponse, Response

    from backend.core.config import get_settings

    settings = get_settings()
    avatar_cache_dir = settings.resolve_workdir() / "avatars" / "chats"
    avatar_cache_dir.mkdir(parents=True, exist_ok=True)

    # Use chat_id-based cache (avatar is global per chat, not per account)
    cache_file = avatar_cache_dir / f"chat_{chat_id}.jpg"
    no_avatar_marker = avatar_cache_dir / f"chat_{chat_id}.no_avatar"

    # Legacy account-specific cache files (for backward compatibility)
    legacy_cache_file = avatar_cache_dir / f"{account_name}_{chat_id}.jpg"

    # If no-avatar marker is recent (7 days), return 404
    if no_avatar_marker.exists():
        age = time.time() - no_avatar_marker.stat().st_mtime
        if age < 604800:
            raise HTTPException(status_code=404, detail="No avatar available")
        else:
            no_avatar_marker.unlink(missing_ok=True)

    # If chat-level cache exists and is fresh, use it
    if cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < 604800:
            return FileResponse(cache_file, media_type="image/jpeg")

    # If legacy account-specific cache exists, migrate it to chat-level
    if legacy_cache_file.exists():
        age = time.time() - legacy_cache_file.stat().st_mtime
        if age < 604800:
            try:
                import shutil
                shutil.copy2(legacy_cache_file, cache_file)
            except Exception:
                pass
            return FileResponse(cache_file, media_type="image/jpeg")

    # Try to download avatar - first with the requested account, then fall back
    from backend.services.telegram import get_telegram_service
    from backend.utils.tg_session import list_account_names

    telegram_service = get_telegram_service()
    accounts_to_try = [account_name]
    # Add other accounts as fallback
    try:
        all_accounts = list_account_names()
        for acc in all_accounts:
            if acc and acc != account_name and acc not in accounts_to_try:
                accounts_to_try.append(acc)
    except Exception:
        pass

    for try_account in accounts_to_try:
        try:
            avatar_bytes = await telegram_service.download_chat_avatar(
                try_account, chat_id
            )
            if avatar_bytes:
                cache_file.write_bytes(avatar_bytes)
                no_avatar_marker.unlink(missing_ok=True)
                return Response(content=avatar_bytes, media_type="image/jpeg")
        except Exception:
            continue

    # No account could fetch the avatar - mark as no avatar
    try:
        no_avatar_marker.write_text("")
    except Exception:
        pass

    raise HTTPException(status_code=404, detail="No avatar available")


@router.websocket("/ws/{task_name}")
async def sign_task_logs_ws(
    websocket: WebSocket,
    task_name: str,
    account_name: str | None = Query(None),
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    try:
        user = verify_token(token, db)
        if not user:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    # Resolve empty/wildcard account_name to None for broader matching
    effective_account = account_name if (account_name and account_name != "*") else None

    last_idx = 0
    connected_at = asyncio.get_running_loop().time()
    seen_activity = False
    # 仅在 phase/state 等变化时推 status，避免 0.5s 心跳刷屏
    last_status_sig = None  # type: ignore[var-annotated]
    try:
        while True:
            active_logs = get_sign_task_service().get_active_logs(
                task_name,
                account_name=effective_account,
            )
            is_running = get_sign_task_service().is_task_running(
                task_name,
                account_name=effective_account,
            )
            if is_running or bool(active_logs):
                seen_activity = True

            run_status = {}
            try:
                if effective_account:
                    run_status = get_sign_task_service().get_task_run_status(
                        effective_account,
                        task_name,
                    )
            except Exception:
                run_status = {}

            status_payload = {
                "phase": run_status.get("phase"),
                "phase_detail": run_status.get("phase_detail") or "",
                "failure_category": run_status.get("failure_category"),
                "state": run_status.get("state"),
                "wait_seconds": run_status.get("wait_seconds"),
            }
            status_sig = (
                status_payload.get("phase"),
                status_payload.get("phase_detail"),
                status_payload.get("state"),
                status_payload.get("failure_category"),
                status_payload.get("wait_seconds"),
                is_running,
            )

            if len(active_logs) > last_idx:
                new_logs = active_logs[last_idx:]
                await websocket.send_json(
                    {
                        "type": "logs",
                        "data": new_logs,
                        "is_running": is_running,
                        **status_payload,
                    }
                )
                last_idx = len(active_logs)
                last_status_sig = status_sig
            elif is_running and run_status and status_sig != last_status_sig:
                # phase 变化时推送，避免卡在 starting 展示
                await websocket.send_json(
                    {
                        "type": "status",
                        "is_running": True,
                        **status_payload,
                    }
                )
                last_status_sig = status_sig

            if (
                not is_running
                and last_idx >= len(active_logs)
                and (
                    seen_activity
                    or asyncio.get_running_loop().time() - connected_at >= 15
                )
            ):
                await websocket.send_json(
                    {
                        "type": "done",
                        "is_running": False,
                        **status_payload,
                    }
                )
                break

            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass

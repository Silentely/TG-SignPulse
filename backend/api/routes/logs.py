from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.models.login_log import LoginLog
from backend.models.user import User
from backend.services.sign_tasks import get_sign_task_service
from backend.utils.task_logs import extract_last_target_message

router = APIRouter()


class LoginLogItem(BaseModel):
    id: int
    username: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    detail: Optional[str] = None
    success: bool
    created_at: str


class TaskHistoryLogItem(BaseModel):
    id: int
    account_name: str
    task_name: str
    message: str
    summary: Optional[str] = None
    bot_message: Optional[str] = None
    success: bool
    created_at: str
    flow_line_count: int = 0


class TaskHistoryLogDetailItem(TaskHistoryLogItem):
    flow_logs: list[str] = []
    flow_truncated: bool = False
    last_target_message: Optional[str] = None


class ClearLogsResponse(BaseModel):
    success: bool
    cleared: int
    message: str


class DeleteLogResponse(BaseModel):
    success: bool
    message: str


def _normalize_date_filter(date: Optional[str]) -> Optional[datetime]:
    if not date:
        return None
    try:
        return datetime.strptime(str(date).strip(), "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="INVALID_DATE_FILTER",
        ) from exc


@router.get("/login", response_model=list[LoginLogItem])
def get_login_logs(
    limit: int = 100,
    date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    del current_user

    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500

    filter_date = _normalize_date_filter(date)
    query = db.query(LoginLog)
    if filter_date is not None:
        next_day = filter_date + timedelta(days=1)
        query = query.filter(
            LoginLog.created_at >= filter_date,
            LoginLog.created_at < next_day,
        )

    rows = query.order_by(LoginLog.created_at.desc()).limit(limit).all()
    return [
        LoginLogItem(
            id=row.id,
            username=row.username,
            ip_address=row.ip_address,
            user_agent=row.user_agent,
            detail=row.detail,
            success=bool(row.success),
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]


@router.post("/login/clear", response_model=ClearLogsResponse)
def clear_login_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    del current_user

    cleared = db.query(LoginLog).delete()
    db.commit()
    return ClearLogsResponse(success=True, cleared=cleared, message="Login logs cleared")


@router.delete("/login/{log_id}", response_model=DeleteLogResponse)
def delete_login_log(
    log_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    del current_user

    row = db.query(LoginLog).filter(LoginLog.id == log_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="LOGIN_LOG_NOT_FOUND")

    db.delete(row)
    db.commit()
    return DeleteLogResponse(success=True, message="Login log deleted")


@router.get("/tasks", response_model=list[TaskHistoryLogItem])
def get_task_logs(
    limit: int = 100,
    account_name: Optional[str] = None,
    date: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    del current_user
    _normalize_date_filter(date)

    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500

    history = get_sign_task_service().get_filtered_history_logs(
        account_name=account_name,
        date=date,
        limit=limit,
    )

    return [
        TaskHistoryLogItem(
            id=index + 1,
            account_name=str(item.get("account_name") or ""),
            task_name=str(item.get("task_name") or "Unknown Task"),
            message=str(item.get("message") or ""),
            summary=(
                f"Task: {str(item.get('task_name') or 'Unknown Task')} "
                f"{'success' if bool(item.get('success')) else 'failed'}"
            ),
            bot_message=str(item.get("last_target_message") or "").strip()
            or extract_last_target_message(item.get("flow_logs")),
            success=bool(item.get("success", False)),
            created_at=str(item.get("time") or ""),
            flow_line_count=int(item.get("flow_line_count") or 0),
        )
        for index, item in enumerate(history)
    ]


@router.get("/tasks/item", response_model=TaskHistoryLogDetailItem)
def get_task_log_detail(
    account_name: str,
    task_name: str,
    created_at: str,
    current_user: User = Depends(get_current_user),
):
    del current_user

    detail = get_sign_task_service().get_history_log_detail(
        account_name=account_name,
        task_name=task_name,
        created_at=created_at,
    )
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="TASK_LOG_NOT_FOUND")

    return TaskHistoryLogDetailItem(
        id=1,
        account_name=str(detail.get("account_name") or ""),
        task_name=str(detail.get("task_name") or "Unknown Task"),
        message=str(detail.get("message") or ""),
        summary=(
            f"Task: {str(detail.get('task_name') or 'Unknown Task')} "
            f"{'success' if bool(detail.get('success')) else 'failed'}"
        ),
        bot_message=str(detail.get("last_target_message") or "").strip()
        or extract_last_target_message(detail.get("flow_logs")),
        success=bool(detail.get("success", False)),
        created_at=str(detail.get("time") or ""),
        flow_line_count=int(detail.get("flow_line_count") or 0),
        flow_logs=[str(line) for line in detail.get("flow_logs") or []],
        flow_truncated=bool(detail.get("flow_truncated", False)),
        last_target_message=str(detail.get("last_target_message") or "").strip() or None,
    )


@router.post("/tasks/clear", response_model=ClearLogsResponse)
def clear_task_logs(current_user: User = Depends(get_current_user)):
    del current_user

    result = get_sign_task_service().clear_all_history_logs()
    return ClearLogsResponse(
        success=True,
        cleared=int(result.get("removed_entries", 0)),
        message="Task logs cleared",
    )


@router.delete("/tasks/item", response_model=DeleteLogResponse)
def delete_task_log(
    account_name: str,
    task_name: str,
    created_at: str,
    current_user: User = Depends(get_current_user),
):
    del current_user

    deleted = get_sign_task_service().delete_history_log(
        account_name=account_name,
        task_name=task_name,
        created_at=created_at,
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="TASK_LOG_NOT_FOUND")

    return DeleteLogResponse(success=True, message="Task log deleted")

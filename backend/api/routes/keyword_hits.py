"""关键词命中记录 API：列表、分组、CSV 导出、清空。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from backend.core.auth import get_current_user
from backend.models.user import User
from backend.services.keyword_monitor.hits import (
    clear_keyword_hits,
    export_keyword_hits_csv,
    group_keyword_hits,
    list_keyword_hits,
)

router = APIRouter()


@router.get("")
def list_hits(
    account_name: Optional[str] = None,
    task_name: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
):
    return list_keyword_hits(
        account_name=account_name,
        task_name=task_name,
        limit=limit,
        offset=offset,
    )


@router.get("/groups")
def list_hit_groups(
    account_name: Optional[str] = None,
    task_name: Optional[str] = None,
    group_by: str = Query("task"),
    limit_per_group: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
):
    normalized = (group_by or "task").strip().lower()
    if normalized not in {"task", "account", "chat"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="group_by 仅支持 task / account / chat",
        )
    return group_keyword_hits(
        account_name=account_name,
        task_name=task_name,
        group_by=normalized,
        limit_per_group=limit_per_group,
    )


@router.get("/export")
def export_hits(
    account_name: Optional[str] = None,
    task_name: Optional[str] = None,
    limit: int = Query(2000, ge=1, le=5000),
    current_user: User = Depends(get_current_user),
):
    csv_text = export_keyword_hits_csv(
        account_name=account_name,
        task_name=task_name,
        limit=limit,
    )
    # UTF-8 BOM 便于 Excel 识别中文
    payload = "\ufeff" + csv_text
    filename = "keyword_hits.csv"
    return Response(
        content=payload.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.delete("")
def delete_hits(
    account_name: Optional[str] = None,
    task_name: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    deleted = clear_keyword_hits(account_name=account_name, task_name=task_name)
    return {"ok": True, "deleted": deleted}

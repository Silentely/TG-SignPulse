"""任务模板最小 API:创建 / 列出 / 更新模板,列出引用某模板的任务。

模板存储在 ``<workdir>/task_templates.json``;更新模板时会把公共字段
同步到所有引用它的任务(账号私有字段与 enabled 等任务级开关保持不变)。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.core.auth import get_current_user
from backend.services.sign_task_templates import (
    TaskTemplateStore,
    list_tasks_using_template,
    sync_template_to_tasks,
)
from backend.services.sign_tasks import get_sign_task_service

logger = logging.getLogger("backend.sign_task_templates_api")

router = APIRouter()


def _get_store() -> TaskTemplateStore:
    return TaskTemplateStore(get_sign_task_service().workdir)


class TemplateCreate(BaseModel):
    name: str = Field(..., description="Template name")
    description: str = Field("", description="Template description")
    fields: Dict[str, Any] = Field(
        default_factory=dict, description="Public task config fields"
    )


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    fields: Optional[Dict[str, Any]] = None


class TemplateOut(BaseModel):
    id: str
    name: str
    description: str = ""
    fields: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


class TemplateSyncResult(BaseModel):
    template: TemplateOut
    synced_tasks: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


@router.get("", response_model=List[TemplateOut])
def list_templates(current_user=Depends(get_current_user)):
    return _get_store().list_templates()


@router.post("", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(payload: TemplateCreate, current_user=Depends(get_current_user)):
    try:
        return _get_store().create_template(
            name=payload.name,
            description=payload.description,
            fields=payload.fields,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.put("/{template_id}", response_model=TemplateSyncResult)
def update_template(
    template_id: str,
    payload: TemplateUpdate,
    current_user=Depends(get_current_user),
):
    store = _get_store()
    try:
        template = store.update_template(
            template_id,
            name=payload.name,
            description=payload.description,
            fields=payload.fields,
        )
    except ValueError as exc:
        status_code = (
            status.HTTP_404_NOT_FOUND
            if str(exc) == "模板不存在"
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    warnings: List[str] = []
    synced: List[Dict[str, Any]] = []
    try:
        synced = sync_template_to_tasks(get_sign_task_service(), template)
    except Exception as exc:
        # 配置已保存;同步失败不能整体 500,返回警告供前端提示
        logger.error("模板 %s 同步任务失败: %s", template_id, exc, exc_info=True)
        warnings.append(f"模板已保存,但同步任务失败: {exc}")

    result: Dict[str, Any] = {"template": template, "synced_tasks": synced}
    if warnings:
        result["warnings"] = warnings
    return result


@router.get("/{template_id}/tasks")
def list_template_tasks(template_id: str, current_user=Depends(get_current_user)):
    store = _get_store()
    if store.get_template(template_id) is None:
        raise HTTPException(status_code=404, detail="TEMPLATE_NOT_FOUND")
    return list_tasks_using_template(get_sign_task_service(), template_id)

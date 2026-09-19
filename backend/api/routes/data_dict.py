from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.core.auth import get_current_user
from backend.models.user import User
from backend.services.data_dict import get_data_dict_service

router = APIRouter()
logger = logging.getLogger("backend.data_dict_api")


class DataDictMeta(BaseModel):
    name: str
    count: int
    remark: str = ""
    updated_at: str = ""


class DataDictDetail(BaseModel):
    name: str
    entries: List[str]
    cursor: int = 0
    remark: str = ""
    updated_at: str = ""


class SaveDataDictRequest(BaseModel):
    name: str = Field(..., description="字典名称，仅支持字母、数字、下划线、短横线")
    entries: List[str] = Field(..., description="词条列表")
    remark: Optional[str] = Field(default="", description="字典备注说明")


class SampleEntryResponse(BaseModel):
    name: str
    entry: str
    mode: str = "random"


class OkResponse(BaseModel):
    ok: bool = True


@router.get("", response_model=List[DataDictMeta])
@router.get("/", response_model=List[DataDictMeta], include_in_schema=False)
def list_data_dicts(_user: User = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """列出所有数据字典元信息。"""
    service = get_data_dict_service()
    return service.list_dicts()


@router.post("", response_model=OkResponse)
@router.post("/", response_model=OkResponse, include_in_schema=False)
def save_data_dict(
    payload: SaveDataDictRequest,
    _user: User = Depends(get_current_user),
) -> Dict[str, bool]:
    """创建或保存数据字典。"""
    service = get_data_dict_service()
    try:
        service.save_dict(payload.name, payload.entries, remark=payload.remark or "")
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.get("/{name}", response_model=DataDictDetail)
def get_data_dict_detail(
    name: str,
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """获取指定数据字典详情及全部条目。"""
    service = get_data_dict_service()
    try:
        return service.get_dict(name)
    except ValueError as exc:
        code = str(exc)
        if code == "DATA_DICT_NOT_FOUND":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="DATA_DICT_NOT_FOUND",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=code,
        )


@router.delete("/{name}", response_model=OkResponse)
def delete_data_dict(
    name: str,
    _user: User = Depends(get_current_user),
) -> Dict[str, bool]:
    """删除指定数据字典。"""
    service = get_data_dict_service()
    service.delete_dict(name)
    return {"ok": True}


@router.get("/{name}/sample", response_model=SampleEntryResponse)
def sample_data_dict_entry(
    name: str,
    mode: Literal["random", "round_robin"] = Query("random", description="抽取模式: random 或 round_robin"),
    _user: User = Depends(get_current_user),
) -> Dict[str, str]:
    """抽取单条词条样本预览。"""
    service = get_data_dict_service()
    try:
        entry = service.get_entry(name, mode=mode)
        return {"name": name, "entry": entry, "mode": mode}
    except ValueError as exc:
        code = str(exc)
        if code == "DATA_DICT_NOT_FOUND":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="DATA_DICT_NOT_FOUND",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=code,
        )

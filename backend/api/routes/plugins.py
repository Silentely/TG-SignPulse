"""Plugin management API routes."""
from __future__ import annotations

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.core.auth import get_current_user
from backend.models.user import User
from tg_signer.core.plugins import PluginRegistry

router = APIRouter()
logger = logging.getLogger("backend.plugins_api")


class PluginInfo(BaseModel):
    name: str
    mode: str
    description: str = ""
    source_path: Optional[str] = None


class ReloadPluginsResponse(BaseModel):
    count: int
    plugins: List[PluginInfo]


@router.get("", response_model=List[PluginInfo])
async def list_plugins(_user: User = Depends(get_current_user)) -> List[PluginInfo]:
    """获取所有已加载的自定义插件列表。"""
    plugins = PluginRegistry.list_plugins()
    return [
        PluginInfo(
            name=p.name,
            mode=p.mode,
            description=p.description,
            source_path=p.source_path,
        )
        for p in plugins.values()
    ]


@router.post("/reload", response_model=ReloadPluginsResponse)
async def reload_plugins(_user: User = Depends(get_current_user)) -> ReloadPluginsResponse:
    """重新扫描并加载所有配置的插件目录。"""
    PluginRegistry.reload_all_plugins()
    plugins = PluginRegistry.list_plugins()
    res_list = [
        PluginInfo(
            name=p.name,
            mode=p.mode,
            description=p.description,
            source_path=p.source_path,
        )
        for p in plugins.values()
    ]
    logger.info("已重新加载自定义插件，当前共 %d 个可用插件", len(res_list))
    return ReloadPluginsResponse(count=len(res_list), plugins=res_list)

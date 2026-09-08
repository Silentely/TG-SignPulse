"""Plugin management API routes."""
from __future__ import annotations

import asyncio
import inspect
import logging
import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.core.auth import get_current_user
from backend.models.user import User
from tg_signer.core.plugins import PluginContext, PluginRegistry

router = APIRouter()
logger = logging.getLogger("backend.plugins_api")


class PluginInfo(BaseModel):
    name: str
    mode: str
    description: str = ""
    source_path: Optional[str] = None
    params_schema: List[Dict[str, Any]] = Field(default_factory=list)


class ReloadPluginsResponse(BaseModel):
    count: int
    plugins: List[PluginInfo]


class PluginTestRequest(BaseModel):
    text: str = Field(default="", description="模拟接收到的 Telegram 消息文本")
    params: Dict[str, Any] = Field(default_factory=dict, description="插件自定义参数")


class PluginTestResponse(BaseModel):
    name: str
    success: bool
    handled: bool
    reply_text: Optional[str] = None
    sent_messages: List[str] = Field(default_factory=list)
    logs: List[str] = Field(default_factory=list)
    duration_ms: float = 0.0
    error: Optional[str] = None


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
            params_schema=p.params_schema or [],
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
            params_schema=p.params_schema or [],
        )
        for p in plugins.values()
    ]
    logger.info("已重新加载自定义插件，当前共 %d 个可用插件", len(res_list))
    return ReloadPluginsResponse(count=len(res_list), plugins=res_list)


@router.post("/{name}/test", response_model=PluginTestResponse)
async def test_plugin(
    name: str,
    req: PluginTestRequest,
    _user: User = Depends(get_current_user),
) -> PluginTestResponse:
    """在 Web 调试沙箱中模拟单测指定插件。"""
    meta = PluginRegistry.get(name)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"插件 '{name}' 未找到或未加载",
        )

    captured_logs: List[str] = []
    reply_record: List[str] = []
    sent_records: List[str] = []

    def log_capture(msg: str):
        captured_logs.append(str(msg))

    class MockMessage:
        def __init__(self, text: str):
            self.text = text
            self.id = 999999

        async def reply(self, reply_text: str, **_kwargs):
            reply_record.append(str(reply_text))
            return self

        async def click(self, _button_text_or_idx, **_kwargs):
            captured_logs.append("[mock] 点击了消息按钮")
            return True

    class MockApp:
        async def send_message(self, _chat_id, text: str, **kwargs):
            sent_records.append(str(text))
            if 'reply_to_message_id' in kwargs:
                reply_record.append(str(text))
            return MockMessage(text)

    mock_msg = MockMessage(req.text)
    mock_app = MockApp()

    ctx = PluginContext(
        app=mock_app,
        chat_id=12345678,
        message=mock_msg,
        params=req.params,
        logger=log_capture,
    )

    start_t = time.perf_counter()
    success = True
    handled = False
    err_str = None

    try:
        # 支持同步或异步执行
        if inspect.iscoroutinefunction(meta.handler):
            res = await asyncio.wait_for(meta.handler(ctx), timeout=5.0)
        else:
            loop = asyncio.get_running_loop()
            res = await asyncio.wait_for(
                loop.run_in_executor(None, meta.handler, ctx),
                timeout=5.0,
            )

        handled = bool(res) if res is not None else False
    except asyncio.TimeoutError:
        success = False
        err_str = "插件执行超时（沙箱限制 5 秒）"
        captured_logs.append(f"[error] {err_str}")
    except Exception as exc:
        success = False
        err_str = f"插件执行异常: {exc}"
        captured_logs.append(f"[error] {err_str}")

    duration_ms = round((time.perf_counter() - start_t) * 1000, 2)

    return PluginTestResponse(
        name=name,
        success=success,
        handled=handled,
        reply_text=(reply_record[-1] if reply_record else (sent_records[-1] if sent_records else None)),
        sent_messages=sent_records,
        logs=captured_logs,
        duration_ms=duration_ms,
        error=err_str,
    )

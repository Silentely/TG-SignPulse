"""Plugin management API routes."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.core.auth import get_current_user
from backend.models.user import User
from tg_signer.core.plugin_host import PluginProcessHost
from tg_signer.core.plugins import PluginContext, PluginRegistry, is_builtin_plugin_path

router = APIRouter()
logger = logging.getLogger("backend.plugins_api")


def _safe_source_path(source_path: Optional[str]) -> Optional[str]:
    """仅返回插件目录和文件名，避免泄露宿主机绝对路径。"""
    if not source_path:
        return None
    path = Path(source_path)
    return "/".join(path.parts[-2:])


def _get_disabled_plugins() -> set[str]:
    try:
        from backend.services.config import get_config_service
        settings = get_config_service().get_global_settings() or {}
        return set(settings.get("disabled_plugins", []))
    except Exception:
        return set()


class PluginInfo(BaseModel):
    name: str
    mode: str
    description: str = ""
    source_path: Optional[str] = None
    params_schema: List[Dict[str, Any]] = Field(default_factory=list)
    enabled: bool = True
    builtin: bool = False
    permissions: List[str] = Field(default_factory=list)


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
    isolation: str = "in_process"
    killed: bool = False
    reply_text: Optional[str] = None
    sent_messages: List[str] = Field(default_factory=list)
    reacted_emojis: List[str] = Field(default_factory=list)
    logs: List[str] = Field(default_factory=list)
    duration_ms: float = 0.0
    error: Optional[str] = None


@router.get("", response_model=List[PluginInfo])
async def list_plugins(_user: User = Depends(get_current_user)) -> List[PluginInfo]:
    """获取所有已加载的自定义插件列表。"""
    plugins = PluginRegistry.list_plugins()
    disabled_set = _get_disabled_plugins()
    for name in plugins:
        PluginRegistry.set_disabled(name, disabled=name in disabled_set)

    return [
        PluginInfo(
            name=p.name,
            mode=p.mode,
            description=p.description,
            source_path=_safe_source_path(p.source_path),
            params_schema=p.params_schema or [],
            enabled=p.name not in disabled_set,
            builtin=getattr(p, "builtin", False),
            permissions=getattr(p, "permissions", []),
        )
        for p in plugins.values()
    ]


@router.post("/reload", response_model=ReloadPluginsResponse)
async def reload_plugins(
    _user: User = Depends(get_current_user),
) -> ReloadPluginsResponse:
    """重新扫描并加载所有配置的插件目录。"""
    PluginRegistry.reload_all_plugins()
    plugins = PluginRegistry.list_plugins()
    disabled_set = _get_disabled_plugins()
    for name in plugins:
        PluginRegistry.set_disabled(name, disabled=name in disabled_set)

    res_list = [
        PluginInfo(
            name=p.name,
            mode=p.mode,
            description=p.description,
            source_path=_safe_source_path(p.source_path),
            params_schema=p.params_schema or [],
            enabled=p.name not in disabled_set,
            builtin=getattr(p, "builtin", False),
            permissions=getattr(p, "permissions", []),
        )
        for p in plugins.values()
    ]
    logger.info("已重新加载自定义插件，当前共 %d 个可用插件", len(res_list))
    return ReloadPluginsResponse(count=len(res_list), plugins=res_list)


@router.post("/{name}/toggle", response_model=PluginInfo)
async def toggle_plugin(
    name: str,
    _user: User = Depends(get_current_user),
) -> PluginInfo:
    """切换插件的启用/停用软开关状态。"""
    meta = PluginRegistry.get(name)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"插件 '{name}' 未找到或未加载",
        )

    try:
        from backend.services.config import get_config_service
        cfg_svc = get_config_service()
        settings = dict(cfg_svc.get_global_settings() or {})
        disabled_list = list(settings.get("disabled_plugins", []))
    except Exception:
        cfg_svc = None
        disabled_list = []

    currently_disabled = name in disabled_list
    new_disabled = not currently_disabled

    if new_disabled:
        if name not in disabled_list:
            disabled_list.append(name)
    else:
        if name in disabled_list:
            disabled_list.remove(name)

    if cfg_svc is not None:
        settings["disabled_plugins"] = disabled_list
        cfg_svc.save_global_settings(settings)

    PluginRegistry.set_disabled(name, disabled=new_disabled)

    return PluginInfo(
        name=meta.name,
        mode=meta.mode,
        description=meta.description,
        source_path=_safe_source_path(meta.source_path),
        params_schema=meta.params_schema or [],
        enabled=not new_disabled,
        builtin=getattr(meta, "builtin", False),
    )


@router.post("/{name}/test", response_model=PluginTestResponse)
async def test_plugin(
    name: str,
    req: PluginTestRequest,
    _user: User = Depends(get_current_user),
) -> PluginTestResponse:
    """在宿主进程内模拟执行指定插件，仅用于测试可信插件。"""
    meta = PluginRegistry.get(name)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"插件 '{name}' 未找到或未加载",
        )

    captured_logs: List[str] = []
    reply_record: List[str] = []
    sent_records: List[str] = []
    reacted_records: List[str] = []

    def log_capture(msg: str):
        captured_logs.append(str(msg))

    class MockChat:
        id = 12345678
        title = "MockChat"
        type = "private"

    class MockMessage:
        def __init__(self, text: str):
            self.text = text
            self.caption = None
            self.id = 999999
            self.chat = MockChat()
            self.chat_id = 12345678

        async def reply(self, reply_text: str, **_kwargs):
            reply_record.append(str(reply_text))
            return self

        async def click(self, _button_text_or_idx, **_kwargs):
            captured_logs.append("[mock] 点击了消息按钮")
            return True

        async def react(self, emoji: str, **_kwargs):
            reacted_records.append(str(emoji))
            captured_logs.append(f"[mock] 对消息表态表情: {emoji}")
            return True

    class MockApp:
        async def send_message(self, _chat_id, text: str, **kwargs):
            sent_records.append(str(text))
            if "reply_to_message_id" in kwargs:
                reply_record.append(str(text))
            return MockMessage(text)

        async def send_reaction(self, _chat_id, message_id: int, emoji: str, **_kwargs):
            reacted_records.append(str(emoji))
            captured_logs.append(f"[mock] 对消息 {message_id} 表态表情: {emoji}")
            return True

    mock_msg = MockMessage(req.text)
    mock_app = MockApp()

    ctx = PluginContext(
        app=mock_app,
        chat_id=12345678,
        message=mock_msg,
        params=req.params,
        logger=log_capture,
        plugin_name=name,
    )

    try:
        test_timeout = float(os.getenv("PLUGIN_TEST_TIMEOUT", "5.0"))
        if test_timeout <= 0:
            test_timeout = 5.0
    except (ValueError, TypeError):
        test_timeout = 5.0

    engine = os.getenv("PLUGIN_ISOLATION_ENGINE", "auto").lower()
    use_subprocess = engine == "process" or (
        engine == "auto" and not inspect.iscoroutinefunction(meta.handler)
    )
    isolation = "subprocess" if use_subprocess else "in_process"
    killed = False

    start_t = time.perf_counter()
    success = True
    handled = False
    err_str = None

    if use_subprocess:
        host = PluginProcessHost(plugin_name=name, ctx=ctx, timeout=test_timeout)
        try:
            res = await host.execute()
            handled = bool(res) if res is not None else False
        except TimeoutError:
            success = False
            killed = host.process_terminated_by_kill
            timeout_display = (
                int(test_timeout) if test_timeout.is_integer() else test_timeout
            )
            err_str = f"插件执行超时（沙箱限制 {timeout_display} 秒）"
            captured_logs.append(f"[error] {err_str}")
        except Exception as exc:
            success = False
            err_str = f"插件执行异常: {exc}"
            captured_logs.append(f"[error] {err_str}")
    else:
        try:
            # 支持同步或异步执行
            if inspect.iscoroutinefunction(meta.handler):
                res = await asyncio.wait_for(meta.handler(ctx), timeout=test_timeout)
            else:
                loop = asyncio.get_running_loop()
                res = await asyncio.wait_for(
                    loop.run_in_executor(None, meta.handler, ctx),
                    timeout=test_timeout,
                )

            handled = bool(res) if res is not None else False
        except asyncio.TimeoutError:
            success = False
            timeout_display = (
                int(test_timeout) if test_timeout.is_integer() else test_timeout
            )
            err_str = f"插件执行超时（沙箱限制 {timeout_display} 秒）"
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
        isolation=isolation,
        killed=killed,
        reply_text=(
            reply_record[-1]
            if reply_record
            else (sent_records[-1] if sent_records else None)
        ),
        sent_messages=sent_records,
        reacted_emojis=reacted_records,
        logs=captured_logs,
        duration_ms=duration_ms,
        error=err_str,
    )


class InstallRemotePluginRequest(BaseModel):
    url: str = Field(description="远程插件文件 URL (.py 或 raw gist/github)")
    filename: Optional[str] = Field(default=None, description="指定保存的文件名，如 custom_sign.py")


@router.post("/install-remote", response_model=PluginInfo)
async def install_remote_plugin(
    req: InstallRemotePluginRequest,
    _user: User = Depends(get_current_user),
) -> PluginInfo:
    """从远程 URL 下载并安装自定义插件。"""
    import ast
    import httpx
    import re

    import ipaddress
    import socket
    from urllib.parse import urlparse

    raw_url = req.url.strip()
    if not (raw_url.startswith("http://") or raw_url.startswith("https://")):
        raise HTTPException(status_code=400, detail="URL 必须以 http:// 或 https:// 开头")

    parsed_url = urlparse(raw_url)
    hostname = parsed_url.hostname or ""
    if not hostname:
        raise HTTPException(status_code=400, detail="无效的主机名")

    # SSRF 防护：严格禁止回环与局域网内网探测
    def _is_forbidden_target(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        if ip_obj.is_loopback or ip_obj.is_link_local:
            return True
        for net in (
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
            ipaddress.ip_network("169.254.0.0/16"),
        ):
            if ip_obj.version == net.version and ip_obj in net:
                return True
        return False

    try:
        ip = ipaddress.ip_address(hostname)
        if _is_forbidden_target(ip):
            raise HTTPException(status_code=400, detail="安全限制：禁止请求私有或内网地址")
    except ValueError:
        try:
            addr_info = socket.getaddrinfo(hostname, None)
            for addr in addr_info:
                ip_str = addr[4][0]
                ip = ipaddress.ip_address(ip_str)
                if _is_forbidden_target(ip):
                    raise HTTPException(status_code=400, detail="安全限制：禁止请求私有或内网地址")
        except socket.gaierror:
            pass

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(raw_url)
            if resp.status_code != 200:
                raise HTTPException(status_code=400, detail=f"下载失败: HTTP {resp.status_code}")
            code_text = resp.text
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"无法拉取远程插件: {exc}")

    if len(code_text.encode("utf-8")) > 1024 * 1024:
        raise HTTPException(status_code=400, detail="插件文件大小超过 1MB 限制")

    try:
        ast.parse(code_text)
    except SyntaxError as exc:
        raise HTTPException(status_code=400, detail=f"插件代码语法错误: {exc}")

    # 确定保存目录
    custom_dirs = [d for d in PluginRegistry.get_search_directories() if not is_builtin_plugin_path(d)]
    target_dir = custom_dirs[0] if custom_dirs else Path.cwd() / "data" / "plugins"
    target_dir.mkdir(parents=True, exist_ok=True)

    fname = req.filename.strip() if req.filename else ""
    if not fname:
        parts = raw_url.rstrip("/").split("/")
        last_part = parts[-1].split("?")[0]
        if last_part.endswith(".py"):
            fname = last_part
        else:
            fname = f"plugin_{int(time.time())}.py"

    base_stem = fname[:-3].strip() if fname.endswith(".py") else fname.strip()
    safe_stem = re.sub(r"[^a-zA-Z0-9_-]", "_", base_stem).strip("_")
    if not safe_stem:
        safe_stem = f"plugin_{int(time.time())}"
    fname = f"{safe_stem}.py"
    dest_path = target_dir / fname
    dest_path.write_text(code_text, encoding="utf-8")

    # 重新加载插件
    PluginRegistry.reload_all_plugins()
    plugins = PluginRegistry.list_plugins()

    # 寻找匹配该文件的插件
    matched: Optional[PluginMeta] = None
    for p in plugins.values():
        if p.source_path and Path(p.source_path).name == fname:
            matched = p
            break

    if not matched:
        # 兜底返回最新加载的一个
        matched = list(plugins.values())[-1] if plugins else None

    if not matched:
        raise HTTPException(status_code=500, detail="插件文件已写入但未能成功加载")

    return PluginInfo(
        name=matched.name,
        mode=matched.mode,
        description=matched.description,
        source_path=_safe_source_path(matched.source_path),
        params_schema=matched.params_schema or [],
        enabled=True,
        builtin=False,
        permissions=getattr(matched, "permissions", []),
    )

"""Plugin management API routes."""

from __future__ import annotations

import asyncio
from datetime import datetime
import inspect
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.core.auth import get_current_user
from backend.models.user import User
from tg_signer.core.plugin_host import PluginProcessHost
from tg_signer.core.plugins import (
    PluginContext,
    PluginMeta,
    PluginRegistry,
    is_builtin_plugin_path,
)

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
    version: str = "1.0.0"
    updated_at: str = ""
    author: str = ""
    source_path: Optional[str] = None
    params_schema: List[Dict[str, Any]] = Field(default_factory=list)
    enabled: bool = True
    builtin: bool = False
    permissions: List[str] = Field(default_factory=list)


class PluginSourceResponse(BaseModel):
    name: str
    version: str = "1.0.0"
    updated_at: str = ""
    author: str = ""
    builtin: bool = False
    source_path: Optional[str] = None
    source: str


class CreatePluginRequest(BaseModel):
    name: str = Field(..., pattern=r"^[a-zA-Z0-9_]{3,32}$", description="插件英文标识（3-32位字母数字下划线）")
    mode: Literal["reactive", "active"] = "reactive"
    template: Literal["basic_reactive", "basic_active", "storage_counter"] = "basic_reactive"
    description: str = Field(default="", max_length=200)
    author: str = Field(default="", max_length=50)
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")


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
            version=getattr(p, "version", "1.0.0") or "1.0.0",
            updated_at=getattr(p, "updated_at", "") or "",
            author=getattr(p, "author", "") or "",
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
    import ipaddress
    import re
    import socket
    from urllib.parse import urlparse

    import httpx

    raw_url = req.url.strip()
    if not (raw_url.startswith("http://") or raw_url.startswith("https://")):
        raise HTTPException(status_code=400, detail="URL 必须以 http:// 或 https:// 开头")

    parsed_url = urlparse(raw_url)
    hostname = parsed_url.hostname or ""
    if not hostname:
        raise HTTPException(status_code=400, detail="无效的主机名")

    # SSRF 防护：白名单式校验，仅放行全局可路由地址
    def _is_forbidden_target(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        embedded: list[ipaddress.IPv4Address] = []
        if ip_obj.version == 6:
            # IPv4-mapped/6to4/Teredo 内嵌的 IPv4 地址需一并判定，防止 ::ffff:10.0.0.1 之类字面量绕过
            if ip_obj.ipv4_mapped:
                embedded.append(ip_obj.ipv4_mapped)
            if ip_obj.sixtofour:
                embedded.append(ip_obj.sixtofour)
            if ip_obj.teredo:
                embedded.extend([ip_obj.teredo.server, ip_obj.teredo.client])
        if not ip_obj.is_global:
            return True
        return any(not addr.is_global for addr in embedded)

    # 解析候选地址并逐一校验，返回钉扎用的 IP，避免后续请求重新解析造成 DNS rebinding
    try:
        candidates = [ipaddress.ip_address(hostname)]
    except ValueError:
        try:
            addr_info = socket.getaddrinfo(hostname, None)
        except (socket.gaierror, UnicodeError):
            raise HTTPException(status_code=400, detail=f"无法解析主机: {hostname}")
        candidates = []
        for addr in addr_info:
            try:
                candidates.append(ipaddress.ip_address(addr[4][0]))
            except ValueError:
                continue
    if not candidates:
        raise HTTPException(status_code=400, detail=f"无法解析主机: {hostname}")
    for ip_obj in candidates:
        if _is_forbidden_target(ip_obj):
            raise HTTPException(status_code=400, detail="安全限制：禁止请求私有或内网地址")
    pinned_ip_obj = candidates[0]
    if pinned_ip_obj.version == 6 and pinned_ip_obj.ipv4_mapped:
        pinned_ip_obj = pinned_ip_obj.ipv4_mapped
    pinned_ip = str(pinned_ip_obj)

    default_port = {"http": 80, "https": 443}.get(parsed_url.scheme)

    def _build_pinned_url() -> str:
        host_for_url = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
        netloc = host_for_url if parsed_url.port is None else f"{host_for_url}:{parsed_url.port}"
        if parsed_url.username:
            credential = parsed_url.username
            if parsed_url.password:
                credential = f"{credential}:{parsed_url.password}"
            netloc = f"{credential}@{netloc}"
        return parsed_url._replace(netloc=netloc).geturl()

    try:
        request_url = _build_pinned_url()
        host_header = hostname if parsed_url.port in (None, default_port) else f"{hostname}:{parsed_url.port}"
        request_headers = {"Host": host_header}
        # trust_env=False：禁用环境/系统代理，代理会以未受校验的解析建立连接，且其隧道
        # 路径不支持 sni_hostname 扩展；直连钉扎 IP 才能保证校验与实际连接目标一致
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False, trust_env=False) as client:
            if parsed_url.scheme == "https":
                # 钉扎 IP 后仍按原主机名完成 SNI 与证书校验
                resp = await client.get(request_url, headers=request_headers, extensions={"sni_hostname": hostname})
            else:
                resp = await client.get(request_url, headers=request_headers)
        if 300 <= resp.status_code < 400:
            raise HTTPException(status_code=400, detail="远程插件 URL 不允许重定向")
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
        # 加载失败时清理已写入的文件，避免残留无效插件
        dest_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="插件文件已写入但未能成功加载")

    return PluginInfo(
        name=matched.name,
        mode=matched.mode,
        description=matched.description,
        version=getattr(matched, "version", "1.0.0") or "1.0.0",
        updated_at=getattr(matched, "updated_at", "") or "",
        author=getattr(matched, "author", "") or "",
        source_path=_safe_source_path(matched.source_path),
        params_schema=matched.params_schema or [],
        enabled=True,
        builtin=False,
        permissions=getattr(matched, "permissions", []),
    )


@router.get("/{name}/source", response_model=PluginSourceResponse)
async def get_plugin_source(
    name: str,
    _user: User = Depends(get_current_user),
) -> PluginSourceResponse:
    """获取指定插件的只读源代码内容。"""
    meta = PluginRegistry.get(name)
    if not meta:
        raise HTTPException(status_code=404, detail="插件未找到")

    if not meta.source_path:
        raise HTTPException(status_code=404, detail="插件无源码文件")

    source_path = Path(meta.source_path).resolve()
    if not source_path.is_file():
        raise HTTPException(status_code=404, detail="插件源码文件在磁盘上不存在")

    # 路径防穿越安全校验：文件必须存在于合法搜索目录或内置插件目录中
    allowed_dirs = [d.resolve() for d in PluginRegistry.get_search_directories()]
    allowed_dirs.extend([d.resolve() for d in PluginRegistry.get_builtin_directories()])
    is_allowed = any(d in source_path.parents or d == source_path.parent for d in allowed_dirs)
    if not is_allowed:
        raise HTTPException(status_code=403, detail="非法插件源码路径访问")

    # 单文件读取上限 2MB
    try:
        file_size = source_path.stat().st_size
        if file_size > 2 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="插件源码文件超过 2MB 限制")
        source_code = source_path.read_text(encoding="utf-8")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("读取插件源码失败 %s: %s", source_path, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"读取插件源码失败: {exc}")

    return PluginSourceResponse(
        name=meta.name,
        version=getattr(meta, "version", "1.0.0") or "1.0.0",
        updated_at=getattr(meta, "updated_at", "") or "",
        author=getattr(meta, "author", "") or "",
        builtin=getattr(meta, "builtin", False) or is_builtin_plugin_path(source_path),
        source_path=_safe_source_path(str(source_path)),
        source=source_code,
    )


@router.delete("/{name}")
async def delete_plugin(
    name: str,
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """删除指定的自定义插件（官方内置插件禁止删除）。"""
    meta = PluginRegistry.get(name)
    if not meta:
        raise HTTPException(status_code=404, detail="插件未找到")

    if getattr(meta, "builtin", False) or is_builtin_plugin_path(meta.source_path):
        raise HTTPException(status_code=403, detail="官方内置插件禁止删除")

    if not meta.source_path:
        raise HTTPException(status_code=400, detail="插件无物理源文件路径，无法物理删除")

    source_path = Path(meta.source_path).resolve()
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="插件文件在磁盘上不存在")

    # 安全检查：源文件必须位于自定义插件目录中
    custom_dirs = [d.resolve() for d in PluginRegistry.get_search_directories() if not is_builtin_plugin_path(d)]
    is_in_custom_dir = any(d in source_path.parents or d == source_path.parent for d in custom_dirs)
    if not is_in_custom_dir:
        raise HTTPException(status_code=403, detail="插件所在目录不是自定义插件目录，禁止删除")

    try:
        # 如果是目录型插件（例如 /path/to/custom_plugins/my_plug/main.py），且父目录在 custom_dir 内部
        if source_path.name in ("main.py", "__init__.py") and source_path.parent not in custom_dirs:
            shutil.rmtree(source_path.parent)
        else:
            source_path.unlink()
    except Exception as exc:
        logger.error("删除插件文件失败 %s: %s", source_path, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除插件文件失败: {exc}")

    # 若有停用配置，同步从全局 disabled_plugins 中移除
    try:
        from backend.services.config import get_config_service
        cfg_service = get_config_service()
        settings = cfg_service.get_global_settings() or {}
        disabled = list(settings.get("disabled_plugins", []))
        if name in disabled:
            disabled.remove(name)
            settings["disabled_plugins"] = disabled
            cfg_service.save_global_settings(settings)
    except Exception as exc:
        logger.warning("清理 disabled_plugins 失败: %s", exc)

    PluginRegistry.reload_all_plugins()
    return {"success": True, "name": name, "message": f"插件 {name} 已成功删除"}


@router.post("/create", response_model=PluginInfo)
async def create_plugin_from_template(
    req: CreatePluginRequest,
    _user: User = Depends(get_current_user),
) -> PluginInfo:
    """根据模板脚手架在线创建自定义插件。"""
    # 1. 检查名称是否重复
    existing = PluginRegistry.get(req.name)
    if existing:
        raise HTTPException(status_code=400, detail=f"插件名称 '{req.name}' 已存在")

    # 2. 确定自定义插件保存目录
    custom_dirs = [d for d in PluginRegistry.get_search_directories() if not is_builtin_plugin_path(d)]
    target_dir = custom_dirs[0] if custom_dirs else Path.cwd() / "data" / "plugins"
    target_dir.mkdir(parents=True, exist_ok=True)

    plugin_dir = target_dir / req.name
    if plugin_dir.exists():
        raise HTTPException(status_code=400, detail=f"目录 '{req.name}' 已存在于插件目录中")

    today = datetime.now().strftime("%Y-%m-%d")
    version = req.version or "1.0.0"
    author = req.author or ""
    description = req.description or f"自定义插件 {req.name}"

    if req.template == "basic_active":
        code_text = f'''"""自定义主动执行式插件: {req.name}"""
from tg_signer.core.plugins import PluginContext, PluginRegistry

VERSION = "{version}"
UPDATED_AT = "{today}"
AUTHOR = "{author}"

PARAMS_SCHEMA = [
    {{
        "name": "notify_text",
        "label": "通知文案",
        "type": "string",
        "default": "主动任务执行完毕",
        "description": "需要主动推送的内容",
    }}
]

@PluginRegistry.register(
    name="{req.name}",
    mode="active",
    description="{description}",
    params_schema=PARAMS_SCHEMA,
    version=VERSION,
    updated_at=UPDATED_AT,
    author=AUTHOR,
)
async def {req.name}_handler(ctx: PluginContext) -> bool:
    params = ctx.params or {{}}
    text = params.get("notify_text", "主动任务执行完毕")
    ctx.log(f"正在执行主动插件 {req.name}，目标 chat_id: {{ctx.chat_id}}")
    await ctx.send_message(f"[{req.name}] {{text}}")
    return True
'''
    elif req.template == "storage_counter":
        code_text = f'''"""自定义带状态持久化插件: {req.name}"""
from tg_signer.core.plugins import PluginContext, PluginRegistry

VERSION = "{version}"
UPDATED_AT = "{today}"
AUTHOR = "{author}"

PARAMS_SCHEMA = []

@PluginRegistry.register(
    name="{req.name}",
    mode="reactive",
    description="{description}",
    params_schema=PARAMS_SCHEMA,
    version=VERSION,
    updated_at=UPDATED_AT,
    author=AUTHOR,
)
async def {req.name}_handler(ctx: PluginContext) -> bool:
    count = await ctx.storage.increment("total_trigger_count", 1)
    ctx.log(f"插件 {req.name} 已累计触发 {{count}} 次")
    if ctx.message:
        await ctx.reply(f"这是您第 {{count}} 次触发此插件")
    return True
'''
    else:  # basic_reactive
        code_text = f'''"""自定义监听响应式插件: {req.name}"""
from tg_signer.core.plugins import PluginContext, PluginRegistry

VERSION = "{version}"
UPDATED_AT = "{today}"
AUTHOR = "{author}"

PARAMS_SCHEMA = [
    {{
        "name": "reply_prefix",
        "label": "回复前缀",
        "type": "string",
        "default": "[自动应答]",
        "description": "发送回复文本时附带的前缀",
    }}
]

@PluginRegistry.register(
    name="{req.name}",
    mode="reactive",
    description="{description}",
    params_schema=PARAMS_SCHEMA,
    version=VERSION,
    updated_at=UPDATED_AT,
    author=AUTHOR,
)
async def {req.name}_handler(ctx: PluginContext) -> bool:
    msg = ctx.message
    if not msg or not getattr(msg, "text", None):
        return False

    prefix = (ctx.params or {{}}).get("reply_prefix", "[自动应答]")
    await ctx.reply(f"{{prefix}} 已收到消息: {{msg.text[:50]}}")
    return True
'''

    try:
        plugin_dir.mkdir(parents=True, exist_ok=True)
        dest_file = plugin_dir / "main.py"
        dest_file.write_text(code_text, encoding="utf-8")
    except Exception as exc:
        shutil.rmtree(plugin_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"写入插件文件失败: {exc}")

    # 重新加载插件
    PluginRegistry.reload_all_plugins()
    matched = PluginRegistry.get(req.name)
    if not matched:
        shutil.rmtree(plugin_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="插件模板文件已写入但未能成功加载")

    return PluginInfo(
        name=matched.name,
        mode=matched.mode,
        description=matched.description,
        version=getattr(matched, "version", "1.0.0") or "1.0.0",
        updated_at=getattr(matched, "updated_at", "") or "",
        author=getattr(matched, "author", "") or "",
        source_path=_safe_source_path(matched.source_path),
        params_schema=matched.params_schema or [],
        enabled=True,
        builtin=False,
        permissions=getattr(matched, "permissions", []),
    )

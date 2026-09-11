"""Plugin management API routes."""

from __future__ import annotations

import ast
import asyncio
import inspect
import logging
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
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


def _get_custom_plugins_dir() -> Path:
    custom_dirs = [
        d for d in PluginRegistry.get_search_directories()
        if not is_builtin_plugin_path(d)
    ]
    target_dir = custom_dirs[0] if custom_dirs else Path.cwd() / "data" / "plugins"
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


class PluginMetricsModel(BaseModel):
    run_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    last_run_at: Optional[str] = None
    last_duration_ms: float = 0.0
    avg_duration_ms: float = 0.0
    success_rate: float = 100.0
    last_error: Optional[str] = None


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
    doc: Optional[str] = None
    recent_results: List[bool] = Field(default_factory=list)
    metrics: Optional[PluginMetricsModel] = None


def _meta_to_info(p: PluginMeta, disabled_set: Optional[set[str]] = None) -> PluginInfo:
    if disabled_set is None:
        disabled_set = _get_disabled_plugins()
    metrics_data = PluginRegistry.get_metrics(p.name)
    metrics_model = PluginMetricsModel(**metrics_data.to_dict()) if metrics_data else None
    hist = PluginRegistry.get_execution_history(p.name, limit=10)
    recent_bools = [r.success for r in reversed(hist)]
    return PluginInfo(
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
        doc=getattr(p, "doc", None),
        recent_results=recent_bools,
        metrics=metrics_model,
    )


class PluginSourceResponse(BaseModel):
    name: str
    version: str = "1.0.0"
    updated_at: str = ""
    author: str = ""
    builtin: bool = False
    source_path: Optional[str] = None
    source: str


class UpdatePluginSourceRequest(BaseModel):
    source: str = Field(..., description="更新后的 Python 插件源码")


class CreatePluginRequest(BaseModel):
    name: str = Field(..., pattern=r"^[a-zA-Z0-9_]{3,32}$", description="插件英文标识（3-32位字母数字下划线）")
    mode: Literal["reactive", "active"] = "reactive"
    template: Literal[
        "basic_reactive",
        "basic_active",
        "storage_counter",
        "regex_extractor",
        "webhook_alert",
    ] = "basic_reactive"
    description: str = Field(default="", max_length=200)
    author: str = Field(default="", max_length=50)
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")


class PluginConfigResponse(BaseModel):
    name: str
    params: Dict[str, Any] = Field(default_factory=dict)
    is_customized: bool = False


class UpdatePluginConfigRequest(BaseModel):
    params: Dict[str, Any] = Field(default_factory=dict)


class CheckSyntaxRequest(BaseModel):
    source: str


class CheckSyntaxResponse(BaseModel):
    valid: bool
    line: Optional[int] = None
    column: Optional[int] = None
    error: Optional[str] = None


class AuditPluginRequest(BaseModel):
    source: str


class AuditPluginWarning(BaseModel):
    line: int
    column: int
    severity: str
    rule: str
    message: str


class AuditPluginResponse(BaseModel):
    passed: bool
    warnings: List[AuditPluginWarning] = Field(default_factory=list)


class ImportBundleResponse(BaseModel):
    imported_count: int = 0
    files: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class ClonePluginRequest(BaseModel):
    new_name: str = Field(..., pattern=r"^[a-zA-Z0-9_]{3,32}$", description="新插件标识")
    description: Optional[str] = Field(default=None, max_length=200)


class BatchTogglePluginsRequest(BaseModel):
    enabled: bool = Field(..., description="是否批量启用自定义插件")


class PluginLoadErrorItem(BaseModel):
    file_path: str
    plugin_name: str
    error_type: str
    error_message: str
    missing_module: Optional[str] = None
    suggested_command: Optional[str] = None
    timestamp: str = ""


class PluginDiagnosticsResponse(BaseModel):
    total_loaded: int
    total_errors: int
    load_errors: List[PluginLoadErrorItem]


class ReloadPluginsResponse(BaseModel):
    count: int
    plugins: List[PluginInfo]


class PluginTestRequest(BaseModel):
    text: str = Field(default="", description="模拟接收到的 Telegram 消息文本")
    params: Dict[str, Any] = Field(default_factory=dict, description="插件自定义参数")
    reset_storage: bool = Field(default=False, description="测试前是否重置测试命名空间内的持久化存储")
    chat_id: Optional[Union[int, str]] = Field(default=None, description="模拟会话 ID")
    sender_name: Optional[str] = Field(default=None, description="模拟发送者名称")
    timeout: Optional[float] = Field(default=None, description="单次测试最大超时时间(秒)")


PluginInfo.update_forward_refs()
PluginTestRequest.update_forward_refs()


class PluginTestResponse(BaseModel):
    name: str
    mode: str = "reactive"
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


@router.get("/diagnostics", response_model=PluginDiagnosticsResponse)
async def get_plugin_diagnostics(_user: User = Depends(get_current_user)) -> PluginDiagnosticsResponse:
    """获取插件加载诊断与加载失败项。"""
    errs = PluginRegistry.get_load_errors()
    items = [
        PluginLoadErrorItem(
            file_path=_safe_source_path(e.file_path) or e.file_path,
            plugin_name=e.plugin_name,
            error_type=e.error_type,
            error_message=e.error_message,
            missing_module=e.missing_module,
            suggested_command=e.suggested_command,
            timestamp=e.timestamp,
        )
        for e in errs
    ]
    return PluginDiagnosticsResponse(
        total_loaded=len(PluginRegistry.list_plugins()),
        total_errors=len(items),
        load_errors=items,
    )


@router.get("", response_model=List[PluginInfo])
async def list_plugins(_user: User = Depends(get_current_user)) -> List[PluginInfo]:
    """获取所有已加载的自定义插件列表。"""
    plugins = PluginRegistry.list_plugins()
    disabled_set = _get_disabled_plugins()
    for name in plugins:
        PluginRegistry.set_disabled(name, disabled=name in disabled_set)

    return [_meta_to_info(p, disabled_set) for p in plugins.values()]


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

    res_list = [_meta_to_info(p, disabled_set) for p in plugins.values()]
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

    return _meta_to_info(meta, set(disabled_list))


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

    eff_chat_id = req.chat_id if req.chat_id is not None else 12345678
    eff_sender_name = req.sender_name or "Tester"

    class MockUser:
        id = 888888
        first_name = eff_sender_name
        is_bot = False

    class MockChat:
        id = eff_chat_id
        title = "MockChat"
        type = "supergroup" if str(eff_chat_id).startswith("-100") else "private"

    class MockMessage:
        def __init__(self, text: str):
            self.text = text
            self.caption = None
            self.id = 999999
            self.chat = MockChat()
            self.from_user = MockUser()
            self.chat_id = eff_chat_id

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

    if req.reset_storage:
        try:
            from tg_signer.core.plugins import PluginStorageBackend
            PluginStorageBackend().clear(namespace=f"12345678:{name}")
            captured_logs.append("[mock] 已清空该插件测试命名空间持久化存储")
        except Exception as exc:
            captured_logs.append(f"[mock] 清空存储提示: {exc}")

    mock_msg = MockMessage(req.text) if (req.text or meta.mode != "active") else None
    mock_app = MockApp()

    ctx = PluginContext(
        app=mock_app,
        chat_id=eff_chat_id,
        message=mock_msg,
        params=req.params,
        logger=log_capture,
        plugin_name=name,
    )

    if req.timeout is not None and req.timeout > 0:
        test_timeout = float(req.timeout)
    else:
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
    summary = " | ".join(captured_logs[-2:]) if captured_logs else None
    PluginRegistry.record_execution(
        name,
        duration_ms=duration_ms,
        success=bool(success and not err_str),
        error=err_str,
        trigger_type="manual_test",
        log_summary=summary,
    )

    return PluginTestResponse(
        name=name,
        mode=meta.mode,
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


@router.put("/{name}/source", response_model=PluginInfo)
async def update_plugin_source(
    name: str,
    payload: UpdatePluginSourceRequest,
    _user: User = Depends(get_current_user),
) -> PluginInfo:
    """在线更新自定义插件源码并热重载。"""
    meta = PluginRegistry.get(name)
    if not meta:
        raise HTTPException(status_code=404, detail="插件未找到")

    if not meta.source_path:
        raise HTTPException(status_code=404, detail="插件无物理源码文件，无法编辑")

    source_path = Path(meta.source_path).resolve()
    if not source_path.is_file():
        raise HTTPException(status_code=404, detail="插件源码文件在磁盘上不存在")

    is_builtin = getattr(meta, "builtin", False) or is_builtin_plugin_path(source_path)
    if is_builtin:
        raise HTTPException(status_code=403, detail="官方内置插件受保护，禁止修改源码")

    custom_dirs = [d.resolve() for d in PluginRegistry.get_search_directories() if not is_builtin_plugin_path(d)]
    custom_dirs.append(_get_custom_plugins_dir().resolve())
    is_in_custom_dir = any(d in source_path.parents or d == source_path.parent for d in custom_dirs)
    if not is_in_custom_dir:
        raise HTTPException(status_code=403, detail="插件所在目录不是自定义插件目录，禁止修改")

    if len(payload.source.encode("utf-8")) > 1024 * 1024:
        raise HTTPException(status_code=400, detail="插件源码大小超过 1MB 限制")

    try:
        ast.parse(payload.source, filename=source_path.name)
    except SyntaxError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Python 语法错误: {exc.msg} (第 {exc.lineno} 行)",
        )

    try:
        source_path.write_text(payload.source, encoding="utf-8")
    except Exception as exc:
        logger.error("保存插件源码失败 %s: %s", source_path, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"保存插件源码失败: {exc}")

    try:
        PluginRegistry.reload_all_plugins()
    except Exception as exc:
        logger.warning("插件重载异常: %s", exc)

    updated_meta = PluginRegistry.get(name)
    if not updated_meta:
        for p in PluginRegistry.list_plugins().values():
            if p.source_path and Path(p.source_path).resolve() == source_path:
                updated_meta = p
                break

    if not updated_meta:
        raise HTTPException(
            status_code=400,
            detail="插件代码已保存，但在重载时未注册有效插件，请检查 @PluginRegistry.register 装饰器",
        )

    return _meta_to_info(updated_meta)


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
    elif req.template == "regex_extractor":
        code_text = f'''"""自定义正则提取插件: {req.name}"""
import re
from tg_signer.core.plugins import PluginContext, PluginRegistry

VERSION = "{version}"
UPDATED_AT = "{today}"
AUTHOR = "{author}"

PARAMS_SCHEMA = [
    {{
        "name": "pattern",
        "label": "提取正则表达式",
        "type": "string",
        "default": r"(?:验证码|code)[:：\\s]*([a-zA-Z0-9]{{4,8}})",
        "description": "用于从消息文本中捕获特定信息的正则表达式",
    }},
    {{
        "name": "reply_format",
        "label": "回复模版",
        "type": "string",
        "default": "已捕获结果: {{match}}",
        "description": "回复文本模版，支持使用 {{match}} 占位符",
    }},
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

    params = ctx.params or {{}}
    pattern = params.get("pattern", r"(?:验证码|code)[:：\\s]*([a-zA-Z0-9]{{4,8}})")
    reply_format = params.get("reply_format", "已捕获结果: {{match}}")

    match = re.search(pattern, msg.text, re.IGNORECASE)
    if not match:
        return False

    extracted = match.group(1) if match.groups() else match.group(0)
    ctx.log(f"正则匹配成功: {{extracted}}")
    reply_msg = reply_format.replace("{{match}}", extracted)
    await ctx.reply(reply_msg)
    return True
'''
    elif req.template == "webhook_alert":
        code_text = f'''"""自定义 Webhook 推送插件: {req.name}"""
import json
import urllib.request
from tg_signer.core.plugins import PluginContext, PluginRegistry

VERSION = "{version}"
UPDATED_AT = "{today}"
AUTHOR = "{author}"
PERMISSIONS = ["network"]

PARAMS_SCHEMA = [
    {{
        "name": "webhook_url",
        "label": "Webhook 地址",
        "type": "string",
        "default": "",
        "description": "推送通知的目标 HTTP(S) URL",
    }},
]

@PluginRegistry.register(
    name="{req.name}",
    mode="reactive",
    description="{description}",
    params_schema=PARAMS_SCHEMA,
    permissions=PERMISSIONS,
    version=VERSION,
    updated_at=UPDATED_AT,
    author=AUTHOR,
)
async def {req.name}_handler(ctx: PluginContext) -> bool:
    msg = ctx.message
    if not msg or not getattr(msg, "text", None):
        return False

    webhook_url = (ctx.params or {{}}).get("webhook_url")
    if not webhook_url:
        ctx.log("未配置 webhook_url，跳过推送")
        return False

    payload = {{
        "plugin": "{req.name}",
        "chat_id": ctx.chat_id,
        "text": msg.text,
    }}
    req = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={{"Content-Type": "application/json"}},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        ctx.log(f"Webhook 推送完成，HTTP 状态码: {{resp.status}}")

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


@router.get("/{name}/export")
async def export_plugin(
    name: str,
    _user: User = Depends(get_current_user),
) -> Response:
    """导出并下载指定插件的 .py 源码文件。"""
    meta = PluginRegistry.get(name)
    if not meta or not meta.source_path:
        raise HTTPException(status_code=404, detail=f"插件 '{name}' 不存在或无源码文件")

    path = Path(meta.source_path).resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"插件 '{name}' 源码文件丢失")

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"读取插件源码失败: {exc}")

    filename = f"{name}.py"
    return Response(
        content=content,
        media_type="text/x-python; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/upload", response_model=PluginInfo)
async def upload_plugin(
    file: UploadFile = File(...),
    _user: User = Depends(get_current_user),
) -> PluginInfo:
    """上传本地 .py 插件文件至自定义插件目录并热重载。"""
    if not file.filename or not file.filename.endswith(".py"):
        raise HTTPException(status_code=400, detail="仅支持上传 .py 格式的 Python 插件文件")

    raw_filename = Path(file.filename).name
    plugin_stem = raw_filename[:-3]
    if not re.match(r"^[a-zA-Z0-9_]{3,32}$", plugin_stem):
        raise HTTPException(
            status_code=400,
            detail="插件文件名必须由 3-32 位字母、数字或下划线组成（如 custom_plugin.py）",
        )

    try:
        content_bytes = await file.read()
        content = content_bytes.decode("utf-8")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"读取上传文件失败: {exc}")

    if len(content_bytes) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="插件文件大小超过 2MB 限制")

    try:
        ast.parse(content, filename=raw_filename)
    except SyntaxError as exc:
        raise HTTPException(status_code=400, detail=f"Python 语法错误 [第 {exc.lineno} 行]: {exc.msg}")

    target_dir = _get_custom_plugins_dir()
    dest_path = target_dir / raw_filename
    try:
        dest_path.write_text(content, encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"写入插件文件失败: {exc}")

    PluginRegistry.reload_all_plugins()
    matched = PluginRegistry.get(plugin_stem)
    if not matched:
        for p in PluginRegistry.list_plugins().values():
            if p.source_path and Path(p.source_path).name == raw_filename:
                matched = p
                break

    if not matched:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="未在上传的文件中检测到有效插件注册（请检查 @PluginRegistry.register 装饰器）")

    return _meta_to_info(matched)

@router.post("/{name}/reset-metrics")
async def reset_plugin_metrics(
    name: str,
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """重置指定插件的运行统计指标。"""
    meta = PluginRegistry.get(name)
    if not meta:
        raise HTTPException(status_code=404, detail="插件未找到")
    PluginRegistry.reset_metrics(name)
    return {"success": True, "name": name, "message": "指标已重置"}

@router.post("/batch-toggle")
async def batch_toggle_plugins(
    payload: BatchTogglePluginsRequest,
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """批量启用或停用所有自定义插件。"""
    try:
        from backend.services.config import get_config_service

        cfg_svc = get_config_service()
        settings = dict(cfg_svc.get_global_settings() or {})
        disabled_list = list(settings.get("disabled_plugins", []))
    except Exception:
        cfg_svc = None
        settings = {}
        disabled_list = []

    disabled_set = set(disabled_list)

    custom_plugins = [
        p
        for p in PluginRegistry.list_plugins().values()
        if not (getattr(p, "builtin", False) or is_builtin_plugin_path(p.source_path))
    ]

    for p in custom_plugins:
        if payload.enabled:
            disabled_set.discard(p.name)
            PluginRegistry.set_disabled(p.name, disabled=False)
        else:
            disabled_set.add(p.name)
            PluginRegistry.set_disabled(p.name, disabled=True)

    if cfg_svc is not None:
        settings["disabled_plugins"] = list(disabled_set)
        cfg_svc.save_global_settings(settings)

    return {
        "success": True,
        "count": len(custom_plugins),
        "enabled": payload.enabled,
    }


@router.post("/reset-all-metrics")
async def reset_all_plugin_metrics(
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """批量重置所有插件的运行统计指标。"""
    for p in PluginRegistry.list_plugins().values():
        PluginRegistry.reset_metrics(p.name)
    return {"success": True, "message": "已重置所有插件运行指标"}

@router.get("/{name}/history")
async def get_plugin_history(
    name: str,
    limit: int = 20,
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """获取指定插件最近的执行调用历史记录。"""
    meta = PluginRegistry.get(name)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"插件 '{name}' 未找到或未加载",
        )
    records = PluginRegistry.get_execution_history(name, limit=limit)
    return {
        "name": name,
        "history": [r.to_dict() for r in records],
    }


@router.post("/{name}/clear-history")
async def clear_plugin_history(
    name: str,
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """清空指定插件的调用历史记录。"""
    meta = PluginRegistry.get(name)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"插件 '{name}' 未找到或未加载",
        )
    cleared = PluginRegistry.clear_execution_history(name)
    return {
        "status": "ok",
        "name": name,
        "cleared_count": cleared,
    }


@router.post("/{name}/clone", response_model=PluginInfo)
async def clone_plugin(
    name: str,
    req: ClonePluginRequest,
    _user: User = Depends(get_current_user),
) -> PluginInfo:
    """基于现有插件克隆生成一个新的自定义插件。"""
    meta = PluginRegistry.get(name)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"源插件 '{name}' 不存在",
        )

    all_plugins = PluginRegistry.list_plugins()
    if req.new_name in all_plugins:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"插件标识 '{req.new_name}' 已存在，请使用其他名称",
        )

    # 读取源插件代码
    source_code: Optional[str] = None
    if meta.source_path and Path(meta.source_path).is_file():
        try:
            source_code = Path(meta.source_path).read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"读取源插件源码失败: {e}")

    if not source_code and meta.handler:
        try:
            import inspect
            source_code = inspect.getsource(meta.handler)
        except Exception:
            pass

    if not source_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无法获取源插件 '{name}' 的源代码进行克隆",
        )

    # 替换插件名称与函数名称
    new_code = source_code
    new_code = re.sub(rf'name\s*=\s*["\']{name}["\']', f'name="{req.new_name}"', new_code)
    new_code = re.sub(rf'def\s+{name}_handler', f'def {req.new_name}_handler', new_code)
    if req.description:
        new_code = re.sub(r'description\s*=\s*["\'][^"\']*["\']', f'description="{req.description}"', new_code, count=1)

    target_dir = _get_custom_plugins_dir()
    target_file = target_dir / f"{req.new_name}.py"
    if target_file.exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"文件 '{target_file.name}' 已存在",
        )

    try:
        target_file.write_text(new_code, encoding="utf-8")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"保存克隆插件文件失败: {exc}",
        )

    PluginRegistry.reload_all_plugins()
    new_meta = PluginRegistry.get(req.new_name)
    if not new_meta:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="克隆插件创建成功，但加载失败",
        )

    return _meta_to_info(new_meta)

def _inspect_plugin_dependencies(source_code: str) -> List[Dict[str, Any]]:
    """利用 AST 静态分析插件源码中的三方外部依赖模块与安装就绪情况。"""
    import ast
    import importlib.util
    import sys
    from importlib.metadata import version as get_pkg_version

    stdlib_modules = set(getattr(sys, "stdlib_module_names", set()))
    ignore_modules = stdlib_modules | {
        "tg_signer", "backend", "tests", "typing", "collections", "dataclasses",
        "pathlib", "os", "sys", "json", "re", "time", "datetime", "asyncio",
        "logging", "traceback", "urllib", "inspect", "enum", "math", "random",
    }

    try:
        tree = ast.parse(source_code)
    except Exception:
        return []

    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_name = alias.name.split(".")[0]
                imported_modules.add(root_name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                root_name = node.module.split(".")[0]
                imported_modules.add(root_name)

    third_party = [m for m in sorted(imported_modules) if m not in ignore_modules]

    results = []
    for mod in third_party:
        spec = importlib.util.find_spec(mod)
        installed = spec is not None
        pkg_ver = None
        if installed:
            try:
                pkg_ver = get_pkg_version(mod)
            except Exception:
                pass
        results.append({
            "module": mod,
            "installed": installed,
            "version": pkg_ver,
            "install_command": f"pip install {mod}" if not installed else None,
        })
    return results


def _get_all_plugin_configs() -> Dict[str, Dict[str, Any]]:
    try:
        from backend.services.config import get_config_service
        settings = get_config_service().get_global_settings() or {}
        return dict(settings.get("plugin_configs", {}))
    except Exception:
        return {}


def _save_all_plugin_configs(configs: Dict[str, Dict[str, Any]]) -> None:
    from backend.services.config import get_config_service
    cfg_svc = get_config_service()
    settings = cfg_svc.get_global_settings() or {}
    settings["plugin_configs"] = configs
    cfg_svc.save_global_settings(settings)


def _get_default_params_from_schema(params_schema: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    defaults = {}
    if not params_schema:
        return defaults
    for item in params_schema:
        if isinstance(item, dict) and "name" in item and "default" in item:
            defaults[item["name"]] = item["default"]
    return defaults


@router.get("/{name}/dependencies")
async def get_plugin_dependencies(
    name: str,
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """静态解析指定插件的三方依赖库，并检测当前运行环境中是否已安装。"""
    meta = PluginRegistry.get(name)
    source_code: Optional[str] = None

    if meta and meta.source_path and Path(meta.source_path).is_file():
        try:
            source_code = Path(meta.source_path).read_text(encoding="utf-8")
        except Exception:
            pass

    if not source_code:
        # 尝试从自定义目录中寻找对应文件（包括因缺少依赖而加载失败的插件）
        target_dir = _get_custom_plugins_dir()
        candidate = target_dir / f"{name}.py"
        if candidate.is_file():
            try:
                source_code = candidate.read_text(encoding="utf-8")
            except Exception:
                pass
        elif (target_dir / name / "__init__.py").is_file():
            try:
                source_code = (target_dir / name / "__init__.py").read_text(encoding="utf-8")
            except Exception:
                pass

    if not source_code and meta and meta.handler:
        try:
            import inspect
            source_code = inspect.getsource(meta.handler)
        except Exception:
            pass

    if not source_code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未能定位插件 '{name}' 的源代码",
        )

    deps = _inspect_plugin_dependencies(source_code)
    return {
        "name": name,
        "dependencies": deps,
    }


@router.get("/{name}/config", response_model=PluginConfigResponse)
async def get_plugin_config(
    name: str,
    _user: User = Depends(get_current_user),
) -> PluginConfigResponse:
    """获取插件全局配置参数。若尚未自定义保存，则返回 params_schema 中声明的默认值。"""
    meta = PluginRegistry.get(name)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"插件 '{name}' 不存在",
        )

    all_configs = _get_all_plugin_configs()
    defaults = _get_default_params_from_schema(meta.params_schema)
    if name in all_configs:
        merged = {**defaults, **all_configs[name]}
        return PluginConfigResponse(name=name, params=merged, is_customized=True)
    return PluginConfigResponse(name=name, params=defaults, is_customized=False)


@router.put("/{name}/config", response_model=PluginConfigResponse)
async def update_plugin_config(
    name: str,
    req: UpdatePluginConfigRequest,
    _user: User = Depends(get_current_user),
) -> PluginConfigResponse:
    """保存插件全局参数配置。"""
    meta = PluginRegistry.get(name)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"插件 '{name}' 不存在",
        )

    all_configs = _get_all_plugin_configs()
    all_configs[name] = req.params
    _save_all_plugin_configs(all_configs)

    defaults = _get_default_params_from_schema(meta.params_schema)
    merged = {**defaults, **req.params}
    return PluginConfigResponse(name=name, params=merged, is_customized=True)


class PluginManifestItem(BaseModel):
    name: str
    mode: str
    description: str
    version: str = "1.0.0"
    updated_at: str = ""
    author: str = ""
    enabled: bool = True
    builtin: bool = False
    permissions: List[str] = Field(default_factory=list)
    params_schema: List[Dict[str, Any]] = Field(default_factory=list)
    doc: Optional[str] = None


@router.get("/manifest", response_model=List[PluginManifestItem])
async def get_plugins_manifest(
    _user: User = Depends(get_current_user),
) -> List[PluginManifestItem]:
    """导出当前所有插件的元数据清单列表。"""
    disabled_set = _get_disabled_plugins()
    result: List[PluginManifestItem] = []
    for p in PluginRegistry.list_plugins().values():
        result.append(
            PluginManifestItem(
                name=p.name,
                mode=p.mode,
                description=p.description,
                version=getattr(p, "version", "1.0.0") or "1.0.0",
                updated_at=getattr(p, "updated_at", "") or "",
                author=getattr(p, "author", "") or "",
                enabled=p.name not in disabled_set,
                builtin=getattr(p, "builtin", False),
                permissions=getattr(p, "permissions", []),
                params_schema=p.params_schema or [],
                doc=getattr(p, "doc", None),
            )
        )
    return result


@router.get("/export-all")
async def export_all_plugins(
    _user: User = Depends(get_current_user),
):
    """将所有用户自定义插件打包为 ZIP 归档文件并下载。"""
    import io
    import zipfile
    from datetime import datetime

    target_dir = _get_custom_plugins_dir()
    if not target_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="自定义插件目录不存在",
        )

    py_files = [
        f for f in target_dir.rglob("*.py")
        if not f.name.startswith(".") and not f.name.startswith("__pycache__")
    ]
    if not py_files:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="当前没有可导出的自定义插件",
        )

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for py_path in py_files:
            rel_path = py_path.relative_to(target_dir)
            zf.write(py_path, arcname=str(rel_path))

    zip_bytes = zip_buffer.getvalue()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"tg_signer_plugins_{timestamp}.zip"

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.post("/check-syntax", response_model=CheckSyntaxResponse)
async def check_plugin_syntax(
    req: CheckSyntaxRequest,
    _user: User = Depends(get_current_user),
) -> CheckSyntaxResponse:
    """静态检查 Python 源码是否存在语法错误。"""
    try:
        ast.parse(req.source, filename="<plugin_editor>")
        return CheckSyntaxResponse(valid=True)
    except SyntaxError as exc:
        return CheckSyntaxResponse(
            valid=False,
            line=exc.lineno,
            column=exc.offset,
            error=f"SyntaxError: {exc.msg} (line {exc.lineno})",
        )
    except Exception as exc:
        return CheckSyntaxResponse(
            valid=False,
            error=f"解析失败: {exc}",
        )


@router.post("/audit-source", response_model=AuditPluginResponse)
async def audit_plugin_source_route(
    req: AuditPluginRequest,
    _user: User = Depends(get_current_user),
) -> AuditPluginResponse:
    """静态审计插件源码中的高危调用与潜在安全隐患。"""
    from tg_signer.core.plugins import audit_plugin_source
    warnings_raw = audit_plugin_source(req.source)
    warnings = [
        AuditPluginWarning(
            line=w["line"],
            column=w["column"],
            severity=w["severity"],
            rule=w["rule"],
            message=w["message"],
        )
        for w in warnings_raw
    ]
    passed = len(warnings) == 0
    return AuditPluginResponse(passed=passed, warnings=warnings)


@router.post("/import-bundle", response_model=ImportBundleResponse)
async def import_plugins_bundle(
    file: UploadFile = File(...),
    _user: User = Depends(get_current_user),
) -> ImportBundleResponse:
    """上传 ZIP 压缩包，批量安全解压并热重载自定义插件。"""
    import io
    import zipfile

    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请上传 .zip 格式的插件压缩包",
        )

    content = await file.read()
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"解压 ZIP 失败: {exc}",
        )

    target_dir = _get_custom_plugins_dir()
    imported_files: List[str] = []
    errors: List[str] = []

    with zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            if not member.filename.endswith(".py"):
                continue

            norm = Path(member.filename)
            if ".." in norm.parts or norm.is_absolute():
                errors.append(f"跳过不安全路径: {member.filename}")
                continue

            dest_path = target_dir / norm
            try:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(dest_path, "wb") as dst:
                    dst.write(src.read())
                plugin_stem = norm.stem if norm.name != "__init__.py" else norm.parent.name
                imported_files.append(plugin_stem)
            except Exception as e:
                errors.append(f"解压 {member.filename} 失败: {e}")

    PluginRegistry.reload_all_plugins()

    return ImportBundleResponse(
        imported_count=len(imported_files),
        files=imported_files,
        errors=errors,
    )


@router.post("/{name}/reset-config", response_model=PluginConfigResponse)
async def reset_plugin_config(
    name: str,
    _user: User = Depends(get_current_user),
) -> PluginConfigResponse:
    """清空插件自定义配置，恢复为 params_schema 中的默认值。"""
    meta = PluginRegistry.get(name)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"插件 '{name}' 不存在",
        )

    all_configs = _get_all_plugin_configs()
    if name in all_configs:
        all_configs.pop(name, None)
        _save_all_plugin_configs(all_configs)

    defaults = _get_default_params_from_schema(meta.params_schema)
    return PluginConfigResponse(name=name, params=defaults, is_customized=False)

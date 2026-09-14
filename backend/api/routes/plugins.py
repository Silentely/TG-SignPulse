"""Plugin management API routes."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import inspect
import io
import json
import logging
import os
import re
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
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
    PluginStorageClient,
    _SecurityVisitor,
    is_builtin_plugin_path,
)
from tg_signer.utils import validate_public_http_url

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


def _plugin_test_namespace(chat_id: Union[int, str], plugin_name: str) -> str:
    """调试台专用持久化命名空间，带保留前缀与生产命名空间（{chat_id}:{name}）隔离。"""
    return f"__test__:{chat_id}:{plugin_name}"


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


class FormatPluginSourceRequest(BaseModel):
    source: str


class FormatPluginSourceResponse(BaseModel):
    formatted: str
    changed: bool
    formatter: str = "black"
    lossy: bool = False


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
    timeout: Optional[float] = Field(
        default=None,
        gt=0,
        le=300,
        description="单次测试最大超时时间(秒)，范围 (0, 300]",
    )


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

class MarketPluginItem(BaseModel):
    id: str
    name: str
    version: str
    mode: str = "reactive"
    category: str = "utility"
    description: str = ""
    author: str = ""
    homepage: Optional[str] = None
    icon: Optional[str] = "puzzle"
    tags: List[str] = Field(default_factory=list)
    min_app_version: Optional[str] = "1.8.0"
    permissions: List[str] = Field(default_factory=list)
    params_schema: List[Dict[str, Any]] = Field(default_factory=list)
    download_url: str
    sha256: Optional[str] = None
    size: int = 0
    readme: Optional[str] = None
    updated_at: Optional[str] = None
    installed: bool = False
    installed_version: Optional[str] = None
    installed_is_builtin: bool = False
    status: Literal["not_installed", "installed", "upgradable"] = "not_installed"


class MarketSourceConfig(BaseModel):
    source_type: Literal["github", "jsdelivr", "ghproxy", "local", "custom"]
    custom_url: Optional[str] = None
    active_url: str


class UpdateMarketSourceRequest(BaseModel):
    source_type: Literal["github", "jsdelivr", "ghproxy", "local", "custom"]
    custom_url: Optional[str] = None


class MarketCatalogResponse(BaseModel):
    total: int
    source_type: str
    source_url: str
    plugins: List[MarketPluginItem]
    cached: bool = False


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


# ==================== Marketplace APIs ====================

MARKET_SOURCE_PRESETS: Dict[str, str] = {
    "github": "https://raw.githubusercontent.com/Silentely/TG-SignPulse/dev/dist/marketplace/marketplace.json",
    "jsdelivr": "https://cdn.jsdelivr.net/gh/Silentely/TG-SignPulse@dev/dist/marketplace/marketplace.json",
    "ghproxy": "https://ghproxy.net/https://raw.githubusercontent.com/Silentely/TG-SignPulse/dev/dist/marketplace/marketplace.json",
    "local": "local://marketplace.json",
}

_market_cache: Optional[Dict[str, Any]] = None
_market_cache_time: float = 0.0
_market_cache_source: str = ""
_market_cache_url: str = ""
PLUGIN_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _parse_semver(v: str) -> tuple[int, ...]:
    clean = re.sub(r"[^0-9.]", "", str(v or "0.0.0")).strip(".")
    parts = []
    for x in clean.split("."):
        if x.isdigit():
            parts.append(int(x))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _get_local_marketplace_catalog() -> Dict[str, Any]:
    """优先读取本地构建的 marketplace.json，不存在则动态扫描 community_plugins 目录。"""
    candidates = [
        Path.cwd() / "dist" / "marketplace" / "marketplace.json",
        Path("/app/dist/marketplace/marketplace.json"),
    ]
    for c in candidates:
        if c.is_file():
            try:
                return json.loads(c.read_text(encoding="utf-8"))
            except Exception:
                pass

    community_dirs = [
        Path.cwd() / "community_plugins",
        Path("/app/community_plugins"),
    ]
    plugins_list: List[Dict[str, Any]] = []
    for cdir in community_dirs:
        if cdir.is_dir():
            for pdir in sorted(cdir.iterdir()):
                if pdir.is_dir() and not pdir.name.startswith(("_", ".")):
                    pjson = pdir / "plugin.json"
                    if pjson.is_file():
                        try:
                            manifest = json.loads(pjson.read_text(encoding="utf-8"))
                            readme_file = pdir / "README.md"
                            readme_text = readme_file.read_text(encoding="utf-8") if readme_file.is_file() else ""
                            manifest.setdefault("download_url", f"local://{pdir.name}")
                            manifest.setdefault("sha256", "")
                            manifest.setdefault("size", 0)
                            manifest.setdefault("readme", readme_text)
                            manifest.setdefault("updated_at", datetime.utcnow().strftime("%Y-%m-%d"))
                            plugins_list.append(manifest)
                        except Exception:
                            pass
            if plugins_list:
                break

    return {
        "version": "1.0",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "total_plugins": len(plugins_list),
        "plugins": plugins_list,
    }


async def _fetch_market_catalog(refresh: bool = False) -> Tuple[Dict[str, Any], str, str, bool]:
    global _market_cache, _market_cache_time, _market_cache_source, _market_cache_url
    from urllib.parse import urlparse

    import httpx

    from backend.services.config import get_config_service

    settings = get_config_service().get_global_settings() or {}
    source_type = str(settings.get("marketplace_source", "github"))
    custom_url = str(settings.get("marketplace_custom_url", ""))

    active_url = (
        custom_url.strip()
        if source_type == "custom" and custom_url
        else MARKET_SOURCE_PRESETS.get(source_type, MARKET_SOURCE_PRESETS["github"])
    )

    now = time.time()
    if (
        not refresh
        and _market_cache is not None
        and (now - _market_cache_time < 60.0)
        and (_market_cache_source == source_type)
        and (_market_cache_url == active_url)
    ):
        return _market_cache, source_type, active_url, True

    catalog_data: Optional[Dict[str, Any]] = None

    if source_type == "local":
        catalog_data = _get_local_marketplace_catalog()
    else:
        try:
            pinned_ip, hostname = validate_public_http_url(active_url)
            parsed_url = urlparse(active_url)
            default_port = {"http": 80, "https": 443}.get(parsed_url.scheme)
            host_for_url = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
            netloc = host_for_url if parsed_url.port is None else f"{host_for_url}:{parsed_url.port}"
            if parsed_url.username:
                cred = parsed_url.username
                if parsed_url.password:
                    cred = f"{cred}:{parsed_url.password}"
                netloc = f"{cred}@{netloc}"
            request_url = parsed_url._replace(netloc=netloc).geturl()
            host_header = hostname if parsed_url.port in (None, default_port) else f"{hostname}:{parsed_url.port}"

            async with httpx.AsyncClient(timeout=10.0, follow_redirects=False, trust_env=False) as client:
                if parsed_url.scheme == "https":
                    resp = await client.get(request_url, headers={"Host": host_header}, extensions={"sni_hostname": hostname})
                else:
                    resp = await client.get(request_url, headers={"Host": host_header})
                if resp.status_code == 200:
                    catalog_data = resp.json()
        except Exception as exc:
            logger.warning("拉取远程插件市场目录失败 (%s): %s，降级为本地市场缓存", active_url, exc)

        if not catalog_data or "plugins" not in catalog_data:
            catalog_data = _get_local_marketplace_catalog()

    _market_cache = catalog_data
    _market_cache_time = now
    _market_cache_source = source_type
    _market_cache_url = active_url
    return catalog_data, source_type, active_url, False


@router.get("/market", response_model=MarketCatalogResponse)
async def list_market_plugins(
    refresh: bool = Query(default=False, description="是否强制刷新市场目录缓存"),
    _user: User = Depends(get_current_user),
) -> MarketCatalogResponse:
    """获取插件市场所有可用的插件清单，并附带当前环境的本地安装/可更新状态。"""
    catalog_data, source_type, active_url, is_cached = await _fetch_market_catalog(refresh=refresh)
    installed_plugins = PluginRegistry.list_plugins()

    plugin_items: List[MarketPluginItem] = []
    for item in catalog_data.get("plugins", []):
        pid = item.get("id")
        if not pid:
            continue

        installed_meta = installed_plugins.get(pid)
        is_installed = installed_meta is not None
        installed_version = installed_meta.version if installed_meta else None
        installed_is_builtin = (
            is_builtin_plugin_path(installed_meta.source_path)
            if (installed_meta and installed_meta.source_path)
            else False
        )

        status_val: Literal["not_installed", "installed", "upgradable"] = "not_installed"
        if is_installed:
            if installed_version:
                market_semver = _parse_semver(str(item.get("version", "0.0.0")))
                local_semver = _parse_semver(str(installed_version))
                if market_semver > local_semver:
                    status_val = "upgradable"
                else:
                    status_val = "installed"
            else:
                status_val = "installed"

        plugin_items.append(
            MarketPluginItem(
                id=pid,
                name=item.get("name", pid),
                version=item.get("version", "1.0.0"),
                mode=item.get("mode", "reactive"),
                category=item.get("category", "utility"),
                description=item.get("description", ""),
                author=item.get("author", "Community"),
                homepage=item.get("homepage"),
                icon=item.get("icon", "puzzle"),
                tags=item.get("tags", []),
                min_app_version=item.get("min_app_version", "1.8.0"),
                permissions=item.get("permissions", []),
                params_schema=item.get("params_schema", []),
                download_url=item.get("download_url", ""),
                sha256=item.get("sha256"),
                size=item.get("size", 0),
                readme=item.get("readme"),
                updated_at=item.get("updated_at"),
                installed=is_installed,
                installed_version=installed_version,
                installed_is_builtin=installed_is_builtin,
                status=status_val,
            )
        )

    return MarketCatalogResponse(
        total=len(plugin_items),
        source_type=source_type,
        source_url=active_url,
        plugins=plugin_items,
        cached=is_cached,
    )


@router.get("/market/source", response_model=MarketSourceConfig)
async def get_market_source(
    _user: User = Depends(get_current_user),
) -> MarketSourceConfig:
    """获取当前配置的插件市场源信息。"""
    from backend.services.config import get_config_service
    settings = get_config_service().get_global_settings() or {}
    source_type = str(settings.get("marketplace_source", "github"))
    custom_url = str(settings.get("marketplace_custom_url", ""))
    active_url = (
        custom_url.strip()
        if source_type == "custom" and custom_url
        else MARKET_SOURCE_PRESETS.get(source_type, MARKET_SOURCE_PRESETS["github"])
    )
    return MarketSourceConfig(
        source_type=source_type,  # type: ignore
        custom_url=custom_url,
        active_url=active_url,
    )


@router.put("/market/source", response_model=MarketSourceConfig)
async def update_market_source(
    req: UpdateMarketSourceRequest,
    _user: User = Depends(get_current_user),
) -> MarketSourceConfig:
    """切换或设置插件市场镜像源（如 GitHub 官方源、jsDelivr CDN、国内代理或本地离线源）。"""
    global _market_cache, _market_cache_time
    from backend.services.config import get_config_service
    config_service = get_config_service()

    source_type = req.source_type
    custom_url = (req.custom_url or "").strip()
    if source_type == "custom":
        if not custom_url:
            raise HTTPException(status_code=400, detail="自定义源必须提供有效的 URL")
        try:
            validate_public_http_url(custom_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"自定义源地址不安全: {exc}")

    current_settings = dict(config_service.get_global_settings() or {})
    current_settings["marketplace_source"] = source_type
    current_settings["marketplace_custom_url"] = custom_url
    config_service.save_global_settings(current_settings)
    _market_cache = None
    _market_cache_time = 0.0

    active_url = (
        custom_url
        if source_type == "custom"
        else MARKET_SOURCE_PRESETS.get(source_type, MARKET_SOURCE_PRESETS["github"])
    )
    return MarketSourceConfig(
        source_type=source_type,
        custom_url=custom_url,
        active_url=active_url,
    )


@router.get("/market/{plugin_id}/readme")
async def get_market_plugin_readme(
    plugin_id: str,
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """获取指定市场插件的 Markdown 说明文档。"""
    if not PLUGIN_ID_REGEX.match(plugin_id):
        raise HTTPException(status_code=400, detail="无效的插件标识符")
    catalog_data, _, _, _ = await _fetch_market_catalog(refresh=False)
    matched_item = next((p for p in catalog_data.get("plugins", []) if p.get("id") == plugin_id), None)

    readme_text = ""
    if matched_item and matched_item.get("readme"):
        readme_text = matched_item["readme"]
    else:
        for base in [Path.cwd() / "community_plugins", Path("/app/community_plugins")]:
            rf = base / plugin_id / "README.md"
            if rf.is_file():
                try:
                    readme_text = rf.read_text(encoding="utf-8")
                    break
                except Exception:
                    pass

    if not readme_text:
        readme_text = f"# {plugin_id}\n\n该插件暂未提供详细说明文档。"
    return {"id": plugin_id, "readme": readme_text}


async def _do_install_market_plugin(plugin_id: str, is_update: bool = False) -> PluginInfo:
    if not PLUGIN_ID_REGEX.match(plugin_id):
        raise HTTPException(status_code=400, detail="无效的插件标识符")

    catalog_data, source_type, _, _ = await _fetch_market_catalog(refresh=False)
    matched_item = next((p for p in catalog_data.get("plugins", []) if p.get("id") == plugin_id), None)
    if not matched_item:
        raise HTTPException(status_code=404, detail=f"未在插件市场中找到标识为 '{plugin_id}' 的插件")

    installed_plugins = PluginRegistry.list_plugins()
    if plugin_id in installed_plugins:
        existing = installed_plugins[plugin_id]
        if is_builtin_plugin_path(existing.source_path):
            raise HTTPException(status_code=403, detail="该插件为系统内置插件，禁止覆盖或修改")

    download_url = str(matched_item.get("download_url", ""))
    archive_bytes: Optional[bytes] = None

    is_local_download = (
        download_url.startswith("local://")
        or source_type == "local"
        or not download_url.startswith(("http://", "https://"))
    )

    if is_local_download:
        ver = matched_item.get("version", "1.0.0")
        for base in [Path.cwd() / "dist" / "marketplace" / "plugins", Path("/app/dist/marketplace/plugins")]:
            zip_file = base / f"{plugin_id}-{ver}.zip"
            if zip_file.is_file():
                try:
                    archive_bytes = zip_file.read_bytes()
                    break
                except Exception:
                    pass

        if archive_bytes is None:
            for base in [Path.cwd() / "community_plugins", Path("/app/community_plugins")]:
                pdir = base / plugin_id
                if pdir.is_dir() and (pdir / "main.py").is_file():
                    bio = io.BytesIO()
                    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as zf:
                        for f in pdir.iterdir():
                            if f.is_file() and not f.name.startswith("."):
                                zf.write(f, arcname=f.name)
                    bio.seek(0)
                    archive_bytes = bio.read()
                    break

        if archive_bytes is None:
            raise HTTPException(status_code=404, detail="本地市场未找到该插件的安装归档包")
    else:
        try:
            pinned_ip, hostname = validate_public_http_url(download_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"下载地址不安全: {exc}")

        from urllib.parse import urlparse

        import httpx

        parsed_url = urlparse(download_url)
        default_port = {"http": 80, "https": 443}.get(parsed_url.scheme)

        host_for_url = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
        netloc = host_for_url if parsed_url.port is None else f"{host_for_url}:{parsed_url.port}"
        if parsed_url.username:
            credential = parsed_url.username
            if parsed_url.password:
                credential = f"{credential}:{parsed_url.password}"
            netloc = f"{credential}@{netloc}"
        request_url = parsed_url._replace(netloc=netloc).geturl()
        host_header = hostname if parsed_url.port in (None, default_port) else f"{hostname}:{parsed_url.port}"

        try:
            async with httpx.AsyncClient(timeout=25.0, follow_redirects=False, trust_env=False) as client:
                if parsed_url.scheme == "https":
                    resp = await client.get(request_url, headers={"Host": host_header}, extensions={"sni_hostname": hostname})
                else:
                    resp = await client.get(request_url, headers={"Host": host_header})
            if resp.status_code != 200:
                raise HTTPException(status_code=400, detail=f"下载插件包失败: HTTP {resp.status_code}")
            if len(resp.content) > 10 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="插件安装包大小超过 10MB 限制")
            archive_bytes = resp.content
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"拉取远程插件包异常: {exc}")

    if not PLUGIN_ID_REGEX.match(plugin_id):
        raise HTTPException(status_code=400, detail="无效的插件标识符")

    expected_sha = matched_item.get("sha256")
    if expected_sha and archive_bytes:
        computed_sha = hashlib.sha256(archive_bytes).hexdigest()
        if computed_sha.lower() != str(expected_sha).lower():
            raise HTTPException(status_code=400, detail="插件安装包完整性校验失败 (SHA-256 不匹配)")

    import tempfile
    import uuid

    custom_dir = _get_custom_plugins_dir()
    custom_dir.mkdir(parents=True, exist_ok=True)
    custom_dir_resolved = custom_dir.resolve()

    target_plugin_dir = (custom_dir / plugin_id).resolve()
    try:
        target_plugin_dir.relative_to(custom_dir_resolved)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法的插件目录路径")

    # 使用系统临时目录进行解压与 AST 审计，彻底避免在插件扫描目录下留下临时文件
    with tempfile.TemporaryDirectory(prefix=f"market_{plugin_id}_") as stage_tmp:
        temp_dir = Path(stage_tmp)
        temp_resolved = temp_dir.resolve()
        extracted_files: List[Path] = []

        total_uncompressed = 0
        member_count = 0
        try:
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
                for member in zf.infolist():
                    member_count += 1
                    if member_count > 100:
                        raise HTTPException(status_code=400, detail="压缩包内文件数量超过 100 个限制")
                    total_uncompressed += member.file_size
                    if total_uncompressed > 20 * 1024 * 1024:
                        raise HTTPException(status_code=400, detail="压缩包解压总大小超过 20MB 限制")

                    norm_name = os.path.normpath(member.filename)
                    if (
                        norm_name.startswith(("/", "\\"))
                        or norm_name.startswith("..")
                        or "/../" in norm_name
                        or "\\..\\" in norm_name
                    ):
                        raise HTTPException(status_code=400, detail="检测到不安全的压缩包文件路径 (Zip Slip)")
                    dest_file = (temp_dir / norm_name).resolve()
                    try:
                        dest_file.relative_to(temp_resolved)
                    except ValueError:
                        raise HTTPException(status_code=400, detail="检测到不安全的压缩包文件路径 (Zip Slip)")
                    if member.is_dir():
                        dest_file.mkdir(parents=True, exist_ok=True)
                        continue
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(dest_file, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    extracted_files.append(dest_file)
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="插件安装包不是有效的 ZIP 格式")

        for ef in extracted_files:
            if ef.suffix == ".py":
                try:
                    code_text = ef.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    raise HTTPException(status_code=400, detail=f"插件代码不是合法的 UTF-8 编码 ({ef.name})")
                try:
                    tree = ast.parse(code_text, filename=ef.name)
                except SyntaxError as exc:
                    raise HTTPException(status_code=400, detail=f"插件代码语法错误 ({ef.name}): {exc}")

                visitor = _SecurityVisitor()
                visitor.visit(tree)
                forbidden = [
                    w for w in visitor.warnings
                    if w.get("severity") in ("high", "critical")
                    or "subprocess" in str(w.get("message", "")).lower()
                    or "os.system" in str(w.get("message", "")).lower()
                ]
                if forbidden:
                    raise HTTPException(status_code=400, detail=f"插件安全审计未通过: {forbidden[0]['message']}")

        if not ((temp_dir / "main.py").is_file() or (temp_dir / "__init__.py").is_file()):
            raise HTTPException(status_code=400, detail="插件包缺少入口文件 (main.py 或 __init__.py)")

        backup_dir = None
        if target_plugin_dir.exists():
            backup_dir = custom_dir / f".bak_{plugin_id}_{uuid.uuid4().hex[:8]}"
            target_plugin_dir.rename(backup_dir)

        try:
            shutil.copytree(temp_dir, target_plugin_dir)
            if backup_dir and backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)
        except Exception as exc:
            if backup_dir and backup_dir.exists():
                backup_dir.rename(target_plugin_dir)
            raise HTTPException(status_code=500, detail=f"写入插件目录失败: {exc}")

    PluginRegistry.reload_all_plugins()
    new_meta = PluginRegistry.get(plugin_id)
    if not new_meta:
        shutil.rmtree(target_plugin_dir, ignore_errors=True)
        raise HTTPException(
            status_code=400,
            detail="插件解压成功，但未能成功注册至 PluginRegistry，请检查 @PluginRegistry.register 命名",
        )

    logger.info("成功%s市场插件: %s (v%s)", "更新" if is_update else "安装", plugin_id, new_meta.version)
    return _meta_to_info(new_meta)


@router.post("/market/{plugin_id}/install", response_model=PluginInfo)
async def install_market_plugin(
    plugin_id: str,
    _user: User = Depends(get_current_user),
) -> PluginInfo:
    """从插件市场安装指定插件。"""
    return await _do_install_market_plugin(plugin_id, is_update=False)


@router.post("/market/{plugin_id}/update", response_model=PluginInfo)
async def update_market_plugin(
    plugin_id: str,
    _user: User = Depends(get_current_user),
) -> PluginInfo:
    """更新已安装的市场插件至最新版本。"""
    return await _do_install_market_plugin(plugin_id, is_update=True)


@router.delete("/market/{plugin_id}/uninstall")
async def uninstall_market_plugin(
    plugin_id: str,
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """卸载已安装的社区/市场插件。"""
    if not PLUGIN_ID_REGEX.match(plugin_id):
        raise HTTPException(status_code=400, detail="无效的插件标识符")

    meta = PluginRegistry.get(plugin_id)
    if meta and (getattr(meta, "builtin", False) or is_builtin_plugin_path(meta.source_path)):
        raise HTTPException(status_code=403, detail="官方内置插件禁止卸载")

    custom_dir = _get_custom_plugins_dir()
    custom_dir_resolved = custom_dir.resolve()
    target_dir = (custom_dir / plugin_id).resolve()
    target_file = (custom_dir / f"{plugin_id}.py").resolve()

    try:
        target_dir.relative_to(custom_dir_resolved)
        target_file.relative_to(custom_dir_resolved)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法的插件路径")

    if target_dir == custom_dir_resolved or target_file == custom_dir_resolved:
        raise HTTPException(status_code=400, detail="禁止操作插件根目录")

    deleted = False
    if target_dir.is_dir():
        shutil.rmtree(target_dir, ignore_errors=True)
        deleted = True
    elif target_file.is_file():
        target_file.unlink(missing_ok=True)
        deleted = True

    if not deleted and not meta:
        raise HTTPException(status_code=404, detail=f"未找到插件 '{plugin_id}'，无法卸载")

    if deleted:
        try:
            from backend.services.config import get_config_service
            settings = get_config_service().get_global_settings() or {}
            disabled = set(settings.get("disabled_plugins", []))
            configs = dict(settings.get("plugin_configs", {}))
            changed = False
            if plugin_id in disabled:
                disabled.remove(plugin_id)
                changed = True
            if plugin_id in configs:
                del configs[plugin_id]
                changed = True
            if changed:
                get_config_service().save_global_settings({
                    "disabled_plugins": sorted(disabled),
                    "plugin_configs": configs,
                })
        except Exception as cfg_err:
            logger.warning("清理卸载插件配置失败 (%s): %s", plugin_id, cfg_err)

    PluginRegistry.reload_all_plugins()
    logger.info("已成功卸载插件: %s", plugin_id)
    return {"success": True, "message": f"插件 '{plugin_id}' 已成功卸载"}



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
            PluginStorageBackend().clear(namespace=_plugin_test_namespace(eff_chat_id, name))
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
    # 调试执行与重置共用独立的测试命名空间，与生产持久化数据（{chat_id}:{name}）完全隔离
    ctx.storage = PluginStorageClient(namespace=_plugin_test_namespace(eff_chat_id, name))

    if req.timeout is not None and req.timeout > 0:
        # 双重钳制：即便模型校验被绕过也限制在 300s 内
        test_timeout = min(float(req.timeout), 300.0)
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
    # 子进程宿主已经记录了完整执行结果，路由只负责记录进程内执行，避免一次调试计数两次。
    if not use_subprocess:
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
    from urllib.parse import urlparse

    import httpx

    raw_url = req.url.strip()

    # SSRF 防护：白名单式校验仅放行全局可路由地址，返回钉扎 IP 避免 DNS rebinding
    try:
        pinned_ip, hostname = validate_public_http_url(raw_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    parsed_url = urlparse(raw_url)

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

    # 先备份旧源码，写入或重载失败时回滚，避免一次坏编辑永久丢失可用插件
    try:
        old_source = source_path.read_text(encoding="utf-8")
    except Exception:
        old_source = None

    def _atomic_write(text: str) -> None:
        # 先写临时文件再原子替换，避免热重载/并发读到半截文件
        tmp_path = source_path.with_name(source_path.name + ".tmp")
        tmp_path.write_text(text, encoding="utf-8")
        os.replace(tmp_path, source_path)

    try:
        _atomic_write(payload.source)
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
        if old_source is not None:
            try:
                _atomic_write(old_source)
                PluginRegistry.reload_all_plugins()
            except Exception as exc:
                logger.error("回滚插件源码失败 %s: %s", source_path, exc, exc_info=True)
        raise HTTPException(
            status_code=400,
            detail="插件代码已保存，但重载时未注册有效插件，已回滚至旧版本，请检查 @PluginRegistry.register 装饰器",
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

    # 同步清理全局配置：disabled_plugins 开关与 plugin_configs 中的孤儿参数，
    # 避免重装同名插件时静默继承旧配置
    try:
        from backend.services.config import get_config_service
        cfg_service = get_config_service()
        settings = cfg_service.get_global_settings() or {}
        dirty = False
        disabled = list(settings.get("disabled_plugins", []))
        if name in disabled:
            disabled.remove(name)
            settings["disabled_plugins"] = disabled
            dirty = True
        configs = dict(settings.get("plugin_configs", {}))
        if name in configs:
            configs.pop(name, None)
            settings["plugin_configs"] = configs
            dirty = True
        if dirty:
            cfg_service.save_global_settings(settings)
    except Exception as exc:
        logger.warning("清理插件全局配置失败: %s", exc)

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
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"插件名称 '{req.name}' 已存在")

    # 2. 确定自定义插件保存目录
    custom_dirs = [d for d in PluginRegistry.get_search_directories() if not is_builtin_plugin_path(d)]
    target_dir = custom_dirs[0] if custom_dirs else Path.cwd() / "data" / "plugins"
    target_dir.mkdir(parents=True, exist_ok=True)

    plugin_dir = target_dir / req.name
    if plugin_dir.exists():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"目录 '{req.name}' 已存在于插件目录中")

    today = datetime.now().strftime("%Y-%m-%d")
    version = req.version or "1.0.0"
    author = req.author or ""
    description = req.description or f"自定义插件 {req.name}"

    if req.template == "basic_active":
        code_text = f'''"""自定义主动执行式插件: {req.name}"""
from tg_signer.core.plugins import PluginContext, PluginRegistry

VERSION = "{version}"
UPDATED_AT = "{today}"
AUTHOR = {author!r}

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
    description={description!r},
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
AUTHOR = {author!r}

PARAMS_SCHEMA = []

@PluginRegistry.register(
    name="{req.name}",
    mode="reactive",
    description={description!r},
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
AUTHOR = {author!r}

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
    description={description!r},
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
AUTHOR = {author!r}
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
    description={description!r},
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
AUTHOR = {author!r}

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
    description={description!r},
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

    # 注入防御自检：author/description 等用户输入已经 repr 转义，此处再验证
    # 生成代码确为合法 Python 且可解析，杜绝任何模板改动引入的代码注入
    try:
        ast.parse(code_text)
    except SyntaxError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"模板生成的插件代码语法非法: {exc.msg} (第 {exc.lineno} 行)",
        )

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

    # 有界读取：最多多读 1 字节用于超限判定，避免超大上传先占满内存
    max_upload_size = 2 * 1024 * 1024
    try:
        content_bytes = await file.read(max_upload_size + 1)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"读取上传文件失败: {exc}")

    if len(content_bytes) > max_upload_size:
        raise HTTPException(status_code=413, detail="插件文件大小超过 2MB 限制")

    try:
        content = content_bytes.decode("utf-8")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"上传文件不是有效的 UTF-8 文本: {exc}")

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
    limit: int = Query(20, ge=1, le=30, description="返回条数，上限 30（与内存环形缓冲一致）"),
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

    # 替换插件名称与函数名称；使用 lambda 字面替换避免 re.sub 对替换串做
    # 反斜杠/分组引用展开，名称统一 re.escape 防止元字符注入正则
    new_code = source_code
    new_code = re.sub(
        rf'name\s*=\s*["\']{re.escape(name)}["\']',
        lambda _m: f'name="{req.new_name}"',
        new_code,
    )
    new_code = re.sub(
        rf'def\s+{re.escape(name)}_handler',
        lambda _m: f'def {req.new_name}_handler',
        new_code,
    )
    if req.description:
        # description 经 repr 生成合法 Python 字面量，引号/换行/反斜杠均被转义
        new_code = re.sub(
            r'description\s*=\s*["\'][^"\']*["\']',
            lambda _m: f'description={req.description!r}',
            new_code,
            count=1,
        )

    # AST 自检：替换后的代码必须是合法 Python，防止拼接破坏源码结构
    try:
        ast.parse(new_code, filename=f"{req.new_name}.py")
    except SyntaxError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"克隆生成的插件代码语法非法: {exc.msg} (第 {exc.lineno} 行)",
        )

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
        # 加载失败时清理已写入的孤儿文件，避免后续同名克隆永久 409
        target_file.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="克隆插件创建成功，但加载失败，已清理残留文件",
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


@router.post("/format-source", response_model=FormatPluginSourceResponse)
async def format_plugin_source_route(
    req: FormatPluginSourceRequest,
    _user: User = Depends(get_current_user),
) -> FormatPluginSourceResponse:
    """自动排版与格式化 Python 源码。"""
    try:
        tree = ast.parse(req.source, filename="<plugin_formatter>")
    except SyntaxError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"代码存在语法错误，无法格式化: {exc.msg} (第 {exc.lineno} 行)",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"代码解析异常: {exc}",
        )

    formatted_code = ""
    formatter_name = "black"
    lossy = False
    try:
        import black
        formatted_code = black.format_str(req.source, mode=black.FileMode())
    except Exception:
        # black 缺失时降级 ast.unparse：会丢失全部注释，必须向前端显式标注
        try:
            formatted_code = ast.unparse(tree)
            formatter_name = "ast"
            lossy = True
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"格式化处理失败: {exc}",
            )

    res_str = formatted_code.strip() + "\n"
    return FormatPluginSourceResponse(
        formatted=res_str,
        changed=res_str.strip() != req.source.strip(),
        formatter=formatter_name,
        lossy=lossy,
    )


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

    max_archive_size = 10 * 1024 * 1024
    max_member_size = 2 * 1024 * 1024
    max_total_size = 10 * 1024 * 1024
    max_members = 100
    content = await file.read(max_archive_size + 1)
    if len(content) > max_archive_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="插件压缩包超过 10MB 限制",
        )
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
    written_paths: List[Path] = []
    total_size = 0

    with zf:
        members = zf.infolist()
        if len(members) > max_members:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="插件压缩包文件数量超过 100 个限制",
            )
        for member in members:
            if member.is_dir():
                continue
            if not member.filename.endswith(".py"):
                continue
            if member.file_size > max_member_size:
                errors.append(f"跳过过大的插件文件: {member.filename}")
                continue
            if total_size + member.file_size > max_total_size:
                errors.append("跳过超出插件解压总大小限制的文件")
                break

            norm = Path(member.filename)
            if "\\" in member.filename or ".." in norm.parts or norm.is_absolute():
                errors.append(f"跳过不安全路径: {member.filename}")
                continue

            # 仅接受加载器可识别的布局：顶层单文件插件，或单层目录型插件（main.py/__init__.py）
            parts = [p for p in norm.parts if p != "."]
            if not (len(parts) == 1 or (len(parts) == 2 and parts[1] in ("main.py", "__init__.py"))):
                errors.append(f"跳过不支持的插件布局: {member.filename}")
                continue

            dest_path = target_dir / norm
            try:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(dest_path, "wb") as dst:
                    remaining = member.file_size
                    while remaining:
                        chunk = src.read(min(64 * 1024, remaining))
                        if not chunk:
                            break
                        dst.write(chunk)
                        remaining -= len(chunk)
                    if remaining:
                        raise ValueError("压缩包成员实际大小与声明不一致")
                total_size += member.file_size
                written_paths.append(dest_path)
            except Exception as e:
                errors.append(f"解压 {member.filename} 失败: {e}")

    PluginRegistry.reload_all_plugins()

    # 以注册表实际加载结果回填导入清单，保证响应与真实加载状态一致
    registered_by_path = {
        Path(p.source_path).resolve(): p.name
        for p in PluginRegistry.list_plugins().values()
        if p.source_path
    }
    for dest in written_paths:
        plugin_name = registered_by_path.get(dest.resolve())
        if plugin_name:
            imported_files.append(plugin_name)
        else:
            errors.append(f"文件未成功加载为插件: {dest.name}")

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

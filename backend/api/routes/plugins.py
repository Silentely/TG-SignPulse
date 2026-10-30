"""Plugin management API routes."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
)

from backend.core.auth import get_current_user
from backend.models.user import User

# Re-export all models, helpers, and Service for backward compatibility and routes
from backend.services.plugins import (
    _PLUGIN_ALLOWED_DATA_SUFFIXES,
    MARKET_SOURCE_PRESETS,
    PLUGIN_ID_REGEX,
    AuditPluginRequest,
    AuditPluginResponse,
    AuditPluginWarning,
    BatchTogglePluginsRequest,
    CheckSyntaxRequest,
    CheckSyntaxResponse,
    ClearPluginStorageResponse,
    ClonePluginRequest,
    CreatePluginRequest,
    FormatPluginSourceRequest,
    FormatPluginSourceResponse,
    ImportBundleResponse,
    InstallRemotePluginRequest,
    MarketCatalogResponse,
    MarketPluginItem,
    MarketSourceConfig,
    PluginConfigResponse,
    PluginDiagnosticsResponse,
    PluginInfo,
    PluginLoadErrorItem,
    PluginManifestItem,
    PluginMetricsModel,
    PluginService,
    PluginSourceResponse,
    PluginStorageNamespaceData,
    PluginStorageRecord,
    PluginStorageResponse,
    PluginTestRequest,
    PluginTestResponse,
    ReloadPluginsResponse,
    UpdateMarketSourceRequest,
    UpdatePluginConfigRequest,
    UpdatePluginSourceRequest,
    _build_local_plugin_archive,
    _do_install_market_plugin,
    _enforce_plugin_security_check,
    _fetch_market_catalog,
    _get_all_plugin_configs,
    _get_custom_plugins_dir,
    _get_default_params_from_schema,
    _get_disabled_plugins,
    _get_local_marketplace_catalog,
    _inspect_plugin_dependencies,
    _meta_to_info,
    _parse_semver,
    _plugin_test_namespace,
    _reload_plugins_preserving_state,
    _safe_source_path,
    _sanitize_traceback,
    _save_all_plugin_configs,
    get_plugin_service,
)
from tg_signer.core.plugin_host import PluginProcessHost
from tg_signer.core.plugins import PluginRegistry

__all__ = [
    "PluginProcessHost",
    "PluginRegistry",
    "AuditPluginRequest",
    "AuditPluginResponse",
    "AuditPluginWarning",
    "BatchTogglePluginsRequest",
    "CheckSyntaxRequest",
    "CheckSyntaxResponse",
    "ClearPluginStorageResponse",
    "ClonePluginRequest",
    "CreatePluginRequest",
    "FormatPluginSourceRequest",
    "FormatPluginSourceResponse",
    "ImportBundleResponse",
    "InstallRemotePluginRequest",
    "MarketCatalogResponse",
    "MarketPluginItem",
    "MarketSourceConfig",
    "PluginConfigResponse",
    "PluginDiagnosticsResponse",
    "PluginInfo",
    "PluginLoadErrorItem",
    "PluginManifestItem",
    "PluginMetricsModel",
    "PluginService",
    "PluginSourceResponse",
    "PluginStorageNamespaceData",
    "PluginStorageRecord",
    "PluginStorageResponse",
    "PluginTestRequest",
    "PluginTestResponse",
    "ReloadPluginsResponse",
    "UpdateMarketSourceRequest",
    "UpdatePluginConfigRequest",
    "UpdatePluginSourceRequest",
    "_PLUGIN_ALLOWED_DATA_SUFFIXES",
    "_build_local_plugin_archive",
    "_do_install_market_plugin",
    "_enforce_plugin_security_check",
    "_fetch_market_catalog",
    "_get_all_plugin_configs",
    "_get_custom_plugins_dir",
    "_get_default_params_from_schema",
    "_get_disabled_plugins",
    "_get_local_marketplace_catalog",
    "_inspect_plugin_dependencies",
    "_meta_to_info",
    "_parse_semver",
    "_plugin_test_namespace",
    "_reload_plugins_preserving_state",
    "_safe_source_path",
    "_sanitize_traceback",
    "_save_all_plugin_configs",
    "get_plugin_service",
    "MARKET_SOURCE_PRESETS",
    "PLUGIN_ID_REGEX",
    "get_plugin_diagnostics",
    "list_plugins",
    "reload_plugins",
    "list_market_plugins",
    "get_market_source",
    "update_market_source",
    "get_market_plugin_readme",
    "install_market_plugin",
    "update_market_plugin",
    "uninstall_market_plugin",
    "toggle_plugin",
    "test_plugin",
    "install_remote_plugin",
    "get_plugin_source",
    "update_plugin_source",
    "delete_plugin",
    "create_plugin_from_template",
    "export_plugin",
    "upload_plugin",
    "reset_plugin_metrics",
    "batch_toggle_plugins",
    "reset_all_plugin_metrics",
    "get_plugin_history",
    "clear_plugin_history",
    "clone_plugin",
    "get_plugin_dependencies",
    "get_plugin_storage",
    "clear_plugin_storage",
    "get_plugin_config",
    "update_plugin_config",
    "get_plugins_manifest",
    "export_all_plugins",
    "check_plugin_syntax",
    "audit_plugin_source_route",
    "format_plugin_source_route",
    "import_plugins_bundle",
    "reset_plugin_config",
]

router = APIRouter()
logger = logging.getLogger("backend.plugins_api")


def _resolve_service(service: Any) -> PluginService:
    if isinstance(service, PluginService):
        return service
    return get_plugin_service()


@router.get("/diagnostics", response_model=PluginDiagnosticsResponse)
async def get_plugin_diagnostics(
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> PluginDiagnosticsResponse:
    """获取插件加载诊断与加载失败项。"""
    return await _resolve_service(service).get_diagnostics()


@router.get("", response_model=List[PluginInfo])
async def list_plugins(
    mode: Optional[Literal["reactive", "active"]] = Query(
        default=None, description="按模式过滤 (reactive/active)"
    ),
    category: Optional[str] = Query(default=None, description="按插件分类过滤"),
    enabled: Optional[bool] = Query(default=None, description="按启用状态过滤"),
    search: Optional[str] = Query(default=None, description="按名称、描述或标签搜索"),
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> List[PluginInfo]:
    """获取所有已加载的自定义插件列表（支持按模式、分类、状态及关键词筛选）。"""
    return await _resolve_service(service).list_plugins(
        mode=mode, category=category, enabled=enabled, search=search
    )


@router.post("/reload", response_model=ReloadPluginsResponse)
async def reload_plugins(
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> ReloadPluginsResponse:
    """重新扫描并加载所有配置的插件目录。"""
    return await _resolve_service(service).reload_plugins()


@router.get("/market", response_model=MarketCatalogResponse)
async def list_market_plugins(
    refresh: bool = Query(default=False, description="是否强制刷新市场目录缓存"),
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> MarketCatalogResponse:
    """获取插件市场所有可用的插件清单，并附带当前环境的本地安装/可更新状态。"""
    return await _resolve_service(service).list_market_catalog(refresh=refresh)


@router.get("/market/source", response_model=MarketSourceConfig)
async def get_market_source(
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> MarketSourceConfig:
    """获取当前配置的插件市场源信息。"""
    return await _resolve_service(service).get_market_source()


@router.put("/market/source", response_model=MarketSourceConfig)
async def update_market_source(
    req: UpdateMarketSourceRequest,
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> MarketSourceConfig:
    """切换或设置插件市场镜像源（如 GitHub 官方源、jsDelivr CDN、国内代理或本地离线源）。"""
    return await _resolve_service(service).update_market_source(req)


@router.get("/market/{plugin_id}/readme")
async def get_market_plugin_readme(
    plugin_id: str,
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> Dict[str, Any]:
    """获取指定市场插件的 Markdown 说明文档。"""
    return await _resolve_service(service).get_market_readme(plugin_id)


@router.post("/market/{plugin_id}/install", response_model=PluginInfo)
async def install_market_plugin(
    plugin_id: str,
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> PluginInfo:
    """从插件市场安装指定插件。"""
    return await _resolve_service(service).install_market_plugin(plugin_id)


@router.post("/market/{plugin_id}/update", response_model=PluginInfo)
async def update_market_plugin(
    plugin_id: str,
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> PluginInfo:
    """更新已安装的市场插件至最新版本。"""
    return await _resolve_service(service).update_market_plugin(plugin_id)


@router.delete("/market/{plugin_id}/uninstall")
async def uninstall_market_plugin(
    plugin_id: str,
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> Dict[str, Any]:
    """卸载已安装的社区/市场插件。"""
    return await _resolve_service(service).uninstall_market_plugin(plugin_id)


@router.post("/{name}/toggle", response_model=PluginInfo)
async def toggle_plugin(
    name: str,
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> PluginInfo:
    """切换插件的启用/停用软开关状态。"""
    return await _resolve_service(service).toggle_plugin(name)


@router.post("/{name}/test", response_model=PluginTestResponse)
async def test_plugin(
    name: str,
    req: PluginTestRequest,
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> PluginTestResponse:
    """在宿主进程内模拟执行指定插件，仅用于测试可信插件。"""
    return await _resolve_service(service).test_run_plugin(name, req)


@router.post("/install-remote", response_model=PluginInfo)
async def install_remote_plugin(
    req: InstallRemotePluginRequest,
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> PluginInfo:
    """从远程 URL 下载并安装自定义插件。"""
    return await _resolve_service(service).install_remote_plugin(req)


@router.get("/{name}/source", response_model=PluginSourceResponse)
async def get_plugin_source(
    name: str,
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> PluginSourceResponse:
    """查看指定插件的 Python 源代码（内置插件只读，自定义插件可读写）。"""
    return await _resolve_service(service).get_plugin_source(name)


@router.put("/{name}/source", response_model=PluginInfo)
async def update_plugin_source(
    name: str,
    payload: UpdatePluginSourceRequest,
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> PluginInfo:
    """在线更新自定义插件源码并热重载。"""
    return await _resolve_service(service).update_plugin_source(
        name, payload.source, force=payload.force
    )


@router.delete("/{name}")
async def delete_plugin(
    name: str,
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> Dict[str, Any]:
    """删除指定的自定义插件（官方内置插件禁止删除）。"""
    return await _resolve_service(service).delete_plugin(name)


@router.post("/create", response_model=PluginInfo)
async def create_plugin_from_template(
    req: CreatePluginRequest,
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> PluginInfo:
    """根据模板脚手架在线创建自定义插件。"""
    return await _resolve_service(service).create_plugin(req)


@router.get("/{name}/export")
async def export_plugin(
    name: str,
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> Response:
    """导出并下载指定插件的 .py 源码文件。"""
    content, filename = await _resolve_service(service).export_plugin(name)
    return Response(
        content=content,
        media_type="text/x-python; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/upload", response_model=PluginInfo)
async def upload_plugin(
    file: UploadFile = File(...),
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> PluginInfo:
    """上传本地 .py 插件文件至自定义插件目录并热重载。"""
    max_upload_size = 2 * 1024 * 1024
    try:
        content_bytes = await file.read(max_upload_size + 1)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"读取上传文件失败: {exc}")
    return await _resolve_service(service).upload_plugin(
        content_bytes, file.filename or ""
    )


@router.post("/{name}/reset-metrics")
async def reset_plugin_metrics(
    name: str,
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> Dict[str, Any]:
    """重置指定插件的运行统计指标。"""
    return await _resolve_service(service).reset_metrics(name)


@router.post("/batch-toggle")
async def batch_toggle_plugins(
    payload: BatchTogglePluginsRequest,
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> Dict[str, Any]:
    """批量启用或停用所有自定义插件。"""
    return await _resolve_service(service).batch_toggle_plugins(
        payload_or_enabled=payload.enabled
    )


@router.post("/reset-all-metrics")
async def reset_all_plugin_metrics(
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> Dict[str, Any]:
    """批量重置所有插件的运行统计指标。"""
    return await _resolve_service(service).reset_all_metrics()


@router.get("/{name}/history")
async def get_plugin_history(
    name: str,
    limit: int = Query(
        20, ge=1, le=30, description="返回条数，上限 30（与内存环形缓冲一致）"
    ),
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> Dict[str, Any]:
    """获取指定插件最近的执行调用历史记录。"""
    return await _resolve_service(service).get_execution_history(name, limit=limit)


@router.post("/{name}/clear-history")
async def clear_plugin_history(
    name: str,
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> Dict[str, Any]:
    """清空指定插件的调用历史记录。"""
    return await _resolve_service(service).clear_execution_history(name)


@router.post("/{name}/clone", response_model=PluginInfo)
async def clone_plugin(
    name: str,
    req: ClonePluginRequest,
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> PluginInfo:
    """基于现有插件克隆生成一个新的自定义插件。"""
    return await _resolve_service(service).clone_plugin(
        name, req.new_name, req.description
    )


@router.get("/{name}/dependencies")
async def get_plugin_dependencies(
    name: str,
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> Dict[str, Any]:
    """静态解析指定插件的三方依赖库，并检测当前运行环境中是否已安装。"""
    return await _resolve_service(service).get_dependencies(name)


@router.get("/{name}/storage", response_model=PluginStorageResponse)
async def get_plugin_storage(
    name: str,
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> PluginStorageResponse:
    """获取指定插件当前持久化存储的所有命名空间与结构化数据记录。"""
    return await _resolve_service(service).get_storage(name)


@router.delete("/{name}/storage", response_model=ClearPluginStorageResponse)
async def clear_plugin_storage(
    name: str,
    namespace: Optional[str] = Query(
        default=None, description="指定清理的命名空间；不传则清理该插件所有命名空间"
    ),
    key: Optional[str] = Query(
        default=None, description="指定清理的单个键名；需同时提供 namespace"
    ),
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> ClearPluginStorageResponse:
    """清理指定插件的持久化存储数据（支持全量清空、指定命名空间清空或删除指定键）。"""
    return await _resolve_service(service).clear_storage(
        name, namespace=namespace, key=key
    )


@router.get("/{name}/config", response_model=PluginConfigResponse)
async def get_plugin_config(
    name: str,
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> PluginConfigResponse:
    """获取插件全局配置参数。若尚未自定义保存，则返回 params_schema 中声明的默认值。"""
    return await _resolve_service(service).get_config(name)


@router.put("/{name}/config", response_model=PluginConfigResponse)
async def update_plugin_config(
    name: str,
    req: UpdatePluginConfigRequest,
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> PluginConfigResponse:
    """保存插件全局参数配置。"""
    return await _resolve_service(service).update_config(name, req.params)


@router.get("/manifest", response_model=List[PluginManifestItem])
async def get_plugins_manifest(
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> List[PluginManifestItem]:
    """导出当前所有插件的元数据清单列表。"""
    return await _resolve_service(service).get_manifest()


@router.get("/export-all")
async def export_all_plugins(
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
):
    """将所有用户自定义插件打包为 ZIP 归档文件并下载。"""
    zip_bytes, filename = await _resolve_service(service).export_all_plugins()
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
    service: PluginService = Depends(get_plugin_service),
) -> CheckSyntaxResponse:
    """校验 Python 代码语法是否正确。"""
    return await _resolve_service(service).check_syntax(req.source)


@router.post("/audit-source", response_model=AuditPluginResponse)
async def audit_plugin_source_route(
    req: AuditPluginRequest,
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> AuditPluginResponse:
    """基于 AST 静态分析在线审查插件源码的安全隐患与权限声明。"""
    return await _resolve_service(service).audit_source(req.source)


@router.post("/format-source", response_model=FormatPluginSourceResponse)
async def format_plugin_source_route(
    req: FormatPluginSourceRequest,
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> FormatPluginSourceResponse:
    """自动排版与格式化 Python 源码。"""
    return await _resolve_service(service).format_source(req.source)


@router.post("/import-bundle", response_model=ImportBundleResponse)
async def import_plugins_bundle(
    file: UploadFile = File(...),
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> ImportBundleResponse:
    """上传 ZIP 压缩包，批量安全解压并热重载自定义插件。"""
    max_archive_size = 10 * 1024 * 1024
    content = await file.read(max_archive_size + 1)
    return await _resolve_service(service).import_bundle(content, file.filename or "")


@router.post("/{name}/reset-config", response_model=PluginConfigResponse)
async def reset_plugin_config(
    name: str,
    _user: User = Depends(get_current_user),
    service: PluginService = Depends(get_plugin_service),
) -> PluginConfigResponse:
    """清空插件自定义配置，恢复为 params_schema 中的默认值。"""
    return await _resolve_service(service).reset_config(name)

"""
运维辅助 API：调度预览、备份状态、进程指标。
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from backend.core.auth import get_current_user
from backend.core.config import get_settings
from backend.models.user import User

logger = logging.getLogger("backend.ops")

router = APIRouter()


class ScheduledJobOut(BaseModel):
    id: str
    name: str = ""
    next_run_time: Optional[str] = None
    trigger: str = ""
    kind: str = Field(
        "other", description="sign / legacy_db / system / other"
    )


class ScheduledJobsResponse(BaseModel):
    jobs: List[ScheduledJobOut]
    total: int
    timezone: str = ""


class BackupStatusResponse(BaseModel):
    data_dir: str
    writable: bool
    size_bytes: int = 0
    size_human: str = ""
    entries: List[Dict[str, Any]] = Field(default_factory=list)
    recommended_paths: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
    restore_hint: str = ""
    webdav_configured: bool = False
    auto_backup_enabled: bool = False
    local_auto_backups: List[Dict[str, Any]] = Field(default_factory=list)


# 完整备份包含的路径（不含初始密码文件，降低误传风险）
BACKUP_ARCHIVE_PATHS = (
    "db.sqlite",
    "db.sqlite-wal",
    "db.sqlite-shm",
    "sessions",
    ".signer",
    ".global_settings.json",
    ".openai_config.json",
    ".telegram_api.json",
)

BACKUP_STATUS_PATHS = (
    "db.sqlite",
    "sessions",
    ".signer",
    ".global_settings.json",
    ".openai_config.json",
    ".telegram_api.json",
)


class MemoryStatsResponse(BaseModel):
    available: bool
    stats: Dict[str, Any] = Field(default_factory=dict)


def _human_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{num} B"


def _dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


@router.get("/scheduled-jobs", response_model=ScheduledJobsResponse)
def list_scheduled_jobs(current_user: User = Depends(get_current_user)):
    """列出 APScheduler 中的待执行任务（下次运行时间）。"""
    from backend.scheduler import scheduler

    if scheduler is None:
        return ScheduledJobsResponse(jobs=[], total=0, timezone="")

    jobs_out: List[ScheduledJobOut] = []
    for job in scheduler.get_jobs():
        jid = str(job.id or "")
        if jid.startswith("sign-"):
            kind = "sign"
        elif jid.startswith("db-"):
            kind = "legacy_db"
        elif jid.startswith("system-"):
            kind = "system"
        else:
            kind = "other"
        next_run = job.next_run_time
        next_iso = None
        if next_run is not None:
            try:
                if next_run.tzinfo is None:
                    next_iso = next_run.replace(tzinfo=timezone.utc).isoformat()
                else:
                    next_iso = next_run.isoformat()
            except Exception:
                next_iso = str(next_run)
        jobs_out.append(
            ScheduledJobOut(
                id=jid,
                name=str(getattr(job, "name", None) or jid),
                next_run_time=next_iso,
                trigger=str(job.trigger) if job.trigger is not None else "",
                kind=kind,
            )
        )

    jobs_out.sort(key=lambda j: j.next_run_time or "9999")
    tz = str(getattr(scheduler, "timezone", "") or "")
    return ScheduledJobsResponse(jobs=jobs_out, total=len(jobs_out), timezone=tz)


@router.get("/backup/status", response_model=BackupStatusResponse)
def backup_status(current_user: User = Depends(get_current_user)):
    """返回数据目录备份相关状态，便于面板提示运维。"""
    from backend.services.config import get_config_service
    from backend.utils.storage import is_writable_dir

    settings = get_settings()
    data_dir = Path(settings.resolve_base_dir())
    recommended = list(BACKUP_STATUS_PATHS)
    entries: List[Dict[str, Any]] = []
    total = 0
    for rel in recommended:
        p = data_dir / rel
        size = _dir_size(p) if p.exists() else 0
        total += size
        entries.append(
            {
                "path": rel,
                "exists": p.exists(),
                "size_bytes": size,
                "size_human": _human_size(size),
            }
        )
    try:
        total = max(total, _dir_size(data_dir))
    except Exception as exc:
        logger.debug("计算数据目录大小失败: %s", exc)

    cfg = get_config_service().get_global_settings()
    webdav_configured = bool((cfg.get("webdav_url") or "").strip())
    auto_backup_enabled = bool(cfg.get("auto_backup_enabled"))

    local_auto: List[Dict[str, Any]] = []
    backup_dir = data_dir / "backups"
    if backup_dir.is_dir():
        files = sorted(
            backup_dir.glob("auto-*.tar.gz"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:5]
        for f in files:
            try:
                st = f.stat()
                local_auto.append(
                    {
                        "name": f.name,
                        "size_bytes": st.st_size,
                        "size_human": _human_size(st.st_size),
                        "mtime": datetime.fromtimestamp(
                            st.st_mtime, tz=timezone.utc
                        ).isoformat(),
                    }
                )
            except OSError:
                continue

    return BackupStatusResponse(
        data_dir=str(data_dir),
        writable=is_writable_dir(data_dir),
        size_bytes=total,
        size_human=_human_size(total),
        entries=entries,
        recommended_paths=recommended,
        notes=[
            "完整备份含数据库、会话与 .signer（任务配置与历史），敏感请妥善保管。",
            "JSON 配置导出不含会话；二者用途不同，勿混用。",
            "不含 .admin_bootstrap_password（避免初始密码随备份传播）。",
            "自动备份在 WebDAV 上传成功后会删除本地副本；失败时保留本地文件。",
        ],
        restore_hint=(
            "恢复：停止服务 → 解压 tar.gz 到 APP_DATA_DIR 覆盖对应路径 → 重启。"
            "详见文档运维手册。"
        ),
        webdav_configured=webdav_configured,
        auto_backup_enabled=auto_backup_enabled,
        local_auto_backups=local_auto,
    )


@router.post("/backup/export")
def export_backup_archive(current_user: User = Depends(get_current_user)):
    """
    打包 data 目录关键路径为 tar.gz 并上传到 WebDAV。

    WebDAV 配置取自全局设置（webdav_url / username / password / remote_dir）。
    兼容旧客户端：若未配置 WebDAV，仍可回退为浏览器下载。
    """
    from backend.services.backup_archive import create_backup_tarball
    from backend.services.config import get_config_service
    from backend.services.webdav_client import upload_file_to_webdav

    settings = get_settings()
    data_dir = Path(settings.resolve_base_dir())
    if not data_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据目录不存在",
        )

    cfg = get_config_service().get_global_settings()
    webdav_url = (cfg.get("webdav_url") or "").strip()
    webdav_user = str(cfg.get("webdav_username") or "").strip()
    webdav_password = str(cfg.get("webdav_password") or "")
    webdav_remote = str(
        cfg.get("webdav_remote_dir") or "tg-signpulse-backups"
    ).strip() or "tg-signpulse-backups"

    # 已声明 WebDAV 时先校验凭据，避免空打包后再失败
    if webdav_url:
        if not webdav_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="WebDAV 用户名未配置，请先保存用户名",
            )
        if not webdav_password.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="WebDAV 密码未配置，请先填写并保存密码",
            )

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    tmp_dir = Path(tempfile.mkdtemp(prefix="tg-signpulse-backup-"))
    archive_path = tmp_dir / f"tg-signpulse-backup-{ts}.tar.gz"

    try:
        create_backup_tarball(data_dir, archive_path, BACKUP_ARCHIVE_PATHS)
        if not archive_path.exists() or archive_path.stat().st_size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="没有可备份的文件",
            )

        if webdav_url:
            try:
                result = upload_file_to_webdav(
                    base_url=webdav_url,
                    username=webdav_user,
                    password=webdav_password,
                    remote_dir=webdav_remote,
                    local_path=archive_path,
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                ) from exc
            except Exception as exc:
                logger.exception("WebDAV 上传失败")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"WebDAV 上传失败: {exc}",
                ) from exc
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            return {
                "success": True,
                "message": "备份已上传到 WebDAV",
                "remote_url": result.get("remote_url"),
                "filename": result.get("filename"),
                "size_bytes": result.get("size_bytes"),
            }

        # 未配置 WebDAV：回退为本地下载
        def _cleanup() -> None:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        return FileResponse(
            path=str(archive_path),
            filename=archive_path.name,
            media_type="application/gzip",
            background=BackgroundTask(_cleanup),
        )
    except HTTPException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except ValueError as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        logger.exception("导出备份失败")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"导出备份失败: {exc}",
        ) from exc


class WebDavTestResponse(BaseModel):
    success: bool
    message: str
    status_code: Optional[int] = None


@router.post("/backup/webdav/test", response_model=WebDavTestResponse)
def test_webdav_backup(current_user: User = Depends(get_current_user)):
    """测试已保存的 WebDAV 配置连通性。"""
    from backend.services.config import get_config_service
    from backend.services.webdav_client import test_webdav_connection

    cfg = get_config_service().get_global_settings()
    try:
        result = test_webdav_connection(
            base_url=str(cfg.get("webdav_url") or ""),
            username=str(cfg.get("webdav_username") or ""),
            password=str(cfg.get("webdav_password") or ""),
            remote_dir=str(cfg.get("webdav_remote_dir") or "tg-signpulse-backups"),
        )
        return WebDavTestResponse(**result)
    except ValueError as exc:
        return WebDavTestResponse(success=False, message=str(exc))
    except Exception as exc:
        logger.exception("WebDAV 测试失败")
        return WebDavTestResponse(success=False, message=f"测试失败: {exc}")


class WebDavFileEntry(BaseModel):
    name: str
    href: str = ""
    size_bytes: Optional[int] = None
    mtime: Optional[str] = None


class WebDavListResponse(BaseModel):
    success: bool
    files: List[WebDavFileEntry] = Field(default_factory=list)
    message: str = ""
    status_code: Optional[int] = None


@router.get("/backup/webdav/files", response_model=WebDavListResponse)
def list_webdav_backup_files(current_user: User = Depends(get_current_user)):
    """列出已保存 WebDAV 配置下远端目录中的 .tar.gz 备份。"""
    from backend.services.config import get_config_service
    from backend.services.webdav_client import list_webdav_files

    cfg = get_config_service().get_global_settings()
    url = (cfg.get("webdav_url") or "").strip()
    if not url:
        return WebDavListResponse(
            success=False,
            message="未配置 WebDAV URL",
        )
    try:
        result = list_webdav_files(
            base_url=url,
            username=str(cfg.get("webdav_username") or ""),
            password=str(cfg.get("webdav_password") or ""),
            remote_dir=str(cfg.get("webdav_remote_dir") or "tg-signpulse-backups"),
            name_suffix=".tar.gz",
            limit=20,
        )
        files = [WebDavFileEntry(**f) for f in (result.get("files") or [])]
        return WebDavListResponse(
            success=bool(result.get("success")),
            files=files,
            message=str(result.get("message") or ""),
            status_code=result.get("status_code"),
        )
    except ValueError as exc:
        return WebDavListResponse(success=False, message=str(exc))
    except Exception as exc:
        logger.exception("WebDAV 列表失败")
        return WebDavListResponse(success=False, message=f"列表失败: {exc}")


@router.get("/backup/webdav/download")
def download_webdav_backup_file(
    name: str,
    current_user: User = Depends(get_current_user),
):
    """
    从已配置 WebDAV 流式下载指定备份包到浏览器。

    仅允许安全的 .tar.gz 文件名；不整包落盘到服务端临时目录。
    不直接解压恢复（恢复请离线覆盖 data/）。
    """
    from fastapi.responses import StreamingResponse

    from backend.services.config import get_config_service
    from backend.services.webdav_client import (
        iter_webdav_file,
        validate_backup_filename,
    )

    try:
        safe_name = validate_backup_filename(name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    cfg = get_config_service().get_global_settings()
    url = (cfg.get("webdav_url") or "").strip()
    if not url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="未配置 WebDAV URL",
        )

    try:
        # 先拉取首块以尽早失败；再拼接剩余流
        stream = iter_webdav_file(
            base_url=url,
            username=str(cfg.get("webdav_username") or ""),
            password=str(cfg.get("webdav_password") or ""),
            remote_dir=str(cfg.get("webdav_remote_dir") or "tg-signpulse-backups"),
            filename=safe_name,
        )
        first = next(stream)

        def _body():
            yield first
            yield from stream

        return StreamingResponse(
            _body(),
            media_type="application/gzip",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_name}"',
            },
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except StopIteration:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WebDAV 下载结果为空",
        ) from None
    except Exception as exc:
        logger.exception("WebDAV 下载失败")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"WebDAV 下载失败: {exc}",
        ) from exc


@router.get("/memory", response_model=MemoryStatsResponse)
def memory_stats(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """返回内存监控统计（若已启动）。"""
    try:
        monitor = getattr(request.app.state, "memory_monitor", None)
        if monitor is None:
            return MemoryStatsResponse(available=False, stats={})
        return MemoryStatsResponse(available=True, stats=monitor.get_stats())
    except Exception as exc:
        logger.debug("读取内存统计失败: %s", exc)
        return MemoryStatsResponse(available=False, stats={"error": str(exc)})


class RuntimeStatusResponse(BaseModel):
    ready: bool
    scheduler_lock_held: bool = False
    legacy_tasks_writable: bool = False
    database_is_sqlite: bool = True
    monitor_shard: str = ""
    monitor_allowlist: str = ""


@router.get("/runtime-status", response_model=RuntimeStatusResponse)
def runtime_status(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """面板/运维用运行时摘要（需登录）。"""
    import os

    from backend.api.routes.tasks import _legacy_writes_allowed
    from backend.core.config import get_settings
    from backend.scheduler.instance_lock import has_scheduler_lock

    settings = get_settings()
    return RuntimeStatusResponse(
        ready=bool(getattr(request.app.state, "ready", False)),
        scheduler_lock_held=has_scheduler_lock(),
        legacy_tasks_writable=_legacy_writes_allowed(),
        database_is_sqlite=settings.is_sqlite,
        monitor_shard=os.getenv("APP_MONITOR_SHARD", "") or "",
        monitor_allowlist=os.getenv("APP_MONITOR_ACCOUNT_ALLOWLIST", "") or "",
    )


class VersionInfoResponse(BaseModel):
    version: str
    git_sha: str = ""
    git_branch: str = ""
    build_time: str = ""
    app_name: str = ""
    python: str = ""
    update_check_enabled: bool = True


class UpdateCheckInfo(BaseModel):
    enabled: bool
    latest_version: Optional[str] = None
    latest_url: Optional[str] = None
    update_available: bool = False
    checked_at: Optional[str] = None
    error: Optional[str] = None
    source: str = "github_releases"
    cached: bool = False


class VersionCheckResponse(VersionInfoResponse):
    update_check: UpdateCheckInfo


@router.get("/version", response_model=VersionInfoResponse)
def get_version(current_user: User = Depends(get_current_user)):
    """返回本地版本与构建元数据（无外网请求）。"""
    from backend.utils.version_info import get_local_version_info

    return VersionInfoResponse(**get_local_version_info())


@router.post("/version/check", response_model=VersionCheckResponse)
def check_version(
    force: bool = False,
    current_user: User = Depends(get_current_user),
):
    """本地版本 + 可选远程更新检查。

    force=true 时跳过服务端缓存。远程失败 soft-fail，HTTP 仍 200。
    """
    from backend.utils.version_info import (
        check_remote_update,
        get_local_version_info,
    )

    local = get_local_version_info()
    remote = check_remote_update(force=force)
    return VersionCheckResponse(
        **local,
        update_check=UpdateCheckInfo(**remote),
    )

"""
运维辅助 API：调度预览、备份状态、进程指标。
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
import time
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
from backend.scheduler.instance_lock import has_scheduler_lock
from backend.services.s3_backup import s3_enabled

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
    execution_mode: Optional[str] = None
    range_start: Optional[str] = None
    range_end: Optional[str] = None
    task_name: Optional[str] = None
    account_name: Optional[str] = None


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
    s3_configured: bool = False
    backup_target: str = "auto"
    auto_backup_enabled: bool = False
    local_auto_backups: List[Dict[str, Any]] = Field(default_factory=list)


# 完整备份包含的路径（不含初始密码文件，降低误传风险）
def _extract_webdav_proxy(cfg: Dict[str, Any]) -> Optional[str]:
    """从配置字典中提取 WebDAV 代理设置（优先 webdav_proxy，回退全局 proxy）。"""
    return str(cfg.get("webdav_proxy") or cfg.get("proxy") or "").strip() or None

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
    if num is None or num < 0:
        return "0 B"
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


# backup/status 的 total 全量扫盘缓存：os.walk 整目录含全部会话与备份包，
# 每次请求重扫开销大；短 TTL 足以反映备份增减
_DIR_SIZE_CACHE_TTL_SECONDS = 60.0
_dir_size_cache: Dict[str, tuple[float, int]] = {}
_dir_size_lock = threading.Lock()


def _dir_size_cached(path: Path) -> int:
    key = str(path)
    now = time.monotonic()
    with _dir_size_lock:
        cached = _dir_size_cache.get(key)
        if cached is not None and now - cached[0] < _DIR_SIZE_CACHE_TTL_SECONDS:
            return cached[1]
    size = _dir_size(path)
    with _dir_size_lock:
        _dir_size_cache[key] = (now, size)
    return size


@router.get("/scheduled-jobs", response_model=ScheduledJobsResponse)
def list_scheduled_jobs(current_user: User = Depends(get_current_user)):
    """列出 APScheduler 中的待执行任务（下次运行时间）。"""
    from backend.scheduler import scheduler

    if scheduler is None:
        return ScheduledJobsResponse(jobs=[], total=0, timezone="")

    task_map: Dict[Any, Dict[str, Any]] = {}
    try:
        from backend.services.sign_tasks import get_sign_task_service

        for t in get_sign_task_service().list_tasks():
            acc = str(t.get("account_name") or "")
            nm = str(t.get("name") or "")
            if nm:
                if acc:
                    task_map[(acc, nm)] = t
                    task_map[f"sign-{acc}-{nm}"] = t
    except Exception as exc:
        logger.debug("预拉取签到任务配置失败: %s", exc)

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

        execution_mode = None
        range_start = None
        range_end = None
        task_name = None
        account_name = None

        if kind == "sign":
            if getattr(job, "args", None) and len(job.args) >= 2:
                account_name = str(job.args[0])
                task_name = str(job.args[1])
            task_info = (
                task_map.get((account_name, task_name))
                or task_map.get(jid)
            )
            if task_info:
                execution_mode = task_info.get("execution_mode") or "fixed"
                range_start = task_info.get("range_start")
                range_end = task_info.get("range_end")
                if not task_name:
                    task_name = task_info.get("name")
                if not account_name:
                    account_name = task_info.get("account_name")

        jobs_out.append(
            ScheduledJobOut(
                id=jid,
                name=str(getattr(job, "name", None) or jid),
                next_run_time=next_iso,
                trigger=str(job.trigger) if job.trigger is not None else "",
                kind=kind,
                execution_mode=execution_mode,
                range_start=range_start,
                range_end=range_end,
                task_name=task_name,
                account_name=account_name,
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
        total = max(total, _dir_size_cached(data_dir))
    except Exception as exc:
        logger.debug("计算数据目录大小失败: %s", exc)

    cfg = get_config_service().get_global_settings()
    webdav_configured = bool((cfg.get("webdav_url") or "").strip())
    s3_configured = s3_enabled(cfg)
    auto_backup_enabled = bool(cfg.get("auto_backup_enabled"))

    local_auto: List[Dict[str, Any]] = []
    backup_dir = data_dir / "backups"
    if backup_dir.is_dir():
        # glob 到 stat 之间文件可能被并发清理（prune/上传后删副本）：
        # 先带容错收集 (mtime, path)，避免 FileNotFoundError 使整个接口 500
        stat_entries: List[tuple[float, Path]] = []
        for p in backup_dir.glob("auto-*.tar.gz"):
            try:
                stat_entries.append((p.stat().st_mtime, p))
            except OSError:
                continue
        files = [
            p
            for _, p in sorted(stat_entries, key=lambda item: item[0], reverse=True)
        ][:5]
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
            "自动备份在 WebDAV / 对象存储上传成功后会删除本地副本；失败时保留本地文件。",
            "备份落点策略支持智能选择、仅 WebDAV、仅对象存储以及双端同时备份（both）。",
        ],
        restore_hint=(
            "恢复：停止服务 → 解压 tar.gz 到 APP_DATA_DIR 覆盖对应路径 → 重启。"
            "详见文档运维手册。"
        ),
        webdav_configured=webdav_configured,
        backup_target=str(cfg.get("backup_target") or "auto"),
        s3_configured=s3_configured,
        auto_backup_enabled=auto_backup_enabled,
        local_auto_backups=local_auto,
    )


@router.post("/backup/export")
async def export_backup_archive(current_user: User = Depends(get_current_user)):
    """
    打包 data 目录关键路径为 tar.gz 并上传到远端。

    优先级：WebDAV（webdav_url 已配置）→ 对象存储（s3_enabled 且必填项齐全）
    → 浏览器下载（二者均未配置时的兼容回退）。
    远端配置均取自全局设置。
    """
    from backend.services.backup_archive import create_backup_tarball
    from backend.services.config import get_config_service
    from backend.services.s3_backup import s3_enabled, upload_backup_to_s3
    from backend.services.webdav_client import upload_file_to_webdav

    settings = get_settings()
    data_dir = Path(settings.resolve_base_dir())
    if not data_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据目录不存在",
        )

    cfg = get_config_service().get_global_settings()
    backup_target = str(cfg.get("backup_target") or "auto").strip().lower()
    if backup_target not in {"auto", "webdav", "s3", "both"}:
        backup_target = "auto"

    webdav_url = (cfg.get("webdav_url") or "").strip()
    s3_ready = s3_enabled(cfg)
    webdav_user = str(cfg.get("webdav_username") or "").strip()
    webdav_password = str(cfg.get("webdav_password") or "")
    webdav_remote = str(
        cfg.get("webdav_remote_dir") or "tg-signpulse-backups"
    ).strip() or "tg-signpulse-backups"

    # 显式策略强校验，避免静默降级
    if backup_target == "both":
        if not webdav_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="备份目标为双端备份（both），但 WebDAV 服务地址未配置",
            )
        if not s3_ready:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="备份目标为双端备份（both），但对象存储未启用或凭据未配置完整",
            )
        do_webdav = True
        do_s3 = True
    elif backup_target == "s3":
        if not s3_ready:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="备份目标为仅对象存储（s3），但对象存储未启用或凭据未配置完整",
            )
        do_webdav = False
        do_s3 = True
    elif backup_target == "webdav":
        if not webdav_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="备份目标为仅 WebDAV，但 WebDAV 服务地址未配置",
            )
        do_webdav = True
        do_s3 = False
    else:  # auto
        do_webdav = bool(webdav_url)
        do_s3 = bool(not do_webdav and s3_ready)

    # 校验 WebDAV 凭据
    if do_webdav:
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

    # 备份文件名用 UTC，与自动备份/命中导出的时间口径一致
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    tmp_dir = Path(tempfile.mkdtemp(prefix="tg-signpulse-backup-"))
    archive_path = tmp_dir / f"tg-signpulse-backup-{ts}.tar.gz"

    try:
        create_backup_tarball(data_dir, archive_path, BACKUP_ARCHIVE_PATHS)
        if not archive_path.exists() or archive_path.stat().st_size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="没有可备份的文件",
            )
        archive_size = archive_path.stat().st_size

        if do_webdav and do_s3:
            wd_proxy = _extract_webdav_proxy(cfg)
            try:
                wd_res = upload_file_to_webdav(
                    base_url=webdav_url,
                    username=webdav_user,
                    password=webdav_password,
                    remote_dir=webdav_remote,
                    local_path=archive_path,
                    proxy=wd_proxy,
                )
                s3_res = await upload_backup_to_s3(cfg, archive_path)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                ) from exc
            except Exception as exc:
                logger.exception("多落点备份上传失败")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"多落点备份上传失败: {exc}",
                ) from exc
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

            return {
                "success": True,
                "mode": "both",
                "message": "备份已成功上传至 WebDAV 及对象存储",
                "filename": archive_path.name,
                "webdav_url": wd_res.get("remote_url"),
                "s3_url": s3_res.get("url"),
                "size_bytes": wd_res.get("size_bytes") or s3_res.get("size") or archive_size,
            }

        if do_webdav:
            try:
                wd_proxy = _extract_webdav_proxy(cfg)
                result = upload_file_to_webdav(
                    base_url=webdav_url,
                    username=webdav_user,
                    password=webdav_password,
                    remote_dir=webdav_remote,
                    local_path=archive_path,
                    proxy=wd_proxy,
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
                "mode": "webdav",
                "message": "备份已上传到 WebDAV",
                "remote_url": result.get("remote_url"),
                "filename": result.get("filename"),
                "size_bytes": result.get("size_bytes"),
            }

        if do_s3:
            try:
                result = await upload_backup_to_s3(cfg, archive_path)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                ) from exc
            except Exception as exc:
                logger.exception("对象存储上传失败")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"对象存储上传失败: {exc}",
                ) from exc
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            return {
                "success": True,
                "mode": "s3",
                "message": "备份已上传到对象存储",
                "filename": Path(str(result.get("key") or "")).name,
                "size_bytes": result.get("size"),
                "remote_url": result.get("url"),
            }

        # 未配置 WebDAV / 对象存储：回退为本地下载
        def _cleanup() -> None:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        return FileResponse(
            path=str(archive_path),
            filename=archive_path.name,
            media_type="application/gzip",
            headers={"Content-Disposition": f'attachment; filename="{archive_path.name}"'},
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
    from backend.services.webdav_client import check_webdav_connection

    cfg = get_config_service().get_global_settings()
    try:
        wd_proxy = _extract_webdav_proxy(cfg)
        result = check_webdav_connection(
            base_url=str(cfg.get("webdav_url") or ""),
            username=str(cfg.get("webdav_username") or ""),
            password=str(cfg.get("webdav_password") or ""),
            remote_dir=str(cfg.get("webdav_remote_dir") or "tg-signpulse-backups"),
            proxy=wd_proxy,
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
        wd_proxy = _extract_webdav_proxy(cfg)
        result = list_webdav_files(
            base_url=url,
            username=str(cfg.get("webdav_username") or ""),
            password=str(cfg.get("webdav_password") or ""),
            remote_dir=str(cfg.get("webdav_remote_dir") or "tg-signpulse-backups"),
            name_suffix=".tar.gz",
            limit=20,
            proxy=wd_proxy,
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
        wd_proxy = _extract_webdav_proxy(cfg)
        stream = iter_webdav_file(
            base_url=url,
            username=str(cfg.get("webdav_username") or ""),
            password=str(cfg.get("webdav_password") or ""),
            remote_dir=str(cfg.get("webdav_remote_dir") or "tg-signpulse-backups"),
            filename=safe_name,
            proxy=wd_proxy,
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


class S3TestResponse(BaseModel):
    success: bool
    message: str
    status_code: Optional[int] = None


@router.post("/backup/s3/test", response_model=S3TestResponse)
async def test_s3_backup(current_user: User = Depends(get_current_user)):
    """测试已保存的对象存储（S3/R2/MinIO）配置连通性。"""
    from backend.services.config import get_config_service
    from backend.services.s3_backup import check_s3_connection, s3_enabled

    cfg = get_config_service().get_global_settings()
    if not s3_enabled(cfg):
        return S3TestResponse(success=False, message="对象存储未配置或必填项不完整")
    result = await check_s3_connection(cfg)
    return S3TestResponse(**result)


class S3FileEntry(BaseModel):
    name: str
    href: str = ""
    size_bytes: Optional[int] = None
    mtime: Optional[str] = None


class S3ListResponse(BaseModel):
    success: bool
    files: List[S3FileEntry] = Field(default_factory=list)
    message: str = ""
    status_code: Optional[int] = None


@router.get("/backup/s3/files", response_model=S3ListResponse)
async def list_s3_backup_files(current_user: User = Depends(get_current_user)):
    """列出已保存对象存储配置下 prefix 中的 .tar.gz 备份。"""
    from backend.services.config import get_config_service
    from backend.services.s3_backup import list_s3_files, s3_enabled

    cfg = get_config_service().get_global_settings()
    if not s3_enabled(cfg):
        return S3ListResponse(success=False, message="对象存储未配置或必填项不完整")
    result = await list_s3_files(cfg, name_suffix=".tar.gz", limit=20)
    if not result.get("success"):
        return S3ListResponse(success=False, message=str(result.get("message") or "列表失败"))
    files = [S3FileEntry(**f) for f in (result.get("files") or [])]
    return S3ListResponse(
        success=True,
        files=files,
        message="对象存储列表获取成功" if files else "远端暂无备份",
    )


@router.get("/backup/s3/download")
async def download_s3_backup_file(
    name: str,
    current_user: User = Depends(get_current_user),
):
    """
    从已配置对象存储下载指定备份包到浏览器。

    仅允许安全的 .tar.gz 文件名；恢复请离线覆盖 data/，不在面板内解压。
    """
    from fastapi.responses import StreamingResponse

    from backend.services.config import get_config_service
    from backend.services.s3_backup import s3_enabled, stream_s3_file
    from backend.services.webdav_client import validate_backup_filename

    try:
        safe_name = validate_backup_filename(name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    cfg = get_config_service().get_global_settings()
    if not s3_enabled(cfg):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="对象存储未配置或必填项不完整",
        )
    try:
        stream = await stream_s3_file(cfg, safe_name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("对象存储下载失败")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"对象存储下载失败: {exc}",
        ) from exc

    try:
        first_chunk = await anext(stream)
    except StopAsyncIteration as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="对象存储下载结果为空",
        ) from exc
    except Exception as exc:
        logger.exception("对象存储读取失败")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"对象存储读取失败: {exc}",
        ) from exc

    async def _body():
        yield first_chunk
        async for chunk in stream:
            yield chunk

    return StreamingResponse(
        _body(),
        media_type="application/gzip",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
        },
    )


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
    scheduler_role: str = "replica"
    legacy_tasks_writable: bool = False
    legacy_tasks_removed: bool = True
    database_is_sqlite: bool = True
    monitor_shard: str = ""
    monitor_allowlist: str = ""
    uptime_seconds: int = 0


@router.get("/runtime-status", response_model=RuntimeStatusResponse)
def runtime_status(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """面板/运维用运行时摘要（需登录）。"""
    settings = get_settings()
    lock_held = has_scheduler_lock()
    start_time = getattr(request.app.state, "start_time", None)
    uptime_seconds = int(time.time() - start_time) if start_time else 0

    return RuntimeStatusResponse(
        ready=bool(getattr(request.app.state, "ready", False)),
        scheduler_lock_held=lock_held,
        scheduler_role="primary" if lock_held else "replica",
        legacy_tasks_writable=False,
        legacy_tasks_removed=True,
        database_is_sqlite=settings.is_sqlite,
        monitor_shard=os.getenv("APP_MONITOR_SHARD", "") or "",
        monitor_allowlist=os.getenv("APP_MONITOR_ACCOUNT_ALLOWLIST", "") or "",
        uptime_seconds=uptime_seconds,
    )


class VersionInfoResponse(BaseModel):
    version: str
    git_sha: str = ""
    git_branch: str = ""
    build_time: str = ""
    app_name: str = ""
    os_platform: str = ""
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


class DailyTrendItem(BaseModel):
    date: str
    total: int
    success: int
    failed: int
    success_rate: float


class TrendsResponse(BaseModel):
    days: int
    total_runs: int
    total_success: int
    total_failed: int
    overall_success_rate: float
    trends: List[DailyTrendItem]
    categories: Dict[str, int]


@router.get("/trends", response_model=TrendsResponse)
def get_trends(
    days: int = 7,
    current_user: User = Depends(get_current_user),
):
    """获取最近 N 天的签到历史趋势与成功率指标。"""
    from backend.services.sign_tasks import SignTaskService

    service = SignTaskService()
    return service.get_history_trends(days=days)

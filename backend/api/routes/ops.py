"""
运维辅助 API：调度预览、备份状态、进程指标。
"""

from __future__ import annotations

import logging
import os
import shutil
import tarfile
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
    from backend.utils.storage import is_writable_dir

    settings = get_settings()
    data_dir = Path(settings.resolve_base_dir())
    recommended = [
        "db.sqlite",
        "sessions",
        ".signer",
        ".global_settings.json",
        ".openai_config.json",
        ".telegram_api.json",
    ]
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
    # 加上其余顶层占用粗算
    try:
        total = max(total, _dir_size(data_dir))
    except Exception as exc:
        logger.debug("计算数据目录大小失败: %s", exc)

    return BackupStatusResponse(
        data_dir=str(data_dir),
        writable=is_writable_dir(data_dir),
        size_bytes=total,
        size_human=_human_size(total),
        entries=entries,
        recommended_paths=recommended,
    )


@router.post("/backup/export")
def export_backup_archive(current_user: User = Depends(get_current_user)):
    """
    打包 data 目录关键路径为 tar.gz 并下载。

    仅包含推荐备份路径；不会导出系统临时文件。
    """
    settings = get_settings()
    data_dir = Path(settings.resolve_base_dir())
    if not data_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据目录不存在",
        )

    recommended = [
        "db.sqlite",
        "db.sqlite-wal",
        "db.sqlite-shm",
        "sessions",
        ".signer",
        ".global_settings.json",
        ".openai_config.json",
        ".telegram_api.json",
        ".admin_bootstrap_password",
    ]

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    tmp_dir = Path(tempfile.mkdtemp(prefix="tg-signpulse-backup-"))
    archive_path = tmp_dir / f"tg-signpulse-backup-{ts}.tar.gz"

    try:
        with tarfile.open(archive_path, "w:gz") as tar:
            for rel in recommended:
                src = data_dir / rel
                if not src.exists():
                    continue
                tar.add(src, arcname=rel)
        if archive_path.stat().st_size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="没有可备份的文件",
            )
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
    except Exception as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        logger.exception("导出备份失败")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"导出备份失败: {exc}",
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

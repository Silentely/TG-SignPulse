"""数据目录备份打包与自动备份清理。"""

from __future__ import annotations

import logging
import os
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple

logger = logging.getLogger("backend.backup_archive")

DEFAULT_BACKUP_PATHS: Tuple[str, ...] = (
    "db.sqlite",
    "db.sqlite-wal",
    "db.sqlite-shm",
    "sessions",
    ".signer",
    ".global_settings.json",
    ".openai_config.json",
    ".telegram_api.json",
)


def create_backup_tarball(
    data_dir: Path,
    dest: Path,
    paths: Sequence[str] = DEFAULT_BACKUP_PATHS,
) -> Path:
    """将 data_dir 下推荐路径打包为 tar.gz。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dest, "w:gz") as tar:
        for rel in paths:
            src = data_dir / rel
            if not src.exists():
                continue
            tar.add(src, arcname=rel)
    return dest


def prune_backups(backup_dir: Path, keep: int) -> int:
    """保留最近 keep 份 auto-*.tar.gz，删除更旧文件。返回删除数量。"""
    keep = max(0, int(keep))
    if not backup_dir.exists():
        return 0
    files = sorted(
        backup_dir.glob("auto-*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed = 0
    for f in files[keep:]:
        try:
            f.unlink(missing_ok=True)
            removed += 1
        except OSError as exc:
            logger.warning("删除旧备份失败 %s: %s", f, exc)
    return removed


def run_auto_backup(
    data_dir: Path,
    *,
    keep: int = 3,
    paths: Optional[Iterable[str]] = None,
) -> dict:
    """执行一次自动备份并清理旧文件。"""
    backup_dir = data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = backup_dir / f"auto-{ts}.tar.gz"
    path_tuple = tuple(paths) if paths is not None else DEFAULT_BACKUP_PATHS
    create_backup_tarball(data_dir, dest, path_tuple)
    size = dest.stat().st_size if dest.exists() else 0
    removed = prune_backups(backup_dir, keep)
    return {
        "success": True,
        "path": str(dest),
        "size_bytes": size,
        "pruned": removed,
    }


def should_run_auto_backup(settings: dict) -> bool:
    return bool(settings.get("auto_backup_enabled"))


def auto_backup_interval_hours(settings: dict) -> int:
    raw = settings.get("auto_backup_interval_hours")
    try:
        return max(1, min(int(raw if raw is not None else 24), 168))
    except (TypeError, ValueError):
        return 24


def auto_backup_keep(settings: dict) -> int:
    raw = settings.get("auto_backup_keep")
    try:
        return max(1, min(int(raw if raw is not None else 3), 30))
    except (TypeError, ValueError):
        return 3

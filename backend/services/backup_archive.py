"""数据目录备份打包与自动备份清理。"""

from __future__ import annotations

import logging
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple

logger = logging.getLogger("backend.backup_archive")

DEFAULT_BACKUP_PATHS: Tuple[str, ...] = (
    "db.sqlite",
    "db.sqlite-wal",
    "db.sqlite-shm",
    "plugin_storage.db",
    "plugin_storage.db-wal",
    "plugin_storage.db-shm",
    "plugins",
    "sessions",
    ".signer",
    ".global_settings.json",
    ".openai_config.json",
    ".telegram_api.json",
)


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def create_backup_tarball(
    data_dir: Path,
    dest: Path,
    paths: Sequence[str] = DEFAULT_BACKUP_PATHS,
) -> Path:
    """将 data_dir 下推荐路径打包为 tar.gz。

    仅添加 data_dir 内真实存在的路径；拒绝指向目录外的符号链接逃逸。
    若无任何可打包内容则抛出 ValueError。
    """
    data_dir = data_dir.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    added = 0
    with tarfile.open(dest, "w:gz") as tar:
        for rel in paths:
            # 拒绝绝对路径与父目录穿越
            rel_p = Path(rel) if rel else None
            if not rel or not rel_p or rel_p.is_absolute() or rel.startswith(("/", chr(92))) or ":" in rel or chr(0) in rel or ".." in rel_p.parts:
                logger.warning("跳过非法备份路径: %s", rel)
                continue
            src = (data_dir / rel).resolve()
            try:
                src.relative_to(data_dir)
            except ValueError:
                logger.warning("跳过 data_dir 外路径: %s", rel)
                continue
            if not src.exists():
                continue
            tar.add(src, arcname=rel)
            added += 1
    if added == 0:
        try:
            dest.unlink(missing_ok=True)
        except OSError as exc:
            logger.debug("清理空备份文件失败: %s (%s)", dest, exc)
        raise ValueError("没有可备份的文件")
    return dest


def prune_backups(backup_dir: Path, keep: int) -> int:
    """保留最近 keep 份 auto-*.tar.gz，删除更旧文件。返回删除数量。"""
    try:
        keep = max(0, int(keep))
    except (TypeError, ValueError):
        keep = 3
    if not backup_dir.exists():
        return 0
    files = sorted(
        backup_dir.glob("auto-*.tar.gz"),
        key=_safe_mtime,
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
    webdav_settings: Optional[dict] = None,
    s3_settings: Optional[dict] = None,
) -> dict:
    """执行一次自动备份；远端（WebDAV / 对象存储）上传成功后删除本地副本以节省磁盘。

    WebDAV 优先：二者都配置时走 WebDAV，对象存储仅在未配置 WebDAV 时生效。
    """
    backup_dir = data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    # 备份文件名用 UTC，与历史记录/命中导出的时间口径一致，避免跨时区部署错位
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = backup_dir / f"auto-{ts}.tar.gz"
    path_tuple = tuple(paths) if paths is not None else DEFAULT_BACKUP_PATHS
    try:
        create_backup_tarball(data_dir, dest, path_tuple)
    except ValueError as exc:
        logger.warning("自动备份跳过: %s", exc)
        return {
            "success": False,
            "path": "",
            "size_bytes": 0,
            "pruned": 0,
            "remote_pruned": 0,
            "remote_prune": None,
            "local_removed": False,
            "error": str(exc),
            "webdav": None,
            "s3": None,
        }
    try:
        size = dest.stat().st_size if dest.exists() else 0
    except OSError:
        size = 0
    webdav_result = None
    s3_result = None
    remote_prune = None
    local_removed = False
    path_out = str(dest)
    wd = webdav_settings or {}
    s3 = s3_settings or {}
    use_s3 = not (wd.get("webdav_url") or "").strip() and _s3_ready(s3)
    if (wd.get("webdav_url") or "").strip():
        wd_proxy = str(wd.get("webdav_proxy") or wd.get("proxy") or "").strip() or None
        try:
            from backend.services.webdav_client import upload_file_to_webdav

            webdav_result = upload_file_to_webdav(
                base_url=str(wd.get("webdav_url") or ""),
                username=str(wd.get("webdav_username") or ""),
                password=str(wd.get("webdav_password") or ""),
                remote_dir=str(wd.get("webdav_remote_dir") or "tg-signpulse-backups"),
                local_path=dest,
                proxy=wd_proxy,
            )
        except Exception as exc:
            logger.warning("自动备份 WebDAV 上传失败: %s", exc)
            webdav_result = {"success": False, "error": str(exc)}

        # 远端已有副本则删本地，失败则保留便于补传
        if webdav_result and webdav_result.get("success"):
            try:
                dest.unlink(missing_ok=True)
                local_removed = True
                path_out = str(webdav_result.get("remote_url") or "")
            except OSError as exc:
                logger.warning("删除本地自动备份失败 %s: %s", dest, exc)

            # 远端按 keep 轮转清理旧包
            try:
                from backend.services.webdav_client import prune_webdav_backups

                remote_prune = prune_webdav_backups(
                    base_url=str(wd.get("webdav_url") or ""),
                    username=str(wd.get("webdav_username") or ""),
                    password=str(wd.get("webdav_password") or ""),
                    remote_dir=str(
                        wd.get("webdav_remote_dir") or "tg-signpulse-backups"
                    ),
                    keep=keep,
                    proxy=wd_proxy,
                )
            except Exception as exc:
                logger.warning("远端备份清理失败: %s", exc)
                remote_prune = {"success": False, "removed": 0, "error": str(exc)}
    elif use_s3:
        try:
            s3_result = _run_coro_blocking(_upload_backup_to_s3(s3, dest))
        except Exception as exc:
            logger.warning("自动备份对象存储上传失败: %s", exc)
            s3_result = {"success": False, "error": str(exc)}

        # 远端已有副本则删本地，失败则保留便于补传
        if s3_result and s3_result.get("success"):
            try:
                dest.unlink(missing_ok=True)
                local_removed = True
                path_out = str(s3_result.get("url") or "")
            except OSError as exc:
                logger.warning("删除本地自动备份失败 %s: %s", dest, exc)

            # 远端按 keep 轮转清理旧包
            try:
                from backend.services.s3_backup import prune_s3_backups

                remote_prune = _run_coro_blocking(prune_s3_backups(s3, keep=keep))
            except Exception as exc:
                logger.warning("对象存储远端备份清理失败: %s", exc)
                remote_prune = {"success": False, "removed": 0, "error": str(exc)}

    removed = prune_backups(backup_dir, keep)
    return {
        "success": True,
        "path": path_out,
        "size_bytes": size,
        "pruned": removed,
        "remote_pruned": (remote_prune or {}).get("removed", 0),
        "remote_prune": remote_prune,
        "local_removed": local_removed,
        "webdav": webdav_result,
        "s3": s3_result,
    }


def _s3_ready(s3: dict) -> bool:
    """对象存储是否已配置且启用（必填项齐全）。"""
    if not s3.get("s3_enabled"):
        return False
    try:
        from backend.services.s3_backup import validate_s3_settings

        validate_s3_settings(
            endpoint_url=str(s3.get("s3_endpoint_url") or ""),
            bucket=str(s3.get("s3_bucket") or ""),
            access_key=str(s3.get("s3_access_key") or ""),
            secret_key=str(s3.get("s3_secret_key") or ""),
        )
    except ValueError:
        return False
    return True


def _run_coro_blocking(coro):
    """在同步函数内执行异步协程。

    run_auto_backup 由调度器经 asyncio.to_thread 放进工作线程执行（打包耗时不能
    冻结事件循环），而对象存储客户端是异步的。工作线程内没有运行中的事件循环，
    因此这里新建一个专用 loop 跑完即关，避免影响主循环。
    """
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    # 已被事件循环调用：此时阻塞等待会冻结主循环，直接报错让调用方改为 await
    try:
        coro.close()
    except Exception:
        pass
    raise RuntimeError("run_auto_backup 不能在运行中的事件循环内直接调用")


async def _upload_backup_to_s3(s3: dict, dest: Path) -> dict:
    from backend.services.s3_backup import upload_backup_to_s3

    return await upload_backup_to_s3(s3, dest)


def should_run_auto_backup(settings: Optional[dict]) -> bool:
    if not isinstance(settings, dict):
        return False
    return bool(settings.get("auto_backup_enabled"))


def auto_backup_interval_hours(settings: Optional[dict]) -> int:
    if not isinstance(settings, dict):
        return 24
    raw = settings.get("auto_backup_interval_hours")
    try:
        return max(1, min(int(raw if raw is not None else 24), 168))
    except (TypeError, ValueError):
        return 24


def auto_backup_keep(settings: Optional[dict]) -> int:
    """自动备份保留份数，范围与设置层钳制口径一致（1–30，默认 3）。

    本地与远端（WebDAV / 对象存储）共用该值做轮转，避免两侧保留策略不一致。
    """
    if not isinstance(settings, dict):
        return 3
    raw = settings.get("auto_backup_keep")
    try:
        return max(1, min(int(raw if raw is not None else 3), 30))
    except (TypeError, ValueError):
        return 3

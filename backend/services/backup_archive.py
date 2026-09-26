"""数据目录备份打包与自动备份清理。"""

from __future__ import annotations

import contextlib
import logging
import secrets
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
    temp_dest = dest.with_name(f"{dest.name}.tmp.{secrets.token_hex(4)}")
    added = 0
    try:
        with tarfile.open(temp_dest, "w:gz") as tar:
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
            with contextlib.suppress(OSError):
                temp_dest.unlink(missing_ok=True)
            raise ValueError("没有可备份的文件")
        temp_dest.replace(dest)
        return dest
    except Exception:
        with contextlib.suppress(OSError):
            temp_dest.unlink(missing_ok=True)
        raise


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
    backup_target: str = "auto",
) -> dict:
    """执行一次自动备份；远端（WebDAV / 对象存储）上传成功后删除本地副本以节省磁盘。

    支持 backup_target 显式指定：auto（WebDAV优先）、webdav、s3、both（双备份）。
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
    wd_ready = bool((wd.get("webdav_url") or "").strip())
    s3_is_ready = _s3_ready(s3)

    target_mode = (backup_target or "auto").strip().lower()
    if target_mode not in {"auto", "webdav", "s3", "both"}:
        target_mode = "auto"

    do_webdav = False
    do_s3 = False
    if target_mode == "both":
        do_webdav = wd_ready
        do_s3 = s3_is_ready
    elif target_mode == "webdav":
        do_webdav = wd_ready
    elif target_mode == "s3":
        do_s3 = s3_is_ready
    else:  # auto
        if wd_ready:
            do_webdav = True
        elif s3_is_ready:
            do_s3 = True

    # 显式策略下若目标未就绪，记录 attempted 失败避免调度器静默漏报
    if target_mode in {"both", "webdav"} and not wd_ready:
        webdav_result = {"success": False, "attempted": True, "error": "WebDAV 服务地址未配置"}
    elif do_webdav:
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
            webdav_result["attempted"] = True
        except Exception as exc:
            logger.warning("自动备份 WebDAV 上传失败: %s", exc)
            webdav_result = {"success": False, "attempted": True, "error": str(exc)}

        if webdav_result.get("success"):
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
                logger.warning("WebDAV 远端备份清理失败: %s", exc)
                remote_prune = {"success": False, "removed": 0, "error": str(exc)}

    if target_mode in {"both", "s3"} and not s3_is_ready:
        s3_result = {"success": False, "attempted": True, "error": "对象存储未启用或凭据未配置完整"}
    elif do_s3:
        try:
            s3_result = _run_coro_blocking(_upload_backup_to_s3(s3, dest))
            if s3_result is None:
                s3_result = {"success": True}
            s3_result["attempted"] = True
        except Exception as exc:
            logger.warning("自动备份对象存储上传失败: %s", exc)
            s3_result = {"success": False, "attempted": True, "error": str(exc)}

        if s3_result.get("success"):
            try:
                from backend.services.s3_backup import prune_s3_backups

                s3_prune = _run_coro_blocking(prune_s3_backups(s3, keep=keep))
                if remote_prune is None:
                    remote_prune = s3_prune
            except Exception as exc:
                logger.warning("对象存储远端备份清理失败: %s", exc)
                if remote_prune is None:
                    remote_prune = {"success": False, "removed": 0, "error": str(exc)}

    # 远端上传成功判定：
    # 若目标为 both 且同时尝试了 WebDAV 与 S3，要求两端均成功才清理本地，任一端失败则保留本地副本容灾
    upload_succeeded = False
    if target_mode == "both":
        if do_webdav and do_s3:
            upload_succeeded = bool(
                webdav_result and webdav_result.get("success")
                and s3_result and s3_result.get("success")
            )
        elif do_webdav:
            upload_succeeded = bool(webdav_result and webdav_result.get("success"))
        elif do_s3:
            upload_succeeded = bool(s3_result and s3_result.get("success"))
    else:
        if do_webdav and webdav_result and webdav_result.get("success"):
            upload_succeeded = True
        elif do_s3 and s3_result and s3_result.get("success"):
            upload_succeeded = True

    if webdav_result and webdav_result.get("success"):
        path_out = str(webdav_result.get("remote_url") or path_out)
    if s3_result and s3_result.get("success"):
        path_out = str(s3_result.get("url") or path_out)

    if upload_succeeded:
        try:
            dest.unlink(missing_ok=True)
            local_removed = True
        except OSError as exc:
            logger.warning("删除本地自动备份失败 %s: %s", dest, exc)
    elif target_mode == "both" and (do_webdav or do_s3):
        logger.info("备份模式为 both 且远端未全量完成，保留本地副本作为容灾兜底: %s", dest)

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

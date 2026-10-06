"""数据目录备份打包与自动备份清理。"""

from __future__ import annotations

import contextlib
import io
import logging
import os
import secrets
import shutil
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
    "data_dicts",
    ".signer/keyword_monitor",
    ".signer/.device_keepalive_state.json",
)


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _normalize_member_mode(info: tarfile.TarInfo) -> tarfile.TarInfo:
    """把归档成员权限收敛为 0600（目录 0700）。

    备份内含 session、凭据与数据库，属高敏感内容；tar.add 默认沿用源文件权限，
    宽松的组/其他位会在解压后把凭据暴露给同机其他用户，故统一压低。
    """
    info.mode = 0o700 if info.isdir() else 0o600
    return info


def create_backup_tarball(
    data_dir: Path,
    dest: Path,
    paths: Sequence[str] = DEFAULT_BACKUP_PATHS,
    *,
    password: Optional[str] = None,
    encrypt: Optional[bool] = None,
) -> Path:
    """将 data_dir 下推荐路径打包为 tar.gz 或 .spbak（加密归档）。

    仅添加 data_dir 内真实存在的路径；拒绝指向目录外的符号链接逃逸。
    归档文件与备份目录权限收敛为 0600/0700，若无任何可打包内容则抛 ValueError。
    """
    data_dir = data_dir.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(dest.parent, 0o700)
    temp_dest = dest.with_name(f"{dest.name}.tmp.{secrets.token_hex(4)}")
    added = 0
    try:
        # O_EXCL + 0600：临时文件自创建起即仅属主可读，不受进程 umask 影响
        fd = os.open(temp_dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as raw:
            with tarfile.open(fileobj=raw, mode="w:gz") as tar:
                for rel in paths:
                    # 拒绝绝对路径与父目录穿越
                    rel_p = Path(rel) if rel else None
                    if (
                        not rel
                        or not rel_p
                        or rel_p.is_absolute()
                        or rel.startswith(("/", chr(92)))
                        or ":" in rel
                        or chr(0) in rel
                        or ".." in rel_p.parts
                    ):
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
                    tar.add(src, arcname=rel, filter=_normalize_member_mode)
                    added += 1
        if added == 0:
            with contextlib.suppress(OSError):
                temp_dest.unlink(missing_ok=True)
            raise ValueError("没有可备份的文件")

        should_encrypt = encrypt is True or (
            encrypt is None and (dest.name.endswith(".spbak") or password is not None)
        )
        if should_encrypt:
            from backend.services.backup_crypto import (
                MAX_ENCRYPT_INPUT_BYTES,
                encrypt_backup,
            )

            if temp_dest.stat().st_size > MAX_ENCRYPT_INPUT_BYTES:
                raise ValueError(
                    f"加密备份原始归档超过内存安全上限 ({MAX_ENCRYPT_INPUT_BYTES} 字节)"
                )
            raw_bytes = temp_dest.read_bytes()
            encrypted_bytes = encrypt_backup(raw_bytes, password=password)
            temp_dest.write_bytes(encrypted_bytes)

        os.chmod(temp_dest, 0o600)
        temp_dest.replace(dest)
        return dest
    except Exception:
        with contextlib.suppress(OSError):
            temp_dest.unlink(missing_ok=True)
        raise


def extract_backup_archive(
    archive_path: Path,
    target_dir: Path,
    *,
    password: Optional[str] = None,
    max_extract_bytes: Optional[int] = None,
) -> int:
    """解密（如为 .spbak）并安全解压备份归档到 target_dir。

    防护措施：
    - 路径遍历防护（拒绝绝对路径、.. 逃逸、符号链接外部逃逸）
    - 解压炸弹防护（累计解压字节上限 max_extract_bytes）
    - 权限收敛（目录 0700，文件 0600）
    返回成功解压的文件数量。
    """
    from backend.services.backup_crypto import (
        MAGIC,
        MAX_EXTRACT_BYTES,
        decrypt_backup,
    )

    limit = max_extract_bytes if max_extract_bytes is not None else MAX_EXTRACT_BYTES
    archive_path = Path(archive_path)
    if not archive_path.exists() or not archive_path.is_file():
        raise ValueError(f"备份文件不存在: {archive_path}")

    target_dir = Path(target_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(target_dir, 0o700)

    raw = archive_path.read_bytes()
    if raw.startswith(MAGIC) or archive_path.name.endswith(".spbak"):
        tar_bytes = decrypt_backup(raw, password=password)
    else:
        tar_bytes = raw

    extracted_count = 0
    total_bytes = 0
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:*") as tar:
        for member in tar.getmembers():
            name = member.name
            if not name or name.startswith(("/", "\\")) or ":" in name or "\0" in name:
                logger.warning("跳过非法归档成员: %s", name)
                continue
            dest_file = (target_dir / name).resolve()
            try:
                dest_file.relative_to(target_dir)
            except ValueError:
                logger.warning("跳过越界归档成员: %s", name)
                continue

            if member.issym() or member.islnk():
                logger.warning("跳过符号链接成员: %s", name)
                continue

            if member.isreg():
                total_bytes += member.size
                if total_bytes > limit:
                    raise ValueError(f"解压数据超过上限 ({limit} 字节)，疑似解压炸弹")

            if member.isdir():
                dest_file.mkdir(parents=True, exist_ok=True)
                with contextlib.suppress(OSError):
                    os.chmod(dest_file, 0o700)
            else:
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                with contextlib.suppress(OSError):
                    os.chmod(dest_file, 0o700)
                extracted_f = tar.extractfile(member)
                if extracted_f is not None:
                    fd = os.open(
                        dest_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
                    )
                    with os.fdopen(fd, "wb") as out:
                        shutil.copyfileobj(extracted_f, out)
                    with contextlib.suppress(OSError):
                        os.chmod(dest_file, 0o600)
                    extracted_count += 1

    return extracted_count


def prune_backups(backup_dir: Path, keep: int) -> int:
    """保留最近 keep 份备份，删除更旧文件。返回删除数量。"""
    try:
        keep = max(0, int(keep))
    except (TypeError, ValueError):
        keep = 3
    if not backup_dir.exists():
        return 0
    files = sorted(
        [
            f
            for f in backup_dir.glob("auto-*.*")
            if f.name.endswith((".tar.gz", ".spbak"))
        ],
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
    backup_target: str = "auto",
    encrypt: bool = False,
) -> dict:
    """执行一次自动备份；远端（WebDAV）上传成功后删除本地副本以节省磁盘。

    支持 backup_target 显式指定：auto（配置了 WebDAV 则上传，未配置则留存本地）、webdav。
    """
    backup_dir = data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    # 备份文件名用 UTC，与历史记录/命中导出的时间口径一致，避免跨时区部署错位
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    extension = "spbak" if encrypt else "tar.gz"
    dest = backup_dir / f"auto-{ts}.{extension}"
    path_tuple = tuple(paths) if paths is not None else DEFAULT_BACKUP_PATHS
    try:
        if encrypt:
            create_backup_tarball(data_dir, dest, path_tuple, encrypt=True)
        else:
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
        }
    try:
        size = dest.stat().st_size if dest.exists() else 0
    except OSError:
        size = 0
    webdav_result = None
    remote_prune = None
    local_removed = False
    path_out = str(dest)
    wd = webdav_settings or {}
    wd_ready = bool((wd.get("webdav_url") or "").strip())

    target_mode = (backup_target or "auto").strip().lower()
    if target_mode not in {"auto", "webdav"}:
        target_mode = "auto"

    do_webdav = wd_ready if target_mode == "auto" else (target_mode == "webdav")

    if target_mode == "webdav" and not wd_ready:
        webdav_result = {
            "success": False,
            "attempted": True,
            "error": "WebDAV 服务地址未配置",
        }
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

    upload_succeeded = bool(
        do_webdav and webdav_result and webdav_result.get("success")
    )

    if webdav_result and webdav_result.get("success"):
        path_out = str(webdav_result.get("remote_url") or path_out)

    if upload_succeeded:
        try:
            dest.unlink(missing_ok=True)
            local_removed = True
        except OSError as exc:
            logger.warning("删除本地自动备份失败 %s: %s", dest, exc)

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
    }


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

    本地与远端（WebDAV）共用该值做轮转，避免两侧保留策略不一致。
    """
    if not isinstance(settings, dict):
        return 3
    raw = settings.get("auto_backup_keep")
    try:
        return max(1, min(int(raw if raw is not None else 3), 30))
    except (TypeError, ValueError):
        return 3

"""账号/聊天头像本地缓存共享组件。

账号头像与 chat 头像两条路由共用的下载-缓存-无头像标记逻辑：
- 无头像标记在有效期内直接判定无头像（避免重复下载）；过期标记自动删除
- 新鲜缓存命中直接返回；下载成功后写缓存并清除无头像标记
- 下载明确返回空才允许调用方写无头像标记；瞬时异常不污染缓存
"""
from __future__ import annotations

import contextlib
import os
import tempfile
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional

# 头像本地缓存有效期：7 天（秒）
AVATAR_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
# 临时残存文件清理阈值：1 小时（秒）
_TMP_FILE_CLEANUP_TTL_SECONDS = 3600

# 下载回调：返回头像字节；返回 None 表示明确无头像；抛异常表示瞬时故障
DownloadFn = Callable[[], Awaitable[Optional[bytes]]]


def marker_hits_no_avatar(
    no_avatar_marker: Path, ttl: int = AVATAR_CACHE_TTL_SECONDS
) -> bool:
    """无头像标记在有效期内返回 True（调用方直接判定无头像）；过期标记删除后返回 False。"""
    try:
        if not no_avatar_marker.exists():
            return False
        if time.time() - no_avatar_marker.stat().st_mtime < ttl:
            return True
        no_avatar_marker.unlink(missing_ok=True)
    except OSError:
        # 并发删除/stat 竞态：按"无标记"处理，下次请求重试
        return False
    return False


def read_cached_avatar(
    cache_file: Path, ttl: int = AVATAR_CACHE_TTL_SECONDS
) -> Optional[bytes]:
    """新鲜缓存命中返回字节；缺失或过期返回 None。"""
    try:
        if not cache_file.exists():
            return None
        if time.time() - cache_file.stat().st_mtime >= ttl:
            return None
        return cache_file.read_bytes()
    except OSError:
        return None


def read_avatar_file(cache_file: Path) -> Optional[bytes]:
    """读取磁盘上的缓存文件（不校验新鲜度），用于瞬时下载失败时的过期兜底。"""
    try:
        return cache_file.read_bytes()
    except OSError:
        return None


def mark_no_avatar(no_avatar_marker: Path) -> None:
    """写入无头像标记；是否容错由调用方按场景决定。"""
    no_avatar_marker.parent.mkdir(parents=True, exist_ok=True)
    no_avatar_marker.write_text("")


async def get_avatar_bytes(
    cache_file: Path,
    no_avatar_marker: Path,
    download_fn: DownloadFn,
) -> Optional[bytes]:
    """下载头像字节并写入本地缓存（供账号/chat 头像路由共用）。

    - 下载成功（非空）→ 写缓存、清除无头像标记，返回字节
    - 下载明确返回空 → 返回 None（是否写无头像标记由调用方按场景决定）
    - 下载/写缓存异常 → 原样上抛，避免瞬时故障污染 7 天缓存
    """
    avatar_bytes = await download_fn()
    if avatar_bytes:
        # 先写临时文件再 rename，避免并发读/写缓存时读到半截文件
        tmp_name: str | None = None
        replaced = False
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=".avatar_", suffix=".tmp", dir=str(cache_file.parent)
            )
            with os.fdopen(fd, "wb") as tmp:
                tmp.write(avatar_bytes)
            os.replace(tmp_name, cache_file)
            replaced = True
        finally:
            if not replaced and tmp_name is not None:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_name)
        with contextlib.suppress(OSError):
            no_avatar_marker.unlink(missing_ok=True)
    return avatar_bytes


def cleanup_avatar_cache(cache_dir: Path, ttl: int = AVATAR_CACHE_TTL_SECONDS) -> int:
    """清理过期头像缓存文件与无头像标记，返回清理数量。
    try:
        ttl = max(60, int(ttl or AVATAR_CACHE_TTL_SECONDS))
    except (TypeError, ValueError):
        ttl = AVATAR_CACHE_TTL_SECONDS

    7 天 TTL 在读路径校验，但磁盘上的过期文件不会自动消失；
    长期运行（大量会话/删除的账号）会累积陈旧文件。
    遍历目录删除超过 TTL 的文件；单文件失败跳过，不影响其余清理。
    """
    removed = 0
    try:
        entries = list(cache_dir.iterdir())
    except OSError:
        return 0
    now = time.time()
    for entry in entries:
        try:
            if not entry.is_file():
                continue
            name = entry.name
            # 针对中断遗留的 .tmp 文件使用更短的 1 小时过期阈值
            file_ttl = _TMP_FILE_CLEANUP_TTL_SECONDS if name.startswith(".avatar_") and name.endswith(".tmp") else ttl
            if now - entry.stat().st_mtime >= file_ttl:
                entry.unlink(missing_ok=True)
                removed += 1
        except OSError:
            # 并发删除/stat 竞态或权限问题：跳过该文件，不影响其余清理
            continue
    return removed

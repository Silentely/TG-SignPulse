"""账号/聊天头像本地缓存共享组件。

账号头像与 chat 头像两条路由共用的下载-缓存-无头像标记逻辑：
- 无头像标记在有效期内直接判定无头像（避免重复下载）；过期标记自动删除
- 新鲜缓存命中直接返回；下载成功后写缓存并清除无头像标记
- 下载明确返回空才允许调用方写无头像标记；瞬时异常不污染缓存
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Awaitable, Callable, Optional

# 头像本地缓存有效期：7 天（秒）
AVATAR_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

# 下载回调：返回头像字节；返回 None 表示明确无头像；抛异常表示瞬时故障
DownloadFn = Callable[[], Awaitable[Optional[bytes]]]


def marker_hits_no_avatar(
    no_avatar_marker: Path, ttl: int = AVATAR_CACHE_TTL_SECONDS
) -> bool:
    """无头像标记在有效期内返回 True（调用方直接判定无头像）；过期标记删除后返回 False。"""
    if not no_avatar_marker.exists():
        return False
    if time.time() - no_avatar_marker.stat().st_mtime < ttl:
        return True
    no_avatar_marker.unlink(missing_ok=True)
    return False


def read_cached_avatar(
    cache_file: Path, ttl: int = AVATAR_CACHE_TTL_SECONDS
) -> Optional[bytes]:
    """新鲜缓存命中返回字节；缺失或过期返回 None。"""
    if not cache_file.exists():
        return None
    if time.time() - cache_file.stat().st_mtime >= ttl:
        return None
    try:
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
        cache_file.write_bytes(avatar_bytes)
        no_avatar_marker.unlink(missing_ok=True)
    return avatar_bytes

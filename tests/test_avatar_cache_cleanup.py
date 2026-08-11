"""头像缓存清理回归：过期文件删除、新鲜文件保留、缺失目录容错。"""

from __future__ import annotations

import os
import time
from pathlib import Path

from backend.services import avatar_cache


def _touch(path: Path, age_seconds: float) -> None:
    path.write_bytes(b"x")
    old = time.time() - age_seconds
    os.utime(path, (old, old))


def test_cleanup_removes_expired_keeps_fresh(tmp_path: Path):
    cache_dir = tmp_path / "avatars"
    cache_dir.mkdir()
    _touch(cache_dir / "chat_1.jpg", avatar_cache.AVATAR_CACHE_TTL_SECONDS + 10)
    _touch(cache_dir / "chat_1.no_avatar", avatar_cache.AVATAR_CACHE_TTL_SECONDS + 5)
    _touch(cache_dir / "chat_2.jpg", 3600)  # 1 小时前，新鲜
    _touch(cache_dir / "chat_2.no_avatar", 60)

    removed = avatar_cache.cleanup_avatar_cache(cache_dir)
    assert removed == 2
    assert not (cache_dir / "chat_1.jpg").exists()
    assert not (cache_dir / "chat_1.no_avatar").exists()
    assert (cache_dir / "chat_2.jpg").exists()
    assert (cache_dir / "chat_2.no_avatar").exists()


def test_cleanup_missing_dir_returns_zero(tmp_path: Path):
    assert avatar_cache.cleanup_avatar_cache(tmp_path / "nope") == 0


def test_cleanup_skips_directories(tmp_path: Path):
    cache_dir = tmp_path / "avatars"
    (cache_dir / "sub").mkdir(parents=True)
    _touch(cache_dir / "sub" / "chat_9.jpg", avatar_cache.AVATAR_CACHE_TTL_SECONDS + 99)
    removed = avatar_cache.cleanup_avatar_cache(cache_dir)
    assert removed == 0
    assert (cache_dir / "sub" / "chat_9.jpg").exists()


def test_cleanup_unreadable_file_does_not_abort(tmp_path: Path, monkeypatch):
    """单个文件 stat/unlink 失败不中断其余清理。"""
    cache_dir = tmp_path / "avatars"
    cache_dir.mkdir()
    _touch(cache_dir / "expired.jpg", avatar_cache.AVATAR_CACHE_TTL_SECONDS + 10)
    _touch(cache_dir / "fresh.jpg", 100)

    original_stat = Path.stat

    def _flaky_stat(self, *args, **kwargs):
        if self.name == "expired.jpg":
            raise OSError("permission denied")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _flaky_stat)
    removed = avatar_cache.cleanup_avatar_cache(cache_dir)
    assert removed == 0  # expired 因 stat 失败跳过、fresh 未过期，均不删除
    # 用 os.path.exists 断言（Path.exists 内部也会走被 patch 的 stat）
    import os as _os

    assert _os.path.exists(cache_dir / "expired.jpg")
    assert _os.path.exists(cache_dir / "fresh.jpg")

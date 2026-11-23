"""backend/services/avatar_cache.py 单元测试。

覆盖：无头像标记 TTL 命中/过期、缓存新鲜度判定、下载写缓存与清除标记、
下载空结果不写缓存、以及并发删除竞态下不抛异常。
"""

from __future__ import annotations

import os
import time

import pytest

from backend.services import avatar_cache


def test_marker_hits_within_ttl(tmp_path):
    marker = tmp_path / "a.no_avatar"
    marker.write_text("")
    assert avatar_cache.marker_hits_no_avatar(marker) is True


def test_marker_expired_is_removed(tmp_path):
    marker = tmp_path / "a.no_avatar"
    marker.write_text("")
    old = time.time() - avatar_cache.NO_AVATAR_CACHE_TTL_SECONDS - 10
    os.utime(marker, (old, old))
    assert avatar_cache.marker_hits_no_avatar(marker) is False
    assert not marker.exists()


def test_marker_missing_returns_false(tmp_path):
    assert avatar_cache.marker_hits_no_avatar(tmp_path / "nope") is False


def test_marker_race_concurrent_unlink_no_raise(tmp_path):
    """标记在 stat 与 unlink 之间被并发删除时按"无标记"处理。"""
    marker = tmp_path / "race.no_avatar"
    marker.write_text("")
    # 文件已被并发进程删除后调用：内部 stat/unlink 抛 FileNotFoundError，
    # 应被吞掉返回 False 而非冒泡成 500
    marker.unlink()
    assert avatar_cache.marker_hits_no_avatar(marker) is False


def test_read_cached_avatar_fresh_and_expired(tmp_path):
    cache = tmp_path / "a.jpg"
    cache.write_bytes(b"img")
    assert avatar_cache.read_cached_avatar(cache) == b"img"

    old = time.time() - avatar_cache.AVATAR_CACHE_TTL_SECONDS - 10
    os.utime(cache, (old, old))
    assert avatar_cache.read_cached_avatar(cache) is None


@pytest.mark.asyncio
async def test_get_avatar_bytes_writes_cache_and_clears_marker(tmp_path):
    cache = tmp_path / "a.jpg"
    marker = tmp_path / "a.no_avatar"
    marker.write_text("")

    async def download():
        return b"img"

    result = await avatar_cache.get_avatar_bytes(cache, marker, download)
    assert result == b"img"
    assert cache.read_bytes() == b"img"
    assert not marker.exists()


@pytest.mark.asyncio
async def test_get_avatar_bytes_empty_result_no_cache(tmp_path):
    cache = tmp_path / "b.jpg"
    marker = tmp_path / "b.no_avatar"

    async def download():
        return None

    result = await avatar_cache.get_avatar_bytes(cache, marker, download)
    assert result is None
    assert not cache.exists()
    assert not marker.exists()


@pytest.mark.asyncio
async def test_get_avatar_bytes_download_error_no_cache_write(tmp_path):
    cache = tmp_path / "c.jpg"
    marker = tmp_path / "c.no_avatar"

    async def boom():
        raise RuntimeError("download failed")

    with pytest.raises(RuntimeError):
        await avatar_cache.get_avatar_bytes(cache, marker, boom)
    assert not cache.exists()
    assert not marker.exists()


@pytest.mark.asyncio
async def test_get_avatar_bytes_mkstemp_failure_raises_oserror(tmp_path, monkeypatch):
    """mkstemp 本身失败时原样上抛 OSError，不得被清理分支的 NameError 掩盖。"""
    import tempfile

    cache = tmp_path / "d.jpg"
    marker = tmp_path / "d.no_avatar"

    async def download():
        return b"img"

    def bad_mkstemp(*args, **kwargs):
        raise OSError("缓存目录不可写")

    monkeypatch.setattr(tempfile, "mkstemp", bad_mkstemp)
    with pytest.raises(OSError, match="缓存目录不可写"):
        await avatar_cache.get_avatar_bytes(cache, marker, download)
    assert not cache.exists()


def test_cleanup_avatar_cache_removes_expired_no_avatar(tmp_path):
    marker = tmp_path / "chat_123.no_avatar"
    marker.write_text("")
    old = time.time() - avatar_cache.NO_AVATAR_CACHE_TTL_SECONDS - 10
    os.utime(marker, (old, old))

    fresh_marker = tmp_path / "chat_456.no_avatar"
    fresh_marker.write_text("")

    removed = avatar_cache.cleanup_avatar_cache(tmp_path)
    assert removed == 1
    assert not marker.exists()
    assert fresh_marker.exists()


def test_lookup_chat_username(tmp_path, monkeypatch):
    import json

    from backend.services.telegram.accounts import TelegramAccountsMixin

    class FakeSettings:
        def resolve_workdir(self):
            return tmp_path

    monkeypatch.setattr("backend.core.config.get_settings", lambda: FakeSettings())

    acc_dir = tmp_path / "test_acc"
    acc_dir.mkdir()
    cache_file = acc_dir / "chats_cache.json"
    cache_file.write_text(
        json.dumps(
            [
                {
                    "id": 8300459562,
                    "title": "厂妹",
                    "username": "changmei_bot",
                    "type": "bot",
                },
                {
                    "id": 123456,
                    "title": "普通群",
                    "username": None,
                    "type": "supergroup",
                },
            ]
        ),
        encoding="utf-8",
    )

    username = TelegramAccountsMixin._lookup_chat_username(8300459562, "test_acc")
    assert username == "changmei_bot"

    # 其他账号 fallback 也能查到
    username_fallback = TelegramAccountsMixin._lookup_chat_username(
        8300459562, "other_acc"
    )
    assert username_fallback == "changmei_bot"

    # 无 username 的返回 None
    assert TelegramAccountsMixin._lookup_chat_username(123456, "test_acc") is None
    # 不存在的 id 返回 None
    assert TelegramAccountsMixin._lookup_chat_username(999999, "test_acc") is None

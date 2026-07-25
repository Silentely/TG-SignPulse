"""backend.utils.session_cache.SessionCache 单元测试"""

from __future__ import annotations

import pytest

from backend.utils.session_cache import SessionCache


@pytest.mark.asyncio
async def test_set_get_remove():
    cache = SessionCache(maxsize=5)
    assert await cache.get("a") is None
    assert await cache.set("a", {"client": 1}) is None
    assert await cache.get("a") == {"client": 1}
    assert await cache.remove("a") == {"client": 1}
    assert await cache.get("a") is None


@pytest.mark.asyncio
async def test_lru_eviction_returns_evicted():
    cache = SessionCache(maxsize=2)
    await cache.set("a", "sa")
    await cache.set("b", "sb")
    # 访问 a，使 b 成为最久未使用
    await cache.get("a")
    evicted = await cache.set("c", "sc")
    assert evicted == "sb"
    assert await cache.contains("b") is False
    assert await cache.contains("a") is True
    assert await cache.contains("c") is True


@pytest.mark.asyncio
async def test_clear_keys_size():
    cache = SessionCache(maxsize=3)
    await cache.set("x", 1)
    await cache.set("y", 2)
    assert await cache.size() == 2
    keys = await cache.keys()
    assert set(keys) == {"x", "y"}
    cleared = await cache.clear()
    assert set(cleared) == {1, 2}
    assert await cache.size() == 0


def test_invalid_maxsize():
    with pytest.raises(ValueError):
        SessionCache(maxsize=0)


def test_repr():
    cache = SessionCache(maxsize=3)
    assert "SessionCache" in repr(cache)
    assert cache.maxsize == 3


@pytest.mark.asyncio
async def test_get_missing_returns_none():
    """获取不存在的 key 应返回 None。"""
    cache = SessionCache(maxsize=3)
    assert await cache.get("missing") is None


@pytest.mark.asyncio
async def test_set_update_existing_does_not_evict():
    """更新已有 key 应刷新 LRU 顺序，不驱逐任何条目。"""
    cache = SessionCache(maxsize=2)
    await cache.set("a", "sa")
    await cache.set("b", "sb")
    evicted = await cache.set("a", "sa-new")
    assert evicted is None
    assert await cache.get("a") == "sa-new"
    assert await cache.get("b") == "sb"
    assert await cache.size() == 2


@pytest.mark.asyncio
async def test_get_refreshes_lru_order():
    """get 命中应将 key 移到末尾（最近使用），影响后续驱逐顺序。"""
    cache = SessionCache(maxsize=2)
    await cache.set("a", "sa")
    await cache.set("b", "sb")
    # 访问 a，使 b 成为最久未使用
    await cache.get("a")
    evicted = await cache.set("c", "sc")
    assert evicted == "sb"
    assert await cache.contains("a") is True
    assert await cache.contains("b") is False
    assert await cache.contains("c") is True


@pytest.mark.asyncio
async def test_remove_missing_returns_none():
    """remove 不存在的 key 应返回 None，不抛异常。"""
    cache = SessionCache(maxsize=3)
    assert await cache.remove("missing") is None


@pytest.mark.asyncio
async def test_clear_returns_all_sessions():
    """clear 应返回所有被移除的会话列表，并清空缓存。"""
    cache = SessionCache(maxsize=5)
    await cache.set("a", "sa")
    await cache.set("b", "sb")
    cleared = await cache.clear()
    assert set(cleared) == {"sa", "sb"}
    assert await cache.size() == 0
    # 再次 clear 应返回空列表
    assert await cache.clear() == []


@pytest.mark.asyncio
async def test_keys_returns_in_lru_order():
    """keys 应按 LRU 顺序返回，最久未使用在前。"""
    cache = SessionCache(maxsize=5)
    await cache.set("a", 1)
    await cache.set("b", 2)
    await cache.set("c", 3)
    # 访问 a，将 a 移到末尾
    await cache.get("a")
    keys = await cache.keys()
    assert keys == ["b", "c", "a"]

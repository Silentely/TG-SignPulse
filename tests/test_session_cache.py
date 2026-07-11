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

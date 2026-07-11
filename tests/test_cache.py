"""backend.utils.cache.TTLCache 单元测试"""

from __future__ import annotations

import time

import pytest

from backend.utils.cache import TTLCache


class TestTTLCache:
    def test_set_get(self):
        cache = TTLCache(maxsize=10, ttl=60.0)
        cache.set("k", "v")
        assert cache.get("k") == "v"

    def test_missing_returns_default(self):
        cache = TTLCache(maxsize=10, ttl=60.0)
        assert cache.get("missing") is None
        assert cache.get("missing", "fallback") == "fallback"

    def test_expire(self):
        cache = TTLCache(maxsize=10, ttl=0.05)
        cache.set("k", 1)
        time.sleep(0.08)
        assert cache.get("k") is None

    def test_lru_eviction(self):
        cache = TTLCache(maxsize=2, ttl=60.0)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        assert cache.get("a") is None
        assert cache.get("b") == 2
        assert cache.get("c") == 3

    def test_delete_and_clear(self):
        cache = TTLCache(maxsize=10, ttl=60.0)
        cache.set("a", 1)
        cache.set("b", 2)
        assert cache.delete("a") is True
        assert cache.delete("missing") is False
        assert cache.clear() == 1
        assert len(cache) == 0

    def test_contains_and_len(self):
        cache = TTLCache(maxsize=10, ttl=60.0)
        cache.set("k", True)
        assert "k" in cache
        assert "x" not in cache
        assert len(cache) == 1

    def test_get_many_set_many(self):
        cache = TTLCache(maxsize=10, ttl=60.0)
        cache.set_many({"a": 1, "b": 2})
        assert cache.get_many(["a", "b", "c"]) == {"a": 1, "b": 2}

    def test_invalid_params(self):
        with pytest.raises(ValueError):
            TTLCache(maxsize=0, ttl=1.0)
        with pytest.raises(ValueError):
            TTLCache(maxsize=1, ttl=0)

    def test_purge_expired(self):
        cache = TTLCache(maxsize=10, ttl=0.05)
        cache.set("a", 1)
        cache.set("b", 2)
        time.sleep(0.08)
        purged = cache.purge_expired()
        assert purged == 2
        assert len(cache) == 0

    def test_repr_and_props(self):
        cache = TTLCache(maxsize=8, ttl=12.5)
        assert cache.maxsize == 8
        assert cache.ttl == 12.5
        assert "TTLCache" in repr(cache)

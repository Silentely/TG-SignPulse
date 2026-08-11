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

    # ------------------------------------------------------------------
    # 边界与错误恢复补充
    # ------------------------------------------------------------------

    def test_contains_expired_returns_false_and_cleans(self):
        """__contains__ 在条目过期时应返回 False 并惰性删除。"""
        cache = TTLCache(maxsize=10, ttl=0.05)
        cache.set("k", "v")
        time.sleep(0.08)
        # 过期后 contains 应返回 False，且内部删除该条目
        assert "k" not in cache
        # 再次 contains 仍安全（已删除路径）
        assert "k" not in cache

    def test_delete_many_returns_actual_count(self):
        """delete_many 应返回实际删除数，未命中不计数。"""
        cache = TTLCache(maxsize=10, ttl=60.0)
        cache.set_many({"a": 1, "b": 2, "c": 3})
        deleted = cache.delete_many(["a", "c", "missing"])
        assert deleted == 2
        assert "a" not in cache
        assert "b" in cache
        assert "c" not in cache

    def test_purge_expired_on_empty_cache(self):
        """purge_expired 在空缓存上应安全返回 0。"""
        cache = TTLCache(maxsize=5, ttl=60.0)
        assert cache.purge_expired() == 0

    def test_purge_expired_partial(self):
        """purge_expired 仅清理过期条目，存活条目保留。"""
        cache = TTLCache(maxsize=10, ttl=0.05)
        cache.set("old1", 1)
        cache.set("old2", 2)
        time.sleep(0.08)
        # 重新写入新条目（重置 ttl）
        cache.set("new", 3)
        purged = cache.purge_expired()
        assert purged == 2
        assert cache.get("new") == 3

    def test_set_update_existing_refreshes_ttl(self):
        """set 已有 key 应更新值并刷新 TTL，不淘汰其他条目。"""
        cache = TTLCache(maxsize=2, ttl=60.0)
        cache.set("a", 1)
        cache.set("b", 2)
        # 更新 a，不应淘汰 b
        cache.set("a", 10)
        assert cache.get("a") == 10
        assert cache.get("b") == 2
        assert len(cache) == 2

    def test_get_many_with_none_value(self):
        """get_many 应能区分缓存 None 与缺失（支持缓存 None 值）。"""
        cache = TTLCache(maxsize=10, ttl=60.0)
        cache.set("present", None)
        result = cache.get_many(["present", "absent"])
        assert "present" in result
        assert result["present"] is None
        assert "absent" not in result

    def test_repr_includes_size(self):
        """repr 应包含当前条目数。"""
        cache = TTLCache(maxsize=5, ttl=30.0)
        cache.set("x", 1)
        repr_str = repr(cache)
        assert "size=1" in repr_str

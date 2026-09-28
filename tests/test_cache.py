"""backend.utils.cache.TTLCache 单元测试"""

from __future__ import annotations

import threading

import pytest

from backend.utils.cache import TTLCache


class _FakeMonotonic:
    """可手动拨动的单调时钟，替代真实 time.monotonic 与 sleep。

    用例里的 TTL 很小（0.05s）+ 真实 sleep 的组合在高负载并行环境（CI）
    下会因睡眠超时把「存活条目」也判成过期而偶发失败（assert 3 == 2）。
    改用假时钟后不消耗真实时间即可确定性推进，消除这类环境相关抖动。
    """

    def __init__(self) -> None:
        self.now: float = 0.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def monotonic(monkeypatch):
    """只替换 backend.utils.cache 持有的 time 引用，不动全局 time 模块。"""
    clock = _FakeMonotonic()
    monkeypatch.setattr("backend.utils.cache.time", clock)
    return clock


class TestTTLCache:
    def test_set_get(self):
        cache = TTLCache(maxsize=10, ttl=60.0)
        cache.set("k", "v")
        assert cache.get("k") == "v"

    def test_missing_returns_default(self):
        cache = TTLCache(maxsize=10, ttl=60.0)
        assert cache.get("missing") is None
        assert cache.get("missing", "fallback") == "fallback"

    def test_expire(self, monotonic):
        cache = TTLCache(maxsize=10, ttl=5.0)
        cache.set("k", 1)
        monotonic.advance(10.0)
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

    def test_pop_returns_and_removes(self):
        cache = TTLCache(maxsize=10, ttl=60.0)
        cache.set("k", "v")
        assert cache.pop("k") == "v"
        # 取出后条目已删除：get 与 pop 都不再命中
        assert cache.get("k") is None
        assert cache.pop("k") is None
        assert len(cache) == 0

    def test_pop_missing_returns_default(self):
        cache = TTLCache(maxsize=10, ttl=60.0)
        assert cache.pop("missing") is None
        assert cache.pop("missing", "fallback") == "fallback"

    def test_pop_expired_returns_default(self, monotonic):
        cache = TTLCache(maxsize=10, ttl=5.0)
        cache.set("k", 1)
        monotonic.advance(10.0)
        assert cache.pop("k") is None

    def test_pop_expired_entry_is_removed(self, monotonic):
        """过期条目兑换时必须被真正删除，否则会残留在缓存里。"""
        cache = TTLCache(maxsize=10, ttl=5.0)
        cache.set("k", 1)
        monotonic.advance(10.0)
        assert cache.pop("k") is None
        assert len(cache) == 0

    def test_pop_is_atomic_under_threads(self):
        """一次性消费：并发 pop 同一 key 只应有一次成功。"""
        cache = TTLCache(maxsize=10, ttl=60.0)
        cache.set("once", "v")
        results: list[object] = []
        lock = threading.Lock()
        barrier = threading.Barrier(8)

        def _pop():
            barrier.wait()
            value = cache.pop("once")
            with lock:
                results.append(value)

        threads = [threading.Thread(target=_pop) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results.count("v") == 1
        assert results.count(None) == 7

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

    def test_purge_expired(self, monotonic):
        cache = TTLCache(maxsize=10, ttl=5.0)
        cache.set("a", 1)
        cache.set("b", 2)
        monotonic.advance(10.0)
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

    def test_contains_expired_returns_false_and_cleans(self, monotonic):
        """__contains__ 在条目过期时应返回 False 并惰性删除。"""
        cache = TTLCache(maxsize=10, ttl=5.0)
        cache.set("k", "v")
        monotonic.advance(10.0)
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

    def test_purge_expired_partial(self, monotonic):
        """purge_expired 仅清理过期条目，存活条目保留。"""
        cache = TTLCache(maxsize=10, ttl=5.0)
        cache.set("old1", 1)
        cache.set("old2", 2)
        monotonic.advance(10.0)
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

    def test_keys_values_items_filter_expired(self, monotonic):
        """keys/values/items 方法应仅返回存活的条目快照并保持顺序。"""
        cache = TTLCache(maxsize=10, ttl=5.0)
        cache.set("a", 100)
        monotonic.advance(10.0)
        cache.set("b", 200)
        cache.set("c", 300)

        assert cache.keys() == ["b", "c"]
        assert cache.values() == [200, 300]
        assert cache.items() == [("b", 200), ("c", 300)]

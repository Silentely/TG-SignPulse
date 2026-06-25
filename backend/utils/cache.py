"""
线程安全的 LRU + TTL 内存缓存

提供 TTLCache 类，用于后端服务中需要短期缓存的场景（如任务列表、账号列表等）。
基于 OrderedDict 实现 LRU 驱逐策略，支持条目级 TTL 过期。

使用示例::

    cache = TTLCache(maxsize=100, ttl=60.0)

    cache.set("key", "value")
    value = cache.get("key")         # 返回 "value"
    value = cache.get("missing")     # 返回 None
    value = cache.get("missing", "") # 返回 ""
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Generic, TypeVar

T = TypeVar("T")

# 条目过期标记：存储 (value, expire_at) 二元组
_CacheEntry = tuple[Any, float]


class TTLCache(Generic[T]):
    """带 TTL 过期的 LRU 缓存，线程安全。

    参数:
        maxsize: 最大缓存条目数，必须 >= 1
        ttl: 条目存活时间（秒），必须 > 0
    """

    def __init__(self, maxsize: int = 128, ttl: float = 300.0) -> None:
        if maxsize < 1:
            raise ValueError(f"maxsize 必须 >= 1，收到 {maxsize}")
        if ttl <= 0:
            raise ValueError(f"ttl 必须 > 0，收到 {ttl}")

        self._maxsize = maxsize
        self._ttl = ttl
        # OrderedDict 维护插入顺序，get 时通过 move_to_end 实现 LRU
        self._data: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def get(self, key: str, default: T | None = None) -> Any:
        """获取缓存值，命中时刷新 LRU 顺序。

        若条目已过期则自动删除并返回 default。
        """
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return default

            value, expire_at = entry
            if time.monotonic() >= expire_at:
                # 已过期，惰性删除
                del self._data[key]
                return default

            # 命中，移到末尾（最近使用）
            self._data.move_to_end(key)
            return value

    def set(self, key: str, value: Any) -> None:
        """写入或更新缓存条目，自动设置 TTL。

        当缓存满时，先淘汰最久未使用的条目（LRU 驱逐）。
        """
        expire_at = time.monotonic() + self._ttl
        with self._lock:
            if key in self._data:
                # 更新已有条目，移到末尾
                self._data[key] = (value, expire_at)
                self._data.move_to_end(key)
            else:
                # 新条目，先检查容量
                if len(self._data) >= self._maxsize:
                    # 淘汰最旧的条目（OrderedDict 头部）
                    self._data.popitem(last=False)
                self._data[key] = (value, expire_at)

    def delete(self, key: str) -> bool:
        """删除指定条目，返回是否存在。"""
        with self._lock:
            if key in self._data:
                del self._data[key]
                return True
            return False

    def clear(self) -> int:
        """清空所有缓存，返回删除的条目数。"""
        with self._lock:
            count = len(self._data)
            self._data.clear()
            return count

    def __contains__(self, key: str) -> bool:
        """检查 key 是否存在且未过期。"""
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return False
            _, expire_at = entry
            if time.monotonic() >= expire_at:
                del self._data[key]
                return False
            self._data.move_to_end(key)
            return True

    def __len__(self) -> int:
        """返回当前条目数（包含可能已过期但尚未清理的条目）。"""
        with self._lock:
            return len(self._data)

    def __repr__(self) -> str:
        return f"TTLCache(maxsize={self._maxsize}, ttl={self._ttl}, size={len(self)})"

    # ------------------------------------------------------------------
    # 批量操作
    # ------------------------------------------------------------------

    _SENTINEL = object()

    def get_many(self, keys: list[str]) -> dict[str, Any]:
        """批量获取，仅返回命中的键值对（支持缓存 None 值）。"""
        result: dict[str, Any] = {}
        for key in keys:
            val = self.get(key, default=self._SENTINEL)
            if val is not self._SENTINEL:
                result[key] = val
        return result

    def set_many(self, items: dict[str, Any]) -> None:
        """批量写入。"""
        for key, value in items.items():
            self.set(key, value)

    def delete_many(self, keys: list[str]) -> int:
        """批量删除，返回实际删除数。"""
        count = 0
        for key in keys:
            if self.delete(key):
                count += 1
        return count

    # ------------------------------------------------------------------
    # 过期清理
    # ------------------------------------------------------------------

    def purge_expired(self) -> int:
        """主动清理所有已过期条目，返回清理数量。

        通常不需要手动调用——get/set 已经惰性处理过期。
        在需要精确统计存活条目数时使用。
        """
        now = time.monotonic()
        expired_keys: list[str] = []
        with self._lock:
            for key, (_, expire_at) in self._data.items():
                if now >= expire_at:
                    expired_keys.append(key)
            for key in expired_keys:
                del self._data[key]
        return len(expired_keys)

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def maxsize(self) -> int:
        """最大容量。"""
        return self._maxsize

    @property
    def ttl(self) -> float:
        """条目存活时间（秒）。"""
        return self._ttl

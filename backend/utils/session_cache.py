"""
异步会话缓存

提供 SessionCache 类，用于管理 Telegram 客户端会话的复用，避免重复连接。
基于 asyncio.Lock 保证异步安全，支持最大会话数限制和 LRU 驱逐策略。

设计目标：
- 复用已建立的 Telegram 客户端连接，减少重复 connect/disconnect 开销
- 通过最大会话数限制控制内存占用
- 提供异步安全的存取接口，适配高并发场景

使用示例::

    cache = SessionCache(maxsize=10)

    session = MockTelegramClient("account1")
    await cache.set("account1", session)

    client = await cache.get("account1")
    # client is session

    await cache.remove("account1")
    await cache.clear()
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import Any, Optional

logger = logging.getLogger("backend.session_cache")


class SessionCache:
    """异步会话缓存，用于管理 Telegram 客户端实例的复用。

    参数:
        maxsize: 最大会话数，必须 >= 1。超出时按 LRU 策略驱逐最久未使用的会话。
    """

    def __init__(self, maxsize: int = 10) -> None:
        if maxsize < 1:
            raise ValueError(f"maxsize 必须 >= 1，收到 {maxsize}")

        self._maxsize = maxsize
        self._sessions: OrderedDict[str, Any] = OrderedDict()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    async def get(self, key: str) -> Optional[Any]:
        """获取缓存的会话，命中时刷新 LRU 顺序。

        若 key 不存在返回 None。
        """
        async with self._lock:
            if key not in self._sessions:
                return None
            # 移到末尾（最近使用）
            self._sessions.move_to_end(key)
            return self._sessions[key]

    async def set(self, key: str, session: Any) -> Optional[Any]:
        """写入或更新会话缓存。

        当缓存满时，先淘汰最久未使用的会话（LRU 驱逐）。
        被淘汰的会话会被返回，由调用方负责关闭。

        Returns:
            被驱逐的旧会话（如果存在），否则返回 None。
        """
        evicted = None
        async with self._lock:
            if key in self._sessions:
                # 更新已有条目，移到末尾
                self._sessions[key] = session
                self._sessions.move_to_end(key)
                return None

            # 新条目，先检查容量
            if len(self._sessions) >= self._maxsize:
                # 淘汰最旧的条目（OrderedDict 头部）
                _, evicted = self._sessions.popitem(last=False)
                logger.debug("会话缓存已满，驱逐最久未使用的会话")

            self._sessions[key] = session
            return evicted

    async def remove(self, key: str) -> Optional[Any]:
        """移除指定会话，返回被移除的会话对象。

        若 key 不存在返回 None。调用方负责关闭返回的会话。
        """
        async with self._lock:
            return self._sessions.pop(key, None)

    async def clear(self) -> list[Any]:
        """清空所有会话缓存，返回所有被移除的会话对象列表。

        调用方负责关闭返回的会话。
        """
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            return sessions

    async def contains(self, key: str) -> bool:
        """检查 key 是否存在于缓存中。"""
        async with self._lock:
            return key in self._sessions

    async def keys(self) -> list[str]:
        """返回所有缓存的 key 列表（按 LRU 顺序，最久未使用在前）。"""
        async with self._lock:
            return list(self._sessions.keys())

    async def size(self) -> int:
        """返回当前缓存的会话数。"""
        async with self._lock:
            return len(self._sessions)

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def maxsize(self) -> int:
        """最大容量。"""
        return self._maxsize

    def __repr__(self) -> str:
        return f"SessionCache(maxsize={self._maxsize}, size={len(self._sessions)})"

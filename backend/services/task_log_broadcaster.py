"""
任务实时日志广播器（Pub/Sub）。
解耦运行中日志与 WebSocket 订阅端，消除轮询开销。
"""

from __future__ import annotations

import asyncio
import collections
from dataclasses import dataclass
from typing import Any, Dict, Optional, Set


@dataclass(frozen=True)
class StreamKey:
    """任务实时日志流的唯一标识三元组。"""

    account_name: Optional[str] = None
    task_name: str = ""
    run_id: Optional[str] = None


class TaskLogBroadcaster:
    """
    事件驱动的任务日志广播器。

    特性：
    - 三元组 StreamKey 强隔离 (account_name, task_name, run_id)
    - 慢消费者背压队列，溢出时丢弃最旧日志并记录 dropped_count
    - 环形缓冲区快照回放 (subscribe with after_seq)
    - 自动清理无订阅者的注册表项
    """

    def __init__(
        self,
        max_queue_size: int = 1000,
        history_size: int = 1000,
        max_streams: int = 200,
    ) -> None:
        self.max_queue_size = max_queue_size
        self.history_size = history_size
        self.max_streams = max_streams

        self._subscribers: dict[StreamKey, Set[asyncio.Queue[Dict[str, Any]]]] = (
            collections.defaultdict(set)
        )
        self._dropped_counts: dict[StreamKey, dict[asyncio.Queue[Dict[str, Any]], int]] = (
            collections.defaultdict(dict)
        )
        self._history: dict[StreamKey, collections.deque[Dict[str, Any]]] = (
            collections.defaultdict(lambda: collections.deque(maxlen=self.history_size))
        )
        self._seq_counters: dict[StreamKey, int] = collections.defaultdict(int)

    def subscribe(
        self,
        key: StreamKey,
        after_seq: Optional[int] = None,
    ) -> asyncio.Queue[Dict[str, Any]]:
        """
        订阅指定流。
        若指定 after_seq，则按时间顺序回放历史中 seq > after_seq 的事件。
        """
        q: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=self.max_queue_size)
        self._subscribers[key].add(q)
        self._dropped_counts[key][q] = 0

        if after_seq is not None and key in self._history:
            for event in list(self._history[key]):
                if event.get("seq", 0) > after_seq:
                    self._deliver_to_queue(key, q, event)

        return q

    def unsubscribe(self, key: StreamKey, queue: asyncio.Queue[Dict[str, Any]]) -> None:
        """取消指定队列的订阅，若订阅数归零则清理相关映射表。"""
        if key in self._subscribers:
            self._subscribers[key].discard(queue)
            if not self._subscribers[key]:
                del self._subscribers[key]

        if key in self._dropped_counts:
            self._dropped_counts[key].pop(queue, None)
            if not self._dropped_counts[key]:
                del self._dropped_counts[key]

    def has_subscribers(self, key: StreamKey) -> bool:
        """检查指定 key 是否仍有活跃订阅者。"""
        return bool(self._subscribers.get(key))

    def get_dropped_count(
        self,
        key: StreamKey,
        queue: asyncio.Queue[Dict[str, Any]],
    ) -> int:
        """获取指定订阅队列因背压被丢弃的事件数。"""
        return self._dropped_counts.get(key, {}).get(queue, 0)

    def _deliver_to_queue(
        self,
        key: StreamKey,
        queue: asyncio.Queue[Dict[str, Any]],
        event: Dict[str, Any],
    ) -> None:
        """安全地将事件写入队列，满时剔除最旧元素。"""
        if queue.full():
            try:
                queue.get_nowait()
                self._dropped_counts[key][queue] = (
                    self._dropped_counts[key].get(queue, 0) + 1
                )
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass

    def publish_nowait(self, key: StreamKey, event: Dict[str, Any]) -> None:
        """非阻塞发布事件。分配递增序列号并分发给所有订阅者与历史回放缓冲。"""
        payload = dict(event)
        seq = payload.get("seq")
        if seq is None:
            self._seq_counters[key] += 1
            payload["seq"] = self._seq_counters[key]
        else:
            self._seq_counters[key] = max(self._seq_counters[key], int(seq))

        if len(self._history) >= self.max_streams and key not in self._history:
            # Clean oldest inactive stream without subscribers
            for old_key in list(self._history.keys()):
                if not self._subscribers.get(old_key):
                    self.clear_stream(old_key)
                    break
        self._history[key].append(payload)

        subscribers = list(self._subscribers.get(key, ()))
        for q in subscribers:
            self._deliver_to_queue(key, q, payload)

    async def publish(self, key: StreamKey, event: Dict[str, Any]) -> None:
        """异步接口发布事件。"""
        self.publish_nowait(key, event)

    def publish_done_nowait(
        self,
        key: StreamKey,
        event: Optional[Dict[str, Any]] = None,
    ) -> None:
        """非阻塞发布终端完成事件。"""
        payload = dict(event or {})
        payload.setdefault("type", "done")
        payload.setdefault("is_running", False)
        self.publish_nowait(key, payload)

    async def publish_done(
        self,
        key: StreamKey,
        event: Optional[Dict[str, Any]] = None,
    ) -> None:
        """异步接口发布终端完成事件。"""
        self.publish_done_nowait(key, event)

    def clear_stream(self, key: StreamKey) -> None:
        """清理指定流的缓冲与计数。"""
        self._history.pop(key, None)
        self._seq_counters.pop(key, None)


_broadcaster_instance: Optional[TaskLogBroadcaster] = None


def get_task_log_broadcaster() -> TaskLogBroadcaster:
    """获取全局 TaskLogBroadcaster 单例。"""
    global _broadcaster_instance
    if _broadcaster_instance is None:
        _broadcaster_instance = TaskLogBroadcaster()
    return _broadcaster_instance


def set_task_log_broadcaster(broadcaster: Optional[TaskLogBroadcaster]) -> None:
    """设置或重置全局 TaskLogBroadcaster 单例（测试用）。"""
    global _broadcaster_instance
    _broadcaster_instance = broadcaster

"""
任务实时日志广播器（Pub/Sub）。
解耦运行中日志与 WebSocket 订阅端，消除轮询开销。
"""

from __future__ import annotations

import asyncio
import collections
import threading
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
    - 线程安全：日志 Handler 可能在工作线程 emit，发布经 loop.call_soon_threadsafe 投递
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

        # 保护序列号、历史缓冲与订阅注册表：发布可能来自非事件循环线程
        self._lock = threading.Lock()
        self._subscribers: dict[StreamKey, Set[asyncio.Queue[Dict[str, Any]]]] = (
            collections.defaultdict(set)
        )
        self._dropped_counts: dict[
            StreamKey, dict[asyncio.Queue[Dict[str, Any]], int]
        ] = collections.defaultdict(dict)
        # 记录每个订阅队列所属事件循环，跨线程发布时以其为投递目标
        self._queue_loops: dict[
            asyncio.Queue[Dict[str, Any]], asyncio.AbstractEventLoop
        ] = {}
        self._history: dict[StreamKey, collections.deque[Dict[str, Any]]] = (
            collections.defaultdict(lambda: collections.deque(maxlen=self.history_size))
        )
        self._seq_counters: dict[StreamKey, int] = collections.defaultdict(int)

    @staticmethod
    def _current_loop() -> Optional[asyncio.AbstractEventLoop]:
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return None

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
        loop = self._current_loop()
        with self._lock:
            self._subscribers[key].add(q)
            self._dropped_counts[key][q] = 0
            if loop is not None:
                self._queue_loops[q] = loop

        if after_seq is not None:
            with self._lock:
                backlog = list(self._history.get(key, ()))
            for event in backlog:
                if event.get("seq", 0) > after_seq:
                    self._deliver_to_queue(key, q, event)

        return q

    def unsubscribe(self, key: StreamKey, queue: asyncio.Queue[Dict[str, Any]]) -> None:
        """取消指定队列的订阅，若订阅数归零则清理相关映射表。"""
        with self._lock:
            subs = self._subscribers.get(key)
            if subs is not None:
                subs.discard(queue)
                if not subs:
                    del self._subscribers[key]

            dropped = self._dropped_counts.get(key)
            if dropped is not None:
                dropped.pop(queue, None)
                if not dropped:
                    del self._dropped_counts[key]

            self._queue_loops.pop(queue, None)

    def has_subscribers(self, key: StreamKey) -> bool:
        """检查指定 key 是否仍有活跃订阅者。"""
        with self._lock:
            return bool(self._subscribers.get(key))

    def get_dropped_count(
        self,
        key: StreamKey,
        queue: asyncio.Queue[Dict[str, Any]],
    ) -> int:
        """获取指定订阅队列因背压被丢弃的事件数。"""
        with self._lock:
            return self._dropped_counts.get(key, {}).get(queue, 0)

    def _deliver_to_queue(
        self,
        key: StreamKey,
        queue: asyncio.Queue[Dict[str, Any]],
        event: Dict[str, Any],
    ) -> None:
        """安全地将事件写入队列，满时剔除最旧元素（须在队列所属事件循环内执行）。"""
        with self._lock:
            dropped = self._dropped_counts.get(key)
            if dropped is None or queue not in dropped:
                # 订阅已取消（或非本流队列），不再投递
                return
            if queue.full():
                try:
                    queue.get_nowait()
                    dropped[queue] = dropped.get(queue, 0) + 1
                except asyncio.QueueEmpty:
                    pass
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass

    def publish_nowait(self, key: StreamKey, event: Dict[str, Any]) -> None:
        """非阻塞发布事件。分配递增序列号并分发给所有订阅者与历史回放缓冲。

        可从任意线程调用：订阅队列所属事件循环与当前线程不一致时，
        经 loop.call_soon_threadsafe 投递，避免跨线程操作 asyncio.Queue。
        """
        payload = dict(event)
        with self._lock:
            seq = payload.get("seq")
            if seq is None:
                self._seq_counters[key] += 1
                payload["seq"] = self._seq_counters[key]
            else:
                self._seq_counters[key] = max(self._seq_counters[key], int(seq))

            can_store_history = True
            if len(self._history) >= self.max_streams and key not in self._history:
                # Clean oldest inactive stream without subscribers
                for old_key in list(self._history.keys()):
                    if not self._subscribers.get(old_key):
                        self._clear_stream_locked(old_key)
                        break
                can_store_history = len(self._history) < self.max_streams
            if can_store_history:
                self._history[key].append(payload)

            targets = [
                (q, self._queue_loops.get(q))
                for q in list(self._subscribers.get(key, ()))
            ]

        if not targets:
            return

        current_loop = self._current_loop()
        for q, loop in targets:
            if loop is None or loop is current_loop:
                self._deliver_to_queue(key, q, payload)
                continue
            try:
                loop.call_soon_threadsafe(self._deliver_to_queue, key, q, payload)
            except RuntimeError:
                # 目标事件循环已关闭：丢弃该订阅的投递
                pass

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
        with self._lock:
            self._clear_stream_locked(key)

    def _clear_stream_locked(self, key: StreamKey) -> None:
        """clear_stream 的无锁内部实现，供已持锁路径复用，避免自锁死。"""
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

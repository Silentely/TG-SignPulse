# tg_signer/core/flow_event_bus.py
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("tg_signer.flow_event_bus")

@dataclass(frozen=True)
class TelegramMessageEvent:
    event_id: str
    chat_id: int
    message_thread_id: Optional[int]
    message_id: int
    sender_id: Optional[int]
    event_type: str
    text: str
    occurred_at: float

class TelegramEventBus:
    """带话题隔离、水位线回补与有界通道的响应式消息事件分发器"""

    def __init__(self, buffer_size: int = 50, buffer_ttl_seconds: float = 300.0):
        self._subscribers: Dict[Tuple[int, Optional[int]], List[asyncio.Queue]] = {}
        self._history_buffers: Dict[Tuple[int, Optional[int]], List[TelegramMessageEvent]] = {}
        self._buffer_size = buffer_size
        self._buffer_ttl = buffer_ttl_seconds

    def subscribe(
        self,
        chat_id: int,
        message_thread_id: Optional[int] = None,
        min_message_id: Optional[int] = None,
    ) -> asyncio.Queue:
        key = (chat_id, message_thread_id)
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.setdefault(key, []).append(queue)

        if min_message_id is not None and key in self._history_buffers:
            for ev in self._history_buffers[key]:
                if ev.message_id > min_message_id and ev.event_type == "NEW_MESSAGE":
                    try:
                        queue.put_nowait(ev)
                    except asyncio.QueueFull:
                        break

        return queue

    def unsubscribe(
        self,
        chat_id: int,
        message_thread_id: Optional[int],
        queue: asyncio.Queue,
    ) -> None:
        key = (chat_id, message_thread_id)
        if key in self._subscribers and queue in self._subscribers[key]:
            self._subscribers[key].remove(queue)
            if not self._subscribers[key]:
                del self._subscribers[key]

    async def publish(self, event: TelegramMessageEvent) -> None:
        key = (event.chat_id, event.message_thread_id)
        now = time.time()
        
        buf = self._history_buffers.setdefault(key, [])
        buf.append(event)
        self._history_buffers[key] = [
            e for e in buf[-self._buffer_size:] if now - e.occurred_at <= self._buffer_ttl
        ]

        for q in self._subscribers.get(key, []):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(f"订阅队列已满，丢弃慢消费者事件: {event.event_id}")

# tg_signer/core/flow_event_bus.py
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

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
    is_outgoing: bool = False
    button_snapshot: tuple[Any, ...] = ()
    message_revision: str = ""

    def __post_init__(self) -> None:
        """Identify each visible revision, including edits to an inline keyboard."""
        snapshot = json.dumps(
            {
                "chat_id": self.chat_id,
                "thread_id": self.message_thread_id,
                "message_id": self.message_id,
                "sender_id": self.sender_id,
                "event_type": self.event_type,
                "text": self.text,
                "buttons": self.button_snapshot,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        revision = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
        object.__setattr__(self, "message_revision", revision)
        object.__setattr__(
            self,
            "event_id",
            f"msg_{self.chat_id}_{self.message_thread_id}_{self.message_id}_{self.event_type.lower()}_{revision[:16]}",
        )


def _normalize_chat_id(cid: Any) -> Any:
    try:
        return int(cid)
    except (ValueError, TypeError):
        return cid


class TelegramEventBus:
    """带话题隔离、水位线回补与有界通道的响应式消息事件分发器"""

    def __init__(self, buffer_size: int = 50, buffer_ttl_seconds: float = 300.0):
        self._subscribers: Dict[Tuple[int, Optional[int]], List[asyncio.Queue]] = {}
        self._history_buffers: Dict[
            Tuple[int, Optional[int]], List[TelegramMessageEvent]
        ] = {}
        self._buffer_size = buffer_size
        self._buffer_ttl = buffer_ttl_seconds

    def subscribe(
        self,
        chat_id: int,
        message_thread_id: Optional[int] = None,
        min_message_id: Optional[int] = None,
        event_type: Optional[str] = "NEW_MESSAGE",
        since_timestamp: Optional[float] = None,
    ) -> asyncio.Queue:
        key = (_normalize_chat_id(chat_id), message_thread_id)
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.setdefault(key, []).append(queue)

        def _matches_type(ev_type: str) -> bool:
            if not event_type or event_type.upper() in {"ANY", "ALL"}:
                return ev_type.upper() in {"NEW_MESSAGE", "EDITED_MESSAGE"}
            return ev_type.upper() == event_type.upper()

        if key in self._history_buffers:
            now = time.time()
            for ev in self._history_buffers[key]:
                if now - ev.occurred_at > self._buffer_ttl:
                    continue
                if getattr(ev, "is_outgoing", False):
                    continue
                if not _matches_type(ev.event_type):
                    continue
                matches_watermark = False
                if min_message_id is not None:
                    matches_watermark = ev.message_id > min_message_id
                elif since_timestamp is not None:
                    matches_watermark = ev.occurred_at >= since_timestamp
                else:
                    matches_watermark = (now - ev.occurred_at) <= 5.0

                if matches_watermark:
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
        key = (_normalize_chat_id(chat_id), message_thread_id)
        if key in self._subscribers and queue in self._subscribers[key]:
            self._subscribers[key].remove(queue)
            if not self._subscribers[key]:
                del self._subscribers[key]

    async def publish(
        self, event: TelegramMessageEvent, *, include_legacy_scope: bool = False
    ) -> None:
        chat_id = _normalize_chat_id(event.chat_id)
        keys = [(chat_id, event.message_thread_id)]
        if include_legacy_scope and event.message_thread_id is not None:
            keys.append((chat_id, None))
        now = time.time()

        for key in keys:
            buf = self._history_buffers.setdefault(key, [])
            latest_revision = next(
                (
                    existing
                    for existing in reversed(buf)
                    if existing.message_id == event.message_id
                    and existing.message_thread_id == event.message_thread_id
                    and existing.event_type == event.event_type
                    and now - existing.occurred_at <= self._buffer_ttl
                ),
                None,
            )
            if (
                latest_revision is not None
                and latest_revision.event_id == event.event_id
            ):
                continue
            buf.append(event)
            self._history_buffers[key] = [
                e
                for e in buf[-self._buffer_size :]
                if now - e.occurred_at <= self._buffer_ttl
            ]

            for q in self._subscribers.get(key, []):
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning(f"订阅队列已满，丢弃慢消费者事件: {event.event_id}")

    def clear(self, chat_id: Optional[int] = None) -> None:
        """重置所有（或指定会话）订阅与历史缓冲区，避免跨任务或测试间相互干扰"""
        if chat_id is None:
            self._subscribers.clear()
            self._history_buffers.clear()
        else:
            to_del_sub = [
                k for k in self._subscribers if k[0] == _normalize_chat_id(chat_id)
            ]
            for k in to_del_sub:
                self._subscribers.pop(k, None)
            to_del_buf = [
                k for k in self._history_buffers if k[0] == _normalize_chat_id(chat_id)
            ]
            for k in to_del_buf:
                self._history_buffers.pop(k, None)

    def get_history(
        self,
        chat_id: int,
        message_thread_id: Optional[int] = None,
        min_message_id: Optional[int] = None,
        limit: int = 10,
    ) -> List[TelegramMessageEvent]:
        """获取指定会话与话题的最近事件历史，支持调试回溯与状态核验"""
        key = (_normalize_chat_id(chat_id), message_thread_id)
        now = time.time()
        buf = [
            ev
            for ev in self._history_buffers.get(key, [])
            if now - ev.occurred_at <= self._buffer_ttl
        ]
        if min_message_id is not None:
            buf = [ev for ev in buf if ev.message_id >= min_message_id]
        return buf[-max(1, limit) :]

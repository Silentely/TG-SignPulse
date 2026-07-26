"""
签到历史实时事件总线（进程内）

写路径（_save_run_info → append_index_entry）发布摘要；
SSE `/api/events/sign-history` 订阅后阻塞等待，避免 2s 扫盘/扫索引。

设计约束：
- 单进程有效（与当前 uvicorn 单 worker 部署一致）
- 慢消费者：队列满时丢弃最旧，保证写路径不阻塞
- 无订阅者时 publish 为空操作
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, AsyncIterator, Dict, Optional, Set

logger = logging.getLogger("backend.sign_history_events")

# 每个订阅者队列容量；满则丢最旧
_QUEUE_MAXSIZE = 64

_lock = threading.Lock()
_subscribers: Set[asyncio.Queue] = set()
_loop: Optional[asyncio.AbstractEventLoop] = None


def _get_loop() -> Optional[asyncio.AbstractEventLoop]:
    global _loop
    try:
        loop = asyncio.get_running_loop()
        _loop = loop
        return loop
    except RuntimeError:
        return _loop


def subscribe() -> asyncio.Queue:
    """注册订阅队列（须在事件循环内调用）。"""
    global _loop
    try:
        _loop = asyncio.get_running_loop()
    except RuntimeError:
        pass
    q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
    with _lock:
        _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    with _lock:
        _subscribers.discard(q)
    # 排空，避免悬挂引用
    try:
        while not q.empty():
            q.get_nowait()
    except Exception:
        pass


def publish_sign_history(entry: Dict[str, Any]) -> None:
    """
    发布一条历史摘要。可从任意线程/协程调用。

    entry 字段与索引一致：time/created_at, account_name, task_name,
    success, message, failure_category。
    """
    if not isinstance(entry, dict):
        return
    payload = {
        "account_name": str(entry.get("account_name") or ""),
        "task_name": str(entry.get("task_name") or ""),
        "success": bool(entry.get("success", False)),
        "message": str(entry.get("message") or entry.get("bot_message") or ""),
        "created_at": str(
            entry.get("created_at") or entry.get("time") or ""
        ),
        "failure_category": str(entry.get("failure_category") or ""),
        "time": str(entry.get("time") or entry.get("created_at") or ""),
    }

    with _lock:
        queues = list(_subscribers)
    if not queues:
        return

    loop = _get_loop()

    def _put(q: asyncio.Queue) -> None:
        try:
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(payload)
        except Exception as exc:
            logger.debug("publish to subscriber failed: %s", exc)

    for q in queues:
        if loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(_put, q)
            except RuntimeError:
                _put(q)
        else:
            _put(q)


async def iter_sign_history_events(
    *,
    heartbeat_seconds: float = 15.0,
    idle_poll_seconds: float = 0.5,
) -> AsyncIterator[Dict[str, Any]]:
    """
    异步迭代：产出 {"type": "event"|"heartbeat", "data": ...}。

    调用方负责 subscribe 生命周期；本生成器内部 subscribe/unsubscribe。
    """
    q = subscribe()
    try:
        while True:
            try:
                item = await asyncio.wait_for(q.get(), timeout=heartbeat_seconds)
                yield {"type": "event", "data": item}
            except asyncio.TimeoutError:
                yield {"type": "heartbeat", "data": None}
            # 轻微让出，避免紧密循环
            if idle_poll_seconds > 0:
                await asyncio.sleep(0)
    finally:
        unsubscribe(q)


def subscriber_count() -> int:
    with _lock:
        return len(_subscribers)


def reset_for_tests() -> None:
    """测试用：清空所有订阅。"""
    with _lock:
        qs = list(_subscribers)
        _subscribers.clear()
    for q in qs:
        try:
            while not q.empty():
                q.get_nowait()
        except Exception:
            pass

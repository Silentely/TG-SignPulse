from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from backend.core.auth import verify_token
from backend.core.database import get_session_local
from backend.models.user import User

router = APIRouter()
_logger = logging.getLogger("backend.events")

# SSE 推送参数（语义见各使用处）：
# 冷启动种子：索引最近条数，仅作去重种子不重复推送历史
SSE_SEED_LIMIT = 30
# 低频兜底扫描：防止跨线程 publish 丢失或启动竞态，间隔与每次取数
SSE_FALLBACK_SCAN_INTERVAL = 30.0
SSE_FALLBACK_SCAN_LIMIT = 20
# 事件队列等待超时（秒）：超时后进入兜底扫描/心跳分支
SSE_QUEUE_WAIT_TIMEOUT = 5.0
# 去重集合上限：超过后截断保留较新 key（内存受控）
SSE_DEDUPE_MAX = 500
SSE_DEDUPE_KEEP = 300
# 无事件时的 keep-alive 心跳间隔（秒）
SSE_HEARTBEAT_INTERVAL = 15


def _require_token(token: Optional[str]) -> User:
    """校验 EventSource 查询参数中的 JWT，返回已认证用户。"""
    if not token or not str(token).strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    session_local = get_session_local()
    with session_local() as db:
        user = verify_token(str(token).strip(), db)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        return user


def _sign_log_sse_bytes(item: dict) -> bytes:
    created = item.get("created_at") or item.get("time")
    payload = {
        "account_name": item.get("account_name"),
        "task_name": item.get("task_name"),
        "success": bool(item.get("success")),
        "message": item.get("bot_message") or item.get("message") or "",
        "created_at": created,
        "failure_category": item.get("failure_category"),
    }
    data = (
        "event: sign_log\n"
        f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    )
    return data.encode("utf-8")


def _entry_dedupe_key(item: dict) -> str:
    return (
        f"{item.get('account_name')}|{item.get('task_name')}|"
        f"{item.get('created_at') or item.get('time')}|{item.get('success')}"
    )



async def _sign_history_event_stream() -> AsyncGenerator[bytes, None]:
    """
    签到历史 SSE：优先订阅进程内事件总线；冷启动用索引种子；
    长时间无事件时用心跳 + 低频索引兜底（防 publish 丢失）。
    """
    from backend.services.sign_history_events import subscribe, unsubscribe

    # 去重集合用 dict 保留插入序（Python 3.7+）：截断时保留的是真正的最近 key，
    # 用 set 的话尾部截取是无序的，长时间运行后可能漏推或重复推
    last_seen: dict[str, bool] = {}
    last_heartbeat = time.monotonic()
    last_fallback_scan = 0.0
    fallback_interval = SSE_FALLBACK_SCAN_INTERVAL  # 兜底扫索引间隔（秒）

    # 冷启动：索引最近条目仅作去重种子，不重复推送历史
    try:
        from backend.services.sign_tasks import get_sign_task_service

        seed = get_sign_task_service().get_recent_history_logs(limit=SSE_SEED_LIMIT)
        for item in seed:
            last_seen[_entry_dedupe_key(item)] = True
    except Exception as exc:
        _logger.debug("签到历史 SSE 种子加载失败: %s", exc, exc_info=True)

    yield b"event: ready\ndata: {}\n\n"
    last_heartbeat = time.monotonic()

    q = subscribe()
    try:
        while True:
            try:
                item = await asyncio.wait_for(q.get(), timeout=SSE_QUEUE_WAIT_TIMEOUT)
            except asyncio.TimeoutError:
                item = None

            if item is not None and isinstance(item, dict):
                key = _entry_dedupe_key(item)
                if key not in last_seen:
                    last_seen[key] = True
                    yield _sign_log_sse_bytes(item)
                    last_heartbeat = time.monotonic()

            now = time.monotonic()
            # 低频兜底：防止跨线程 publish 丢失或启动竞态
            if now - last_fallback_scan >= fallback_interval:
                last_fallback_scan = now
                try:
                    from backend.services.sign_tasks import get_sign_task_service

                    entries = get_sign_task_service().get_recent_history_logs(
                        limit=SSE_FALLBACK_SCAN_LIMIT
                    )
                except Exception as exc:
                    _logger.debug("签到历史兜底扫描失败: %s", exc)
                    entries = []
                for entry in reversed(entries):
                    key = _entry_dedupe_key(entry)
                    if key in last_seen:
                        continue
                    last_seen[key] = True
                    yield _sign_log_sse_bytes(entry)
                    last_heartbeat = time.monotonic()
                if len(last_seen) > SSE_DEDUPE_MAX:
                    # 保留最近 SSE_DEDUPE_KEEP 个 key（dict 插入序即到达序）
                    last_seen = dict(list(last_seen.items())[-SSE_DEDUPE_KEEP:])

            if time.monotonic() - last_heartbeat >= SSE_HEARTBEAT_INTERVAL:
                yield b": keep-alive\n\n"
                last_heartbeat = time.monotonic()
    except asyncio.CancelledError:
        return
    finally:
        unsubscribe(q)



@router.get("/sign-history")
async def sign_history_events(
    token: Optional[str] = Query(None, description="JWT，供 EventSource 使用"),
):
    """
    签到任务历史 SSE 流。

    浏览器 EventSource 无法设置 Authorization，请使用 `?token=`。
    事件：ready / sign_log；注释行 keep-alive。
    """
    # JWT 校验含同步数据库查询，放入线程池避免阻塞事件循环
    # （每个 SSE 连接建立时都会执行一次）
    await asyncio.to_thread(_require_token, token)

    async def event_generator():
        async for chunk in _sign_history_event_stream():
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

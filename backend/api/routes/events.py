from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from backend.core.auth import get_current_user, verify_token
from backend.core.database import get_session_local
from backend.models.task_log import TaskLog
from backend.models.user import User

router = APIRouter()
_logger = logging.getLogger("backend.events")


def _require_token(token: Optional[str]) -> User:
    """校验 EventSource 查询参数中的 JWT，返回已认证用户。"""
    if not token or not str(token).strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    session_local = get_session_local()
    db = session_local()
    try:
        user = verify_token(str(token).strip(), db)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        return user
    finally:
        db.close()


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


async def _logs_event_stream(
    current_user,
) -> AsyncGenerator[bytes, None]:
    """旧版 ORM TaskLog 流（兼容）；新路径请用 /sign-history。"""
    last_id = 0
    last_heartbeat = time.monotonic()
    try:
        while True:
            session_local = get_session_local()
            db = session_local()
            try:
                logs = (
                    db.query(TaskLog)
                    .filter(TaskLog.id > last_id)
                    .order_by(TaskLog.id.asc())
                    .limit(100)
                    .all()
                )
                if logs:
                    for log in logs:
                        last_id = log.id
                        payload = {
                            "id": log.id,
                            "task_id": log.task_id,
                            "status": log.status,
                            "started_at": log.started_at.isoformat(),
                            "finished_at": log.finished_at.isoformat()
                            if log.finished_at
                            else None,
                        }
                        data = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                        yield data.encode("utf-8")
                    last_heartbeat = time.monotonic()
                elif time.monotonic() - last_heartbeat >= 15:
                    yield b": keep-alive\n\n"
                    last_heartbeat = time.monotonic()
            finally:
                db.close()
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        return


async def _sign_history_event_stream() -> AsyncGenerator[bytes, None]:
    """
    签到历史 SSE：优先订阅进程内事件总线；冷启动用索引种子；
    长时间无事件时用心跳 + 低频索引兜底（防 publish 丢失）。
    """
    from backend.services.sign_history_events import subscribe, unsubscribe

    last_seen: set[str] = set()
    last_heartbeat = time.monotonic()
    last_fallback_scan = 0.0
    fallback_interval = 30.0  # 兜底扫索引间隔（秒）

    # 冷启动：索引最近条目仅作去重种子，不重复推送历史
    try:
        from backend.services.sign_tasks import get_sign_task_service

        seed = get_sign_task_service().get_recent_history_logs(limit=30)
        for item in seed:
            last_seen.add(_entry_dedupe_key(item))
    except Exception as exc:
        _logger.debug("sign history SSE seed failed: %s", exc, exc_info=True)

    yield b"event: ready\ndata: {}\n\n"
    last_heartbeat = time.monotonic()

    q = subscribe()
    try:
        while True:
            try:
                item = await asyncio.wait_for(q.get(), timeout=5.0)
            except asyncio.TimeoutError:
                item = None

            if item is not None and isinstance(item, dict):
                key = _entry_dedupe_key(item)
                if key not in last_seen:
                    last_seen.add(key)
                    yield _sign_log_sse_bytes(item)
                    last_heartbeat = time.monotonic()

            now = time.monotonic()
            # 低频兜底：防止跨线程 publish 丢失或启动竞态
            if now - last_fallback_scan >= fallback_interval:
                last_fallback_scan = now
                try:
                    from backend.services.sign_tasks import get_sign_task_service

                    entries = get_sign_task_service().get_recent_history_logs(limit=20)
                except Exception as exc:
                    _logger.debug("sign history fallback scan failed: %s", exc)
                    entries = []
                for entry in reversed(entries):
                    key = _entry_dedupe_key(entry)
                    if key in last_seen:
                        continue
                    last_seen.add(key)
                    yield _sign_log_sse_bytes(entry)
                    last_heartbeat = time.monotonic()
                if len(last_seen) > 500:
                    # 保留较新的 key（无序 set 截断为任意 300）
                    last_seen = set(list(last_seen)[-300:])

            if time.monotonic() - last_heartbeat >= 15:
                yield b": keep-alive\n\n"
                last_heartbeat = time.monotonic()
    except asyncio.CancelledError:
        return
    finally:
        unsubscribe(q)


@router.get("/logs")
async def logs_events(
    current_user=Depends(get_current_user),
):
    """已弃用：ORM TaskLog 流。新面板请使用 /api/events/sign-history。"""

    async def event_generator():
        async for chunk in _logs_event_stream(current_user):
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Deprecation": "true",
            "X-API-Warn": "Prefer /api/events/sign-history for sign-task history.",
        },
    )


@router.get("/sign-history")
async def sign_history_events(
    token: Optional[str] = Query(None, description="JWT，供 EventSource 使用"),
):
    """
    签到任务历史 SSE 流。

    浏览器 EventSource 无法设置 Authorization，请使用 `?token=`。
    事件：ready / sign_log；注释行 keep-alive。
    """
    _require_token(token)

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

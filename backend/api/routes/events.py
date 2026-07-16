from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from backend.core.auth import get_current_user, verify_token
from backend.core.database import get_session_local
from backend.models.task_log import TaskLog

router = APIRouter()


def _require_token(token: Optional[str]) -> dict:
    if not token or not str(token).strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    payload = verify_token(str(token).strip())
    if not payload or not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    return payload


async def _logs_event_stream(
    current_user,
) -> AsyncGenerator[bytes, None]:
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
    """推送签到历史（文件存储体系）增量事件。"""
    last_seen: set[str] = set()
    last_heartbeat = time.monotonic()
    bootstrapped = False
    try:
        while True:
            try:
                from backend.services.sign_tasks import get_sign_task_service

                entries = get_sign_task_service().get_recent_history_logs(limit=30)
            except Exception:
                entries = []

            if not bootstrapped:
                for item in entries:
                    key = (
                        f"{item.get('account_name')}|{item.get('task_name')}|"
                        f"{item.get('created_at') or item.get('time')}|{item.get('success')}"
                    )
                    last_seen.add(key)
                bootstrapped = True
                yield b"event: ready\ndata: {}\n\n"
                last_heartbeat = time.monotonic()
            else:
                new_items = []
                for item in entries:
                    key = (
                        f"{item.get('account_name')}|{item.get('task_name')}|"
                        f"{item.get('created_at') or item.get('time')}|{item.get('success')}"
                    )
                    if key not in last_seen:
                        last_seen.add(key)
                        new_items.append(item)
                if len(last_seen) > 500:
                    last_seen = set(list(last_seen)[-300:])

                if new_items:
                    for item in reversed(new_items):
                        created = item.get("created_at") or item.get("time")
                        payload = {
                            "account_name": item.get("account_name"),
                            "task_name": item.get("task_name"),
                            "success": bool(item.get("success")),
                            "message": item.get("bot_message")
                            or item.get("message")
                            or "",
                            "created_at": created,
                            "failure_category": item.get("failure_category"),
                        }
                        data = (
                            "event: sign_log\n"
                            f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                        )
                        yield data.encode("utf-8")
                    last_heartbeat = time.monotonic()
                elif time.monotonic() - last_heartbeat >= 15:
                    yield b": keep-alive\n\n"
                    last_heartbeat = time.monotonic()

            await asyncio.sleep(2)
    except asyncio.CancelledError:
        return


@router.get("/logs")
async def logs_events(
    current_user=Depends(get_current_user),
):
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
        },
    )


@router.get("/sign-history")
async def sign_history_events(
    token: Optional[str] = Query(None, description="JWT，供 EventSource 使用"),
):
    """
    签到任务历史 SSE 流。

    浏览器 EventSource 无法设置 Authorization，请使用 `?token=`。
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

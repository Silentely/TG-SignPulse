from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.models.task_log import TaskLog

router = APIRouter()


async def _logs_event_stream(
    db: Session,
    current_user,
) -> AsyncGenerator[bytes, None]:
    last_id = 0
    last_heartbeat = time.monotonic()
    try:
        while True:
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
                        "finished_at": log.finished_at.isoformat() if log.finished_at else None,
                    }
                    data = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    yield data.encode("utf-8")
                last_heartbeat = time.monotonic()
            elif time.monotonic() - last_heartbeat >= 15:
                yield b": keep-alive\n\n"
                last_heartbeat = time.monotonic()
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        return


@router.get("/logs")
async def logs_events(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    async def event_generator():
        async for chunk in _logs_event_stream(db, current_user):
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )

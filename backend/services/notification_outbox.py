"""Bounded notification receipts, never a queue of secret message bodies.

An attempt is durably marked unknown before invoking its provider. A crash or
ambiguous response therefore cannot cause automatic duplicate delivery. Receipts
are retained for a bounded deduplication horizon; capacity exhaustion fails closed
instead of evicting recent identities or unresolved attempts.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

import httpx

from backend.core.config import get_settings

DeliveryState = Literal["pending", "sent", "unknown", "failed"]


class NotificationDeliveryError(RuntimeError):
    def __init__(self, notification_id: str, state: str):
        self.notification_id = notification_id
        self.state = state
        super().__init__(f"Notification {notification_id} delivery={state}")


@dataclass(frozen=True)
class NotificationEnvelope:
    notification_id: str
    event_type: str
    account_name: str
    task_name: str
    run_id: str
    payload_hash: str
    attempt: int = 0
    state: DeliveryState = "pending"
    aggregate_status: str = ""


def make_notification_envelope(
    *,
    event_type: str,
    account_name: str = "",
    task_name: str = "",
    run_id: str,
    payload: Any,
    aggregate_status: str = "",
) -> NotificationEnvelope:
    if not run_id:
        raise ValueError("A notification requires a run identity")
    identity = json.dumps(
        [run_id, event_type, account_name, task_name],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    payload_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()
    return NotificationEnvelope(
        hashlib.sha256(identity.encode()).hexdigest(),
        event_type,
        account_name,
        task_name,
        run_id,
        payload_hash,
        aggregate_status=aggregate_status,
    )


class NotificationOutbox:
    def __init__(
        self,
        path: Path | str | None = None,
        *,
        max_records: int = 10000,
        retention_seconds: float = 30 * 86400,
    ):
        self.path = (
            Path(path)
            if path is not None
            else get_settings().resolve_workdir() / "notification_outbox.db"
        )
        self.max_records = max(1, max_records)
        self.retention_seconds = max(0, retention_seconds)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS notification_outbox (
                notification_id TEXT NOT NULL, channel TEXT NOT NULL,
                event_type TEXT NOT NULL, account_name TEXT NOT NULL,
                task_name TEXT NOT NULL, run_id TEXT NOT NULL,
                payload_hash TEXT NOT NULL, aggregate_status TEXT NOT NULL,
                attempt INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL,
                error_code TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL, updated_at REAL NOT NULL,
                PRIMARY KEY (notification_id, channel),
                CHECK(state IN ('pending','sent','unknown','failed'))
            )""")
            db.execute(
                "CREATE INDEX IF NOT EXISTS ix_notification_retention ON notification_outbox(state, updated_at)"
            )

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        try:
            with db:
                yield db
        finally:
            db.close()

    def enqueue_notification(
        self, envelope: NotificationEnvelope, channel: str
    ) -> dict[str, Any]:
        if envelope.state != "pending" or envelope.attempt != 0:
            raise ValueError("New envelopes must be pending and unattempted")
        # Only bounded identifiers and hashes are stored; no URL, token or body.
        fields = (
            envelope.notification_id,
            channel,
            envelope.event_type,
            envelope.account_name,
            envelope.task_name,
            envelope.run_id,
            envelope.payload_hash,
            envelope.aggregate_status,
        )
        if any(len(field) > 256 for field in fields):
            raise ValueError("Notification metadata exceeds its size limit")
        now = time.time()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM notification_outbox WHERE notification_id=? AND channel=?",
                fields[:2],
            ).fetchone()
            if existing is not None:
                return dict(existing)
            db.execute(
                "DELETE FROM notification_outbox WHERE state IN ('sent','failed') AND updated_at < ?",
                (now - self.retention_seconds,),
            )
            if (
                db.execute("SELECT count(*) FROM notification_outbox").fetchone()[0]
                >= self.max_records
            ):
                raise RuntimeError(
                    "Notification outbox capacity reached; reconcile unresolved records or wait for retention"
                )
            db.execute(
                """INSERT INTO notification_outbox
                (notification_id,channel,event_type,account_name,task_name,run_id,payload_hash,aggregate_status,state,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,'pending',?,?)""",
                (*fields, now, now),
            )
        return self.get(envelope.notification_id, channel)

    def get(self, notification_id: str, channel: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM notification_outbox WHERE notification_id=? AND channel=?",
                (notification_id, channel),
            ).fetchone()
        if row is None:
            raise KeyError("Notification not enqueued")
        return dict(row)

    def list_records(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM notification_outbox ORDER BY updated_at DESC LIMIT ?",
                    (max(1, min(limit, 1000)),),
                )
            ]

    async def deliver_notification(
        self, notification_id: str, channel: str, sender: Callable[[], Awaitable[Any]]
    ) -> Literal["sent", "unknown", "failed"]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state FROM notification_outbox WHERE notification_id=? AND channel=?",
                (notification_id, channel),
            ).fetchone()
            if row is None:
                raise KeyError("Notification not enqueued")
            if row["state"] != "pending":
                return row["state"]
            db.execute(
                "UPDATE notification_outbox SET state='unknown', attempt=attempt+1, updated_at=? WHERE notification_id=? AND channel=?",
                (time.time(), notification_id, channel),
            )
        state = "sent"
        error_code = ""
        try:
            await sender()
        except asyncio.CancelledError:
            # Durable pre-send claim intentionally stays unknown on cancellation.
            raise
        except Exception as exc:
            error_code = type(exc).__name__
            if isinstance(
                exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
            ):
                state = "failed"
            elif (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code < 500
            ):
                state = "failed"
                error_code = f"HTTP_{exc.response.status_code}"
            else:
                # Read/write timeouts, protocol errors, and 5xx can follow acceptance.
                state = "unknown"
                if isinstance(exc, httpx.HTTPStatusError):
                    error_code = f"HTTP_{exc.response.status_code}"
        with self._connect() as db:
            db.execute(
                "UPDATE notification_outbox SET state=?, error_code=?, updated_at=? WHERE notification_id=? AND channel=?",
                (state, error_code, time.time(), notification_id, channel),
            )
        return state

    def reconcile_notification(
        self,
        notification_id: str,
        channel: str,
        *,
        confirmed_not_delivered: bool = False,
        confirmed_delivered: bool = False,
    ) -> None:
        """Explicit operator/provider evidence is required before an uncertain retry."""
        if confirmed_not_delivered == confirmed_delivered:
            raise ValueError("Provide exactly one confirmed delivery outcome")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state FROM notification_outbox WHERE notification_id=? AND channel=?",
                (notification_id, channel),
            ).fetchone()
            if row is None:
                raise KeyError("Notification not enqueued")
            if row["state"] == "sent" and confirmed_not_delivered:
                raise ValueError("A sent receipt cannot be automatically replayed")
            db.execute(
                "UPDATE notification_outbox SET state=?,error_code=?,updated_at=? WHERE notification_id=? AND channel=?",
                (
                    "pending" if confirmed_not_delivered else "sent",
                    "reconciled",
                    time.time(),
                    notification_id,
                    channel,
                ),
            )


def enqueue_notification(
    envelope: NotificationEnvelope, channel: str
) -> dict[str, Any]:
    return NotificationOutbox().enqueue_notification(envelope, channel)


async def deliver_notification(
    notification_id: str, channel: str, sender: Callable[[], Awaitable[Any]]
) -> Literal["sent", "unknown", "failed"]:
    return await NotificationOutbox().deliver_notification(
        notification_id, channel, sender
    )

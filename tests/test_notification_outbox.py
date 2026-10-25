"""Persistent notification identity and ambiguous delivery contracts."""

import asyncio
import sqlite3
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.services.notification_outbox import (
    NotificationEnvelope,
    NotificationOutbox,
    make_notification_envelope,
)


def envelope(run_id="run-1"):
    return make_notification_envelope(
        event_type="task_failure",
        account_name="alice",
        task_name="daily",
        run_id=run_id,
        payload={"message": "secret message", "token": "secret-token"},
        aggregate_status="unknown",
    )


@pytest.mark.asyncio
async def test_duplicate_enqueue_and_unknown_delivery_survive_reopen(tmp_path):
    path = tmp_path / "outbox.db"
    box = NotificationOutbox(path)
    item = envelope()
    assert isinstance(item, NotificationEnvelope)
    first = box.enqueue_notification(item, "telegram")
    assert box.enqueue_notification(item, "telegram") == first
    provider = AsyncMock(side_effect=httpx.ReadTimeout("accepted but response lost"))
    assert (
        await box.deliver_notification(item.notification_id, "telegram", provider)
        == "unknown"
    )
    reopened = NotificationOutbox(path)
    assert (
        await reopened.deliver_notification(item.notification_id, "telegram", provider)
        == "unknown"
    )
    assert provider.await_count == 1
    assert reopened.get(item.notification_id, "telegram")["attempt"] == 1
    assert "secret-token" not in path.read_bytes().decode(errors="ignore")
    assert "secret message" not in path.read_bytes().decode(errors="ignore")


@pytest.mark.asyncio
async def test_atomic_claim_prevents_concurrent_delivery(tmp_path):
    box = NotificationOutbox(tmp_path / "outbox.db")
    item = envelope()
    box.enqueue_notification(item, "telegram")
    entered = asyncio.Event()
    release = asyncio.Event()

    async def provider():
        entered.set()
        await release.wait()

    first = asyncio.create_task(
        box.deliver_notification(item.notification_id, "telegram", provider)
    )
    await entered.wait()
    assert (
        await box.deliver_notification(item.notification_id, "telegram", provider)
        == "unknown"
    )
    release.set()
    assert await first == "sent"
    assert (
        await box.deliver_notification(item.notification_id, "telegram", provider)
        == "sent"
    )


@pytest.mark.asyncio
async def test_5xx_unknown_4xx_failed_and_explicit_reconciliation(tmp_path):
    box = NotificationOutbox(tmp_path / "outbox.db")
    request = httpx.Request("POST", "https://provider.invalid/secret")
    for code, state in [(500, "unknown"), (400, "failed")]:
        item = envelope(str(code))
        box.enqueue_notification(item, "telegram")
        provider = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "secret response",
                request=request,
                response=httpx.Response(code, request=request),
            )
        )
        assert (
            await box.deliver_notification(item.notification_id, "telegram", provider)
            == state
        )
        await box.deliver_notification(item.notification_id, "telegram", provider)
        assert provider.await_count == 1
    item = envelope("500")
    box.reconcile_notification(
        item.notification_id, "telegram", confirmed_not_delivered=True
    )
    provider = AsyncMock()
    assert (
        await box.deliver_notification(item.notification_id, "telegram", provider)
        == "sent"
    )


def test_channel_identity_capacity_and_retention(tmp_path):
    box = NotificationOutbox(
        tmp_path / "outbox.db", max_records=2, retention_seconds=60
    )
    item = envelope()
    box.enqueue_notification(item, "telegram")
    box.enqueue_notification(item, "bark")
    assert envelope().notification_id == item.notification_id
    assert envelope("other").notification_id != item.notification_id
    with pytest.raises(RuntimeError, match="capacity"):
        box.enqueue_notification(envelope("other"), "telegram")
    with sqlite3.connect(box.path) as db:
        db.execute('UPDATE notification_outbox SET updated_at=0, state="sent"')
    box.enqueue_notification(envelope("other"), "telegram")
    assert len(box.list_records()) == 1


@pytest.mark.asyncio
async def test_real_success_failure_backup_helpers_use_outbox(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from backend.core.config import get_settings
    from backend.services import config
    from backend.services import push_notifications as push
    from backend.services import sign_task_notify as notify

    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    settings = {
        "telegram_bot_notify_enabled": True,
        "telegram_bot_task_success_enabled": True,
        "telegram_bot_token": "fake-secret",
        "telegram_bot_chat_id": "chat",
    }
    monkeypatch.setattr(
        config,
        "get_config_service",
        lambda: SimpleNamespace(get_global_settings=lambda: settings),
    )
    sender = AsyncMock()
    monkeypatch.setattr(push, "send_telegram_bot_message", sender)
    try:
        for _ in range(2):
            await push.send_task_success_notification(
                settings,
                account_name="alice",
                task_name="daily",
                message="done",
                run_id="success-run",
            )
            await notify.send_failure_notification(
                account_name="alice",
                task_name="daily",
                message="failed",
                run_id="failure-run",
                aggregate_status="partial",
            )
            await push.send_auto_backup_failure_notification(
                settings, error="backup failed", run_id="backup-run"
            )
        assert sender.await_count == 3
        rows = NotificationOutbox(
            get_settings().resolve_workdir() / "notification_outbox.db"
        ).list_records()
        assert len(rows) == 3
        assert {row["event_type"] for row in rows} == {
            "task_success",
            "task_failure",
            "backup_failure",
        }
        assert (
            next(row for row in rows if row["event_type"] == "task_failure")[
                "aggregate_status"
            ]
            == "partial"
        )
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_transport_never_replays_read_timeout_or_5xx(monkeypatch):
    from backend.services import push_notifications as push

    request = httpx.Request("POST", "https://93.184.216.34/hook")
    monkeypatch.setattr(push, "_validate_push_target_url", lambda url: None)
    for error in [
        httpx.ReadTimeout("after acceptance"),
        httpx.HTTPStatusError(
            "500", request=request, response=httpx.Response(500, request=request)
        ),
    ]:
        post = AsyncMock(side_effect=error)
        from types import SimpleNamespace

        monkeypatch.setattr(
            push,
            "_get_shared_http_client",
            lambda post=post: SimpleNamespace(post=post),
        )
        with pytest.raises(type(error)):
            await push._http_post_retry_once(url=str(request.url), channel="test")
        assert post.await_count == 1


@pytest.mark.asyncio
async def test_cancelled_attempt_stays_unknown_without_automatic_replay(tmp_path):
    box = NotificationOutbox(tmp_path / "outbox.db")
    item = envelope("cancelled-run")
    box.enqueue_notification(item, "telegram")
    started = asyncio.Event()

    async def provider():
        started.set()
        await asyncio.Event().wait()

    delivery = asyncio.create_task(
        box.deliver_notification(item.notification_id, "telegram", provider)
    )
    await started.wait()
    delivery.cancel()
    with pytest.raises(asyncio.CancelledError):
        await delivery
    assert box.get(item.notification_id, "telegram")["state"] == "unknown"
    sender = AsyncMock()
    assert (
        await box.deliver_notification(item.notification_id, "telegram", sender)
        == "unknown"
    )
    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_notification_unknown_receipt_stops_a_second_provider_attempt(
    tmp_path, monkeypatch
):
    from backend.core.config import get_settings
    from backend.services import push_notifications as push
    from backend.services.notification_outbox import NotificationDeliveryError

    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    sender = AsyncMock(side_effect=httpx.ReadTimeout("accepted but no receipt"))
    monkeypatch.setattr(push, "send_telegram_bot_message", sender)
    try:
        for _ in range(2):
            with pytest.raises(NotificationDeliveryError, match="unknown"):
                await push.send_outbox_telegram_message(
                    event_type="task_success",
                    run_id="same-run",
                    bot_token="fake-token",
                    chat_id="chat",
                    text="private text",
                )
        assert sender.await_count == 1
        rows = NotificationOutbox(
            get_settings().resolve_workdir() / "notification_outbox.db"
        ).list_records()
        assert rows[0]["state"] == "unknown"
        assert "fake-token" not in str(rows)
        assert "private text" not in str(rows)
    finally:
        get_settings.cache_clear()

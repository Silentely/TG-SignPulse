"""Tests for TG-SignPulse community plugins:
checkin_observer and chat_cleaner.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from community_plugins.chat_cleaner.main import (
    handle_chat_cleaner,
)
from community_plugins.checkin_observer.main import (
    handle_checkin_observer,
)
from tg_signer.core.plugin_storage import PluginStore
from tg_signer.core.plugins import (
    PluginContext,
    PluginMessageNotFoundError,
    PluginRegistry,
    PluginStorageClient,
)


def _make_mock_ctx(
    params: dict | None = None,
    chat_id: int = -100123456789,
    message_id: int = 100,
    reply_to_message_id: int | None = 99,
    text: str = "",
    plugin_name: str = "checkin_observer",
    store: PluginStore | None = None,
) -> PluginContext:
    mock_app = MagicMock()
    mock_app.delete_messages = AsyncMock(return_value=True)

    msg = MagicMock()
    msg.id = message_id
    msg.reply_to_message_id = reply_to_message_id
    msg.text = text
    msg.caption = None

    ctx = PluginContext(
        app=mock_app,
        chat_id=chat_id,
        message=msg,
        params=dict(params or {}),
        plugin_name=plugin_name,
        context_version=2,
    )
    if store is not None:
        ctx.storage = PluginStorageClient(
            namespace=f"test:{plugin_name}:{chat_id}", store=store
        )
    return ctx


# ============================================================================
# checkin_observer Tests
# ============================================================================


@pytest.mark.asyncio
async def test_checkin_observer_atomic_points_parsing(tmp_path):
    """Validates points parsing and atomic persistence to ledger:latest_balance."""
    store = PluginStore(tmp_path / "storage.db")
    ctx = _make_mock_ctx(
        params={
            "enable_points": True,
            "enable_streak": False,
            "enable_cleanup": False,
        },
        text="🎉 签到成功！获得 20 积分，当前积分：1350 点",
        store=store,
    )

    res = await handle_checkin_observer(ctx)
    assert res is True

    balance = await ctx.storage.get("ledger:latest_balance")
    assert balance == 1350 or balance == 1350.0

    seen = await ctx.storage.get(f"seen:{ctx.message.id}")
    assert seen is True


@pytest.mark.asyncio
async def test_checkin_observer_points_floating_and_gain(tmp_path):
    """Validates points parsing with floating point balance and gain."""
    store = PluginStore(tmp_path / "storage.db")
    ctx = _make_mock_ctx(
        params={
            "enable_points": True,
            "enable_streak": False,
            "enable_cleanup": False,
        },
        text="Check-in Success! Points: 88.5, Gain: +5.0",
        store=store,
    )

    res = await handle_checkin_observer(ctx)
    assert res is True

    balance = await ctx.storage.get("ledger:latest_balance")
    assert balance == 88.5


@pytest.mark.asyncio
async def test_checkin_observer_streak_calibration_from_text(tmp_path):
    """Validates streak extraction and calendar date persistence (streak:current, streak:last_date)."""
    store = PluginStore(tmp_path / "storage.db")
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ctx = _make_mock_ctx(
        params={
            "enable_points": False,
            "enable_streak": True,
            "enable_cleanup": False,
        },
        text="打卡成功！已连续签到 12 天，明天继续哦！",
        store=store,
    )

    res = await handle_checkin_observer(ctx)
    assert res is True

    current_streak = await ctx.storage.get("streak:current")
    last_date = await ctx.storage.get("streak:last_date")
    assert current_streak == 12
    assert last_date == today_str


@pytest.mark.asyncio
async def test_checkin_observer_natural_calendar_streak_increment(tmp_path):
    """Validates streak increment when checkin occurred yesterday without explicit streak text."""
    store = PluginStore(tmp_path / "storage.db")
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()
    today_str = date.today().isoformat()

    ctx = _make_mock_ctx(
        params={
            "enable_points": False,
            "enable_streak": True,
            "enable_cleanup": False,
        },
        text="签到成功！",
        store=store,
    )
    # Pre-populate yesterday's streak
    await ctx.storage.set("streak:current", 5)
    await ctx.storage.set("streak:last_date", yesterday_str)

    res = await handle_checkin_observer(ctx)
    assert res is True

    assert await ctx.storage.get("streak:current") == 6
    assert await ctx.storage.get("streak:last_date") == today_str


@pytest.mark.asyncio
async def test_checkin_observer_cleanup_enabled(tmp_path):
    """When enable_cleanup=True, deletes bot reply (message.id) and trigger command (reply_to_message_id)."""
    store = PluginStore(tmp_path / "storage.db")
    ctx = _make_mock_ctx(
        params={
            "enable_points": True,
            "enable_streak": False,
            "enable_cleanup": True,
            "delay_seconds": 2.5,
        },
        message_id=105,
        reply_to_message_id=104,
        text="签到成功！当前余额: 500",
        store=store,
    )

    with (
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch.object(ctx, "delete_message", wraps=ctx.delete_message) as spy_delete,
    ):
        res = await handle_checkin_observer(ctx)
        assert res is True

        mock_sleep.assert_awaited_once_with(2.5)
        # Should delete bot reply (105) and trigger command (104)
        deleted_ids = [
            call.kwargs.get("message_id") for call in spy_delete.call_args_list
        ]
        assert 105 in deleted_ids
        assert 104 in deleted_ids


@pytest.mark.asyncio
async def test_checkin_observer_cleanup_handles_message_not_found(tmp_path):
    """Validates graceful handling of PluginMessageNotFoundError during message cleanup."""
    store = PluginStore(tmp_path / "storage.db")
    ctx = _make_mock_ctx(
        params={
            "enable_points": True,
            "enable_streak": False,
            "enable_cleanup": True,
            "delay_seconds": 0.0,
        },
        message_id=108,
        reply_to_message_id=107,
        text="签到成功！当前积分: 300",
        store=store,
    )

    with patch.object(
        ctx,
        "delete_message",
        AsyncMock(
            side_effect=PluginMessageNotFoundError("Message was already deleted")
        ),
    ):
        # Should not raise exception
        res = await handle_checkin_observer(ctx)
        assert res is True


@pytest.mark.asyncio
async def test_checkin_observer_idempotency_guard(tmp_path):
    """Validates idempotency guard using seen:<msg_id> key to prevent duplicate processing."""
    store = PluginStore(tmp_path / "storage.db")
    ctx = _make_mock_ctx(
        params={
            "enable_points": True,
            "enable_streak": True,
            "enable_cleanup": True,
        },
        message_id=200,
        reply_to_message_id=199,
        text="签到成功！已连续签到 3 天，当前积分: 100",
        store=store,
    )

    # First run
    with patch.object(ctx, "delete_message", wraps=ctx.delete_message) as spy_delete:
        res1 = await handle_checkin_observer(ctx)
        assert res1 is True
        assert await ctx.storage.get("seen:200") is True
        assert await ctx.storage.get("streak:current") == 3
        assert spy_delete.call_count == 2

    # Second run with same message ID
    with patch.object(ctx, "delete_message", wraps=ctx.delete_message) as spy_delete:
        res2 = await handle_checkin_observer(ctx)
        assert res2 is True
        # Idempotency prevents redundant deletion and state modification
        assert spy_delete.call_count == 0


@pytest.mark.asyncio
async def test_checkin_observer_non_destructive_on_parse_failure(tmp_path):
    """Non-destructive: if parsing fails (no points, streak, or checkin match), does NOT delete messages."""
    store = PluginStore(tmp_path / "storage.db")
    ctx = _make_mock_ctx(
        params={
            "enable_points": True,
            "enable_streak": True,
            "enable_cleanup": True,
            "delay_seconds": 1.0,
        },
        message_id=300,
        reply_to_message_id=299,
        text="今日打卡失败：验证码已过期，请重新获取！",
        store=store,
    )

    with patch.object(ctx, "delete_message", wraps=ctx.delete_message) as spy_delete:
        res = await handle_checkin_observer(ctx)
        assert res is False
        spy_delete.assert_not_called()
        assert await ctx.storage.get("ledger:latest_balance") is None
        assert await ctx.storage.get("seen:300") is None


# ============================================================================
# chat_cleaner Tests
# ============================================================================


@pytest.mark.asyncio
async def test_chat_cleaner_standalone_basic():
    """Validates standalone reactive cleaner deletes bot reply and trigger command after delay."""
    ctx = _make_mock_ctx(
        params={
            "delay_seconds": 3.0,
            "delete_bot_reply": True,
            "delete_trigger_command": True,
        },
        message_id=400,
        reply_to_message_id=399,
        plugin_name="chat_cleaner",
    )

    with (
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch.object(ctx, "delete_message", wraps=ctx.delete_message) as spy_delete,
    ):
        res = await handle_chat_cleaner(ctx)
        assert res is True
        mock_sleep.assert_awaited_once_with(3.0)

        deleted_ids = [
            call.kwargs.get("message_id") for call in spy_delete.call_args_list
        ]
        assert 400 in deleted_ids
        assert 399 in deleted_ids


@pytest.mark.asyncio
async def test_chat_cleaner_missing_reply_to_safely():
    """Validates safe handling when reply_to_message_id is None or missing."""
    ctx = _make_mock_ctx(
        params={
            "delay_seconds": 0.0,
            "delete_bot_reply": True,
            "delete_trigger_command": True,
        },
        message_id=405,
        reply_to_message_id=None,
        plugin_name="chat_cleaner",
    )

    with patch.object(ctx, "delete_message", wraps=ctx.delete_message) as spy_delete:
        res = await handle_chat_cleaner(ctx)
        assert res is True
        # Only bot reply should be attempted for deletion
        deleted_ids = [
            call.kwargs.get("message_id") for call in spy_delete.call_args_list
        ]
        assert deleted_ids == [405]


@pytest.mark.asyncio
async def test_chat_cleaner_handles_message_not_found_safely():
    """Validates that PluginMessageNotFoundError does not cause chat_cleaner to crash."""
    ctx = _make_mock_ctx(
        params={
            "delay_seconds": 0.0,
            "delete_bot_reply": True,
            "delete_trigger_command": True,
        },
        message_id=410,
        reply_to_message_id=409,
        plugin_name="chat_cleaner",
    )

    with patch.object(
        ctx,
        "delete_message",
        AsyncMock(side_effect=PluginMessageNotFoundError("Message expired or deleted")),
    ):
        res = await handle_chat_cleaner(ctx)
        assert res is True


# ============================================================================
# Plugin Registry & Manifest Metadata Tests
# ============================================================================


def test_community_plugins_metadata_and_registry():
    """Validates plugin registration and manifest compliance for checkin_observer and chat_cleaner."""
    base_dir = Path(__file__).resolve().parent.parent / "community_plugins"

    # 1. checkin_observer
    obs_manifest_file = base_dir / "checkin_observer" / "plugin.json"
    assert obs_manifest_file.is_file(), "checkin_observer/plugin.json missing"
    obs_manifest = json.loads(obs_manifest_file.read_text(encoding="utf-8"))
    assert obs_manifest["id"] == "checkin_observer"
    assert obs_manifest["name"] == "签到全景观察与清理卫士"
    assert obs_manifest["version"] == "1.0.0"
    assert obs_manifest["mode"] == "reactive"
    assert obs_manifest["category"] == "helper"
    assert obs_manifest["author"] == "TG-SignPulse"
    assert obs_manifest["context_version"] == 2
    assert obs_manifest["plugin_api"] == "2.0"
    assert obs_manifest["min_app_version"] == "1.9.0"
    assert set(obs_manifest["permissions"]) == {"storage", "telegram_send"}

    # 2. chat_cleaner
    cleaner_manifest_file = base_dir / "chat_cleaner" / "plugin.json"
    assert cleaner_manifest_file.is_file(), "chat_cleaner/plugin.json missing"
    cleaner_manifest = json.loads(cleaner_manifest_file.read_text(encoding="utf-8"))
    assert cleaner_manifest["id"] == "chat_cleaner"
    assert cleaner_manifest["name"] == "通用对话痕迹自动清理助手"
    assert cleaner_manifest["version"] == "1.0.0"
    assert cleaner_manifest["mode"] == "reactive"
    assert cleaner_manifest["category"] == "message"
    assert cleaner_manifest["author"] == "TG-SignPulse"
    assert cleaner_manifest["context_version"] == 2
    assert cleaner_manifest["plugin_api"] == "2.0"
    assert cleaner_manifest["min_app_version"] == "1.9.0"
    assert set(cleaner_manifest["permissions"]) == {"telegram_send"}

    # Registry checks
    assert "checkin_observer" in PluginRegistry._plugins
    assert "chat_cleaner" in PluginRegistry._plugins

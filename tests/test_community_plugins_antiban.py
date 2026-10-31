"""Tests for TG-SignPulse anti-detection community plugins:
typing_simulator, jitter_delay, and auto_read_marker.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pyrogram.enums import ChatAction
from pyrogram.errors import FloodWait

from community_plugins.auto_read_marker.main import (
    handle_auto_read_marker,
)
from community_plugins.jitter_delay.main import (
    handle_jitter_delay,
)

# Import the plugin handlers and metadata from community_plugins
from community_plugins.typing_simulator.main import (
    handle_typing_simulator,
)
from tg_signer.core.plugins import (
    PluginContext,
    PluginFloodWaitError,
    PluginRegistry,
)


def _make_mock_ctx(
    params: dict | None = None,
    chat_id: int = 123456,
    chat_type: str = "private",
) -> PluginContext:
    mock_app = MagicMock()
    mock_app.send_chat_action = AsyncMock(return_value=True)
    mock_app.read_chat_history = AsyncMock(return_value=True)

    msg = MagicMock()
    msg.chat = MagicMock()
    msg.chat.type = chat_type

    ctx = PluginContext(
        app=mock_app,
        chat_id=chat_id,
        message=msg,
        params=dict(params or {}),
        plugin_name="test_antiban",
        context_version=2,
    )
    return ctx


# ============================================================================
# typing_simulator Tests
# ============================================================================


@pytest.mark.asyncio
async def test_typing_simulator_default_behavior():
    """Validates default execution: sends 'typing' action, sleeps, returns True."""
    ctx = _make_mock_ctx()
    with (
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch.object(ctx, "send_chat_action", wraps=ctx.send_chat_action) as spy_action,
    ):
        res = await handle_typing_simulator(ctx)
        assert res is True
        spy_action.assert_awaited_once_with("typing")
        ctx.app.send_chat_action.assert_awaited_once()
        sent_action = ctx.app.send_chat_action.call_args[0][1]
        assert sent_action == ChatAction.TYPING or str(sent_action).lower().endswith(
            "typing"
        )
        mock_sleep.assert_awaited_once()
        # Default duration should be clamped in [0.5, 15.0]
        slept_duration = mock_sleep.call_args[0][0]
        assert 0.5 <= slept_duration <= 15.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "input_duration, expected_clamped",
    [
        (0.1, 0.5),  # Below min clamping threshold (0.5s)
        (0.49, 0.5),  # Just below min clamping threshold
        (16.0, 15.0),  # Above max clamping threshold (15.0s)
        (100.0, 15.0),  # Far above max clamping threshold
        (3.5, 3.5),  # Within valid range
    ],
)
async def test_typing_simulator_duration_clamping(
    input_duration: float, expected_clamped: float
):
    """Validates duration clamping to strict [0.5, 15.0] seconds range."""
    ctx = _make_mock_ctx(
        params={"duration_seconds": input_duration, "randomize": False}
    )
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = await handle_typing_simulator(ctx)
        assert res is True
        mock_sleep.assert_awaited_once_with(expected_clamped)


@pytest.mark.asyncio
async def test_typing_simulator_randomize_within_bounds():
    """Validates randomize=True stays within the clamped bounds [0.5, 15.0]."""
    ctx = _make_mock_ctx(params={"duration_seconds": 0.2, "randomize": True})
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = await handle_typing_simulator(ctx)
        assert res is True
        slept = mock_sleep.call_args[0][0]
        assert 0.5 <= slept <= 15.0


@pytest.mark.asyncio
async def test_typing_simulator_custom_action_type():
    """Validates that custom action_type (e.g. choose_sticker) is passed to ctx.send_chat_action."""
    ctx = _make_mock_ctx(
        params={
            "action_type": "choose_sticker",
            "duration_seconds": 1.0,
            "randomize": False,
        }
    )
    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch.object(ctx, "send_chat_action", wraps=ctx.send_chat_action) as spy_action,
    ):
        res = await handle_typing_simulator(ctx)
        assert res is True
        spy_action.assert_awaited_once_with("choose_sticker")
        sent_action = ctx.app.send_chat_action.call_args[0][1]
        assert sent_action == ChatAction.CHOOSE_STICKER or str(
            sent_action
        ).lower().endswith("choose_sticker")


@pytest.mark.asyncio
async def test_typing_simulator_floodwait_pyrogram_propagation():
    """FloodWait from Pyrogram must propagate and not be swallowed."""
    ctx = _make_mock_ctx()
    ctx.app.send_chat_action.side_effect = FloodWait(value=10)
    with pytest.raises(FloodWait):
        await handle_typing_simulator(ctx)


@pytest.mark.asyncio
async def test_typing_simulator_floodwait_plugin_error_propagation():
    """PluginFloodWaitError must propagate and not be swallowed."""
    ctx = _make_mock_ctx()
    ctx.app.send_chat_action.side_effect = PluginFloodWaitError(seconds=8)
    with pytest.raises(PluginFloodWaitError):
        await handle_typing_simulator(ctx)


@pytest.mark.asyncio
async def test_typing_simulator_general_exception_handled():
    """General network or client exceptions should be handled gracefully and return False."""
    ctx = _make_mock_ctx()
    ctx.app.send_chat_action.side_effect = RuntimeError("Connection dropped")
    res = await handle_typing_simulator(ctx)
    assert res is False


# ============================================================================
# jitter_delay Tests
# ============================================================================


@pytest.mark.asyncio
async def test_jitter_delay_default_behavior():
    """Validates default execution sleeps and returns True."""
    ctx = _make_mock_ctx()
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = await handle_jitter_delay(ctx)
        assert res is True
        mock_sleep.assert_awaited_once()
        slept = mock_sleep.call_args[0][0]
        assert slept >= 0.0


@pytest.mark.asyncio
async def test_jitter_delay_low_high_swap_handling():
    """If min_seconds > max_seconds, they must be swapped so low <= high."""
    ctx = _make_mock_ctx(
        params={"min_seconds": 8.0, "max_seconds": 2.0, "distribution": "uniform"}
    )
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = await handle_jitter_delay(ctx)
        assert res is True
        mock_sleep.assert_awaited_once()
        slept = mock_sleep.call_args[0][0]
        assert 2.0 <= slept <= 8.0


@pytest.mark.asyncio
async def test_jitter_delay_min_clamping_non_negative():
    """Negative seconds must be clamped to 0.0."""
    ctx = _make_mock_ctx(
        params={"min_seconds": -5.0, "max_seconds": -1.0, "distribution": "uniform"}
    )
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = await handle_jitter_delay(ctx)
        assert res is True
        mock_sleep.assert_awaited_once_with(0.0)


@pytest.mark.asyncio
async def test_jitter_delay_uniform_distribution():
    """Uniform distribution yields a value between low and high."""
    ctx = _make_mock_ctx(
        params={"min_seconds": 3.0, "max_seconds": 6.0, "distribution": "uniform"}
    )
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        for _ in range(10):
            res = await handle_jitter_delay(ctx)
            assert res is True
            slept = mock_sleep.call_args[0][0]
            assert 3.0 <= slept <= 6.0


@pytest.mark.asyncio
async def test_jitter_delay_gaussian_distribution():
    """Gaussian distribution values must stay clamped within [low, high]."""
    ctx = _make_mock_ctx(
        params={"min_seconds": 2.0, "max_seconds": 10.0, "distribution": "gaussian"}
    )
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        for _ in range(15):
            res = await handle_jitter_delay(ctx)
            assert res is True
            slept = mock_sleep.call_args[0][0]
            assert 2.0 <= slept <= 10.0


@pytest.mark.asyncio
async def test_jitter_delay_equal_bounds():
    """When min_seconds == max_seconds, slept delay is exactly that value."""
    ctx = _make_mock_ctx(params={"min_seconds": 4.5, "max_seconds": 4.5})
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = await handle_jitter_delay(ctx)
        assert res is True
        mock_sleep.assert_awaited_once_with(4.5)


# ============================================================================
# auto_read_marker Tests
# ============================================================================


@pytest.mark.asyncio
async def test_auto_read_marker_active_success():
    """Active mode: calls ctx.read_chat_history(max_id=0), returns True."""
    ctx = _make_mock_ctx()
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = await handle_auto_read_marker(ctx)
        assert res is True
        ctx.app.read_chat_history.assert_awaited_once_with(ctx.chat_id, max_id=0)
        mock_sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_read_marker_with_delay():
    """With delay_seconds > 0, sleeps before calling read_chat_history."""
    ctx = _make_mock_ctx(params={"delay_seconds": 1.5})
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = await handle_auto_read_marker(ctx)
        assert res is True
        mock_sleep.assert_awaited_once_with(1.5)
        ctx.app.read_chat_history.assert_awaited_once_with(ctx.chat_id, max_id=0)


@pytest.mark.asyncio
async def test_auto_read_marker_private_only_behavior():
    """When private_only=True: executes for private chat, skips for non-private."""
    # 1. Non-private chat (chat_id < 0 or chat_type != 'private')
    group_ctx = _make_mock_ctx(
        params={"private_only": True}, chat_id=-1001234567, chat_type="supergroup"
    )
    res = await handle_auto_read_marker(group_ctx)
    assert res is True
    group_ctx.app.read_chat_history.assert_not_awaited()

    # 2. Private chat (chat_id > 0 and chat_type == 'private')
    private_ctx = _make_mock_ctx(
        params={"private_only": True}, chat_id=1234567, chat_type="private"
    )
    res = await handle_auto_read_marker(private_ctx)
    assert res is True
    private_ctx.app.read_chat_history.assert_awaited_once_with(1234567, max_id=0)


@pytest.mark.asyncio
async def test_auto_read_marker_failure_handled():
    """When read_chat_history fails with general exception, logs and returns False."""
    ctx = _make_mock_ctx()
    ctx.app.read_chat_history.side_effect = RuntimeError("Failed to mark as read")
    res = await handle_auto_read_marker(ctx)
    assert res is False


# ============================================================================
# Plugin Registry & Metadata Tests
# ============================================================================


def test_antiban_plugins_registered():
    """All 3 plugins must be registered in PluginRegistry with mode='active'."""
    expected_plugins = ["typing_simulator", "jitter_delay", "auto_read_marker"]
    base_dir = Path(__file__).resolve().parent.parent / "community_plugins"

    for pid in expected_plugins:
        assert pid in PluginRegistry._plugins, (
            f"Plugin {pid} not registered in PluginRegistry"
        )
        meta = PluginRegistry.get(pid)
        assert meta is not None, f"Metadata for {pid} missing"
        assert meta.mode == "active"
        assert meta.context_version == 2
        assert meta.plugin_api == "2.0"
        assert meta.min_app_version == "1.9.0"

        # Check plugin.json manifest directly
        manifest_file = base_dir / pid / "plugin.json"
        assert manifest_file.is_file(), f"plugin.json missing for {pid}"
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        assert manifest["id"] == pid
        assert manifest["mode"] == "active"
        assert manifest["context_version"] == 2
        assert manifest["plugin_api"] == "2.0"
        assert manifest["min_app_version"] == "1.9.0"

    # Check manifest permissions
    typing_manifest = json.loads(
        (base_dir / "typing_simulator" / "plugin.json").read_text(encoding="utf-8")
    )
    assert typing_manifest["permissions"] == ["telegram_send"]

    jitter_manifest = json.loads(
        (base_dir / "jitter_delay" / "plugin.json").read_text(encoding="utf-8")
    )
    assert jitter_manifest["permissions"] == []

    read_manifest = json.loads(
        (base_dir / "auto_read_marker" / "plugin.json").read_text(encoding="utf-8")
    )
    assert read_manifest["permissions"] == ["telegram_read"]

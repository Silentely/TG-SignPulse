"""Tests for Telegram Mini App Claim plugin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from community_plugins.mini_app_claim.main import handle_mini_app_claim
from tg_signer.core.plugin_storage import PluginStore
from tg_signer.core.plugins import (
    PluginContext,
    PluginFloodWaitError,
    PluginStorageClient,
)


def _make_plugin_ctx(
    params: dict | None = None,
    chat_id: int = -10011223344,
    store: PluginStore | None = None,
) -> PluginContext:
    mock_app = MagicMock()
    ctx = PluginContext(
        app=mock_app,
        chat_id=chat_id,
        message=None,
        params=dict(params or {}),
        plugin_name="mini_app_claim",
        context_version=2,
    )
    if store is not None:
        ctx.storage = PluginStorageClient(
            namespace=f"test:mini_app_claim:{chat_id}",
            store=store,
        )
    return ctx


@pytest.mark.asyncio
async def test_mini_app_claim_success_flow(tmp_path):
    """Test successful mini app claim with verbatim initData passthrough and storage persistence."""
    store = PluginStore(tmp_path / "storage.db")
    ctx = _make_plugin_ctx(
        params={
            "bot_peer": "@example_bot",
            "claim_url": "https://api.example.com/v1/claim",
            "from_bot_menu": True,
        },
        store=store,
    )

    sample_init_data = "query_id=AAH123&user=%7B%22id%22%3A123%7D&auth_date=1731000000&hash=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    ctx.request_web_view = AsyncMock(
        return_value={
            "url": f"https://api.example.com/wv#tgWebAppData={sample_init_data}&tgWebAppVersion=8.0",
            "query_id": "AAH123",
            "init_data_raw": sample_init_data,
        }
    )

    mock_resp = {"code": 0, "message": "claimed", "reward": 50}

    with patch(
        "community_plugins.mini_app_claim.main._perform_http_post",
        return_value=mock_resp,
    ) as mock_post:
        success = await handle_mini_app_claim(ctx)

        assert success is True
        # Verify request_web_view was called with exact arguments
        ctx.request_web_view.assert_awaited_once_with(
            bot_peer="@example_bot",
            from_bot_menu=True,
            platform="android",
        )

        # Verify zero-tampering verbatim passthrough
        mock_post.assert_called_once()
        call_url, call_payload, call_headers = mock_post.call_args[0][:3]
        assert call_url == "https://api.example.com/v1/claim"
        assert call_payload == {"init_data": sample_init_data}
        assert call_headers["Authorization"] == f"tma {sample_init_data}"
        assert call_headers["X-Telegram-Init-Data"] == sample_init_data

        # Verify persistence to storage
        status = await ctx.storage.get("last_claim_status")
        result = await ctx.storage.get("last_claim_result")
        assert status == "success"
        assert result == mock_resp


@pytest.mark.asyncio
async def test_mini_app_claim_flood_wait_exact_seconds(tmp_path):
    """Test FloodWait waits exact seconds returned by Telegram without guessing."""
    store = PluginStore(tmp_path / "storage.db")
    ctx = _make_plugin_ctx(
        params={
            "bot_peer": "@example_bot",
            "claim_url": "https://api.example.com/v1/claim",
            "max_flood_wait": 60,
        },
        store=store,
    )

    sample_init_data = "query_id=AAH456&user=%7B%22id%22%3A456%7D&auth_date=1731000000&hash=abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
    # First call raises FloodWait for 7 seconds, second call succeeds
    ctx.request_web_view = AsyncMock(
        side_effect=[
            PluginFloodWaitError(seconds=7),
            {
                "url": f"https://api.example.com/wv#tgWebAppData={sample_init_data}",
                "init_data_raw": sample_init_data,
            },
        ]
    )

    with (
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch(
            "community_plugins.mini_app_claim.main._perform_http_post",
            return_value={"code": 0},
        ) as mock_post,
    ):
        success = await handle_mini_app_claim(ctx)

        assert success is True
        # Verify slept for exact server seconds (7 seconds), no guessing
        mock_sleep.assert_awaited_once_with(7)
        assert ctx.request_web_view.await_count == 2
        mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_mini_app_claim_flood_wait_exceeds_threshold(tmp_path):
    """Test FloodWait exceeding max threshold raises without retry or sleeping."""
    store = PluginStore(tmp_path / "storage.db")
    ctx = _make_plugin_ctx(
        params={
            "bot_peer": "@example_bot",
            "max_flood_wait": 30,
        },
        store=store,
    )

    ctx.request_web_view = AsyncMock(side_effect=PluginFloodWaitError(seconds=120))

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(PluginFloodWaitError) as exc_info:
            await handle_mini_app_claim(ctx)

        assert exc_info.value.seconds == 120
        mock_sleep.assert_not_called()
        assert ctx.request_web_view.await_count == 1

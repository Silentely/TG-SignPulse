from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

from backend.core.database import get_engine
from backend.services.chatops_bot import TelegramChatOpsWorker
from backend.services.push_notifications import (
    close_shared_http_client,
    send_telegram_bot_message,
)
from backend.utils.proxy import format_proxy_url


def test_format_proxy_url():
    # Empty inputs
    assert format_proxy_url(None) is None
    assert format_proxy_url("") is None
    assert format_proxy_url({}) is None

    # Bare host:port defaults to socks5
    assert format_proxy_url("127.0.0.1:1080") == "socks5://127.0.0.1:1080"

    # Explicit HTTP scheme
    assert format_proxy_url("http://127.0.0.1:7890") == "http://127.0.0.1:7890"

    # Explicit SOCKS5 scheme
    assert format_proxy_url("socks5://127.0.0.1:1080") == "socks5://127.0.0.1:1080"

    # Dict input with credentials and special characters
    p_dict = {
        "scheme": "http",
        "hostname": "proxy.example.com",
        "port": 8080,
        "username": "user@domain",
        "password": "p@ss:word/123",
    }
    formatted = format_proxy_url(p_dict)
    assert formatted is not None
    assert formatted.startswith("http://")
    assert "user%40domain" in formatted
    assert "proxy.example.com:8080" in formatted
    from backend.utils.proxy import build_proxy_dict
    assert build_proxy_dict(formatted) == p_dict


@pytest.mark.asyncio
async def test_send_telegram_bot_message_with_proxy():
    # Test that proxy is formatted and passed to telegram client
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_post_resp)
    mock_client.is_closed = False

    with patch(
        "backend.services.push_notifications._get_shared_telegram_client",
        return_value=mock_client,
    ) as mock_get_client:
        await send_telegram_bot_message(
            bot_token="test_token_123",
            chat_id="999888",
            text="Hello from test",
            proxy="http://127.0.0.1:7890",
        )

        mock_get_client.assert_called_once_with(proxy_url="http://127.0.0.1:7890")
        mock_client.post.assert_awaited_once()
        call_url = mock_client.post.call_args[0][0]
        assert call_url == "https://api.telegram.org/bottest_token_123/sendMessage"
        call_json = mock_client.post.call_args[1]["json"]
        assert call_json["chat_id"] == "999888"
        assert "Hello from test" in call_json["text"]


@pytest.mark.asyncio
async def test_send_telegram_bot_message_auto_resolves_global_proxy():
    # When proxy is not passed, it reads get_global_proxy()
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_post_resp)
    mock_client.is_closed = False

    mock_cfg = MagicMock()
    mock_cfg.get_global_proxy.return_value = "socks5://127.0.0.1:1080"

    with patch("backend.services.config.get_config_service", return_value=mock_cfg), patch(
        "backend.services.push_notifications._get_shared_telegram_client",
        return_value=mock_client,
    ) as mock_get_client:
        await send_telegram_bot_message(
            bot_token="token_abc",
            chat_id="12345",
            text="Test msg",
        )

        mock_get_client.assert_called_once_with(proxy_url="socks5://127.0.0.1:1080")


@pytest.mark.asyncio
async def test_close_shared_http_clients():
    mock_client1 = MagicMock()
    mock_client1.aclose = AsyncMock()
    mock_client1.is_closed = False

    mock_client2 = MagicMock()
    mock_client2.aclose = AsyncMock()
    mock_client2.is_closed = False

    with patch("backend.services.push_notifications._shared_http_client", mock_client1), patch(
        "backend.services.push_notifications._shared_tg_client", mock_client2
    ):
        await close_shared_http_client()
        mock_client1.aclose.assert_awaited_once()
        mock_client2.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_chatops_poll_loop_proxy_propagation():
    worker = TelegramChatOpsWorker()
    worker._running = True

    mock_cfg = MagicMock()
    mock_cfg.get_global_settings.return_value = {
        "telegram_bot_token": "mock_token",
        "telegram_bot_chat_id": "12345",
        "telegram_bot_chatops_enabled": True,
    }
    mock_cfg.get_global_proxy.return_value = "http://127.0.0.1:8888"

    created_proxies = []

    class DummyClient:
        def __init__(self, proxy=None, timeout=None):
            created_proxies.append(proxy)
            self.is_closed = False

        async def get(self, url, params=None):
            worker._running = False
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"result": []}
            return resp

        async def aclose(self):
            self.is_closed = True

    with patch("backend.services.config.get_config_service", return_value=mock_cfg), patch(
        "httpx.AsyncClient", side_effect=DummyClient
    ):
        await worker._poll_loop()

    assert created_proxies == ["http://127.0.0.1:8888"]


def test_sqlite_pragmas():
    engine = get_engine()
    with engine.connect() as conn:
        dialect_name = conn.dialect.name
        if dialect_name == "sqlite":
            journal = conn.execute(text("PRAGMA journal_mode")).scalar()
            assert str(journal).lower() == "wal"
            sync = conn.execute(text("PRAGMA synchronous")).scalar()
            # 1 is NORMAL, 2 is FULL
            assert sync in (1, "1", "NORMAL")
            fk = conn.execute(text("PRAGMA foreign_keys")).scalar()
            # 1 is ON
            assert fk in (1, "1", "ON")

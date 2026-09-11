import pytest
from unittest.mock import AsyncMock, patch
from tg_signer.core.plugins import PluginContext, PluginRegistry


@pytest.mark.asyncio
async def test_webhook_pusher_missing_url():
    from plugins.webhook_pusher.main import webhook_pusher_handler

    logs = []
    ctx = PluginContext(app=None, chat_id=123, params={}, logger=logs.append)
    res = await webhook_pusher_handler(ctx)
    assert res is False
    assert any("未配置" in log or "无效" in log for log in logs)


@pytest.mark.asyncio
async def test_webhook_pusher_invalid_url():
    from plugins.webhook_pusher.main import webhook_pusher_handler

    logs = []
    ctx = PluginContext(app=None, chat_id=123, params={"webhook_url": "ftp://invalid"}, logger=logs.append)
    res = await webhook_pusher_handler(ctx)
    assert res is False
    assert any("http" in log.lower() or "无效" in log for log in logs)


@pytest.mark.asyncio
async def test_webhook_pusher_success():
    from plugins.webhook_pusher.main import webhook_pusher_handler

    logs = []
    ctx = PluginContext(
        app=None,
        chat_id=123456,
        params={"webhook_url": "https://example.com/webhook", "secret_token": "token123", "custom_message": "test run"},
        logger=logs.append,
    )
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.text = "ok"

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await webhook_pusher_handler(ctx)
        assert res is True
        assert any("成功" in log for log in logs)
        assert mock_post.called
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["chat_id"] == 123456
        assert call_kwargs["json"]["custom_message"] == "test run"
        assert call_kwargs["headers"]["Authorization"] == "Bearer token123"


def test_webhook_pusher_metadata():
    import plugins.webhook_pusher.main
    meta = PluginRegistry.get("webhook_pusher")
    assert meta is not None
    assert meta.mode == "active"
    assert meta.version == "1.0.0"
    assert meta.updated_at == "2026-09-11"
    assert meta.author == "TG-SignPulse Team"
    assert len(meta.params_schema) >= 2

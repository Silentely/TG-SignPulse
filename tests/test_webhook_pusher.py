from unittest.mock import AsyncMock, patch

import pytest

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
async def test_webhook_pusher_private_url_blocked():
    """SSRF 防护：私有/回环地址必须被拒绝且不发起请求。"""
    from plugins.webhook_pusher.main import webhook_pusher_handler

    logs = []
    ctx = PluginContext(
        app=None,
        chat_id=123,
        params={"webhook_url": "http://127.0.0.1:9000/hook"},
        logger=logs.append,
    )
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        res = await webhook_pusher_handler(ctx)
    assert res is False
    assert not mock_post.called
    assert any("禁止请求私有或内网地址" in log for log in logs)


@pytest.mark.asyncio
async def test_webhook_pusher_unresolvable_host_blocked():
    """SSRF 防护：主机不可解析时拒绝执行且不发起请求。"""
    from plugins.webhook_pusher.main import webhook_pusher_handler

    logs = []
    ctx = PluginContext(
        app=None,
        chat_id=123,
        params={"webhook_url": "https://nonexistent.invalid/webhook"},
        logger=logs.append,
    )
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        res = await webhook_pusher_handler(ctx)
    assert res is False
    assert not mock_post.called


@pytest.mark.asyncio
async def test_webhook_pusher_url_credentials_not_logged():
    """URL 内嵌凭据不得原样进入日志。"""
    from plugins.webhook_pusher.main import webhook_pusher_handler

    logs = []
    ctx = PluginContext(
        app=None,
        chat_id=123,
        params={"webhook_url": "http://user:secret123@127.0.0.1/hook"},
        logger=logs.append,
    )
    res = await webhook_pusher_handler(ctx)
    assert res is False
    joined = "\n".join(logs)
    assert "secret123" not in joined
    assert "user" not in joined


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

    # 钉扎 IP 解析结果打桩：测试环境不依赖真实 DNS
    with patch(
        "plugins.webhook_pusher.main.validate_public_http_url",
        return_value=("93.184.216.34", "example.com"),
    ), patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await webhook_pusher_handler(ctx)
        assert res is True
        assert any("成功" in log for log in logs)
        assert mock_post.called
        call_args = mock_post.call_args
        # 请求应发往钉扎 IP，并以原主机名完成 SNI 与 Host 头
        assert call_args.args[0] == "https://93.184.216.34/webhook"
        assert call_args.kwargs["extensions"] == {"sni_hostname": "example.com"}
        call_kwargs = call_args.kwargs
        assert call_kwargs["json"]["chat_id"] == 123456
        assert call_kwargs["json"]["custom_message"] == "test run"
        assert call_kwargs["headers"]["Authorization"] == "Bearer token123"
        assert call_kwargs["headers"]["Host"] == "example.com"


@pytest.mark.asyncio
async def test_webhook_pusher_http_error_status():
    """非 2xx 响应判定为推送失败。"""
    from plugins.webhook_pusher.main import webhook_pusher_handler

    logs = []
    ctx = PluginContext(
        app=None,
        chat_id=1,
        params={"webhook_url": "https://example.com/webhook"},
        logger=logs.append,
    )
    mock_resp = AsyncMock()
    mock_resp.status_code = 500
    mock_resp.text = "boom"

    with patch(
        "plugins.webhook_pusher.main.validate_public_http_url",
        return_value=("93.184.216.34", "example.com"),
    ), patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await webhook_pusher_handler(ctx)
    assert res is False
    assert any("500" in log for log in logs)


@pytest.mark.asyncio
async def test_webhook_pusher_network_exception():
    """网络异常判定为推送失败且不向外抛出。"""
    from plugins.webhook_pusher.main import webhook_pusher_handler

    logs = []
    ctx = PluginContext(
        app=None,
        chat_id=1,
        params={"webhook_url": "https://example.com/webhook"},
        logger=logs.append,
    )
    with patch(
        "plugins.webhook_pusher.main.validate_public_http_url",
        return_value=("93.184.216.34", "example.com"),
    ), patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=OSError("network down")):
        res = await webhook_pusher_handler(ctx)
    assert res is False
    assert any("异常" in log for log in logs)


def test_webhook_pusher_metadata():
    import plugins.webhook_pusher.main as webhook_module

    meta = PluginRegistry.get("webhook_pusher")
    assert meta is not None
    assert meta.mode == "active"
    assert meta.version == "1.0.0"
    assert meta.updated_at == "2026-09-11"
    assert meta.author == "TG-SignPulse Team"
    assert meta.author == webhook_module.AUTHOR
    assert len(meta.params_schema) >= 2

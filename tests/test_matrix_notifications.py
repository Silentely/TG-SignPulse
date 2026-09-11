import pytest
from unittest.mock import AsyncMock, patch
from backend.services.push_notifications import (
    send_wecom_message,
    send_feishu_message,
    send_dingtalk_message,
    send_discord_message,
    dispatch_matrix_notification,
)


@pytest.mark.asyncio
async def test_send_wecom_message():
    with patch("backend.services.push_notifications._http_post_retry_once", new_callable=AsyncMock) as mock_post:
        await send_wecom_message("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx", "Test Title", "Test Text")
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["channel"] == "WeCom"
        assert "markdown" in call_kwargs["json_body"]
        assert "### Test Title" in call_kwargs["json_body"]["markdown"]["content"]


@pytest.mark.asyncio
async def test_send_feishu_message():
    with patch("backend.services.push_notifications._http_post_retry_once", new_callable=AsyncMock) as mock_post:
        await send_feishu_message("https://open.feishu.cn/open-apis/bot/v2/hook/xxx", "Feishu Title", "Feishu Text")
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["channel"] == "Feishu"
        assert call_kwargs["json_body"]["msg_type"] == "interactive"


@pytest.mark.asyncio
async def test_send_dingtalk_message():
    with patch("backend.services.push_notifications._http_post_retry_once", new_callable=AsyncMock) as mock_post:
        await send_dingtalk_message("https://oapi.dingtalk.com/robot/send?access_token=xxx", "Ding Title", "Ding Text")
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["channel"] == "DingTalk"
        assert call_kwargs["json_body"]["markdown"]["title"] == "Ding Title"


@pytest.mark.asyncio
async def test_send_discord_message():
    with patch("backend.services.push_notifications._http_post_retry_once", new_callable=AsyncMock) as mock_post:
        await send_discord_message("https://discord.com/api/webhooks/xxx/yyy", "Discord Title", "Discord Text")
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["channel"] == "Discord"
        assert call_kwargs["json_body"]["embeds"][0]["title"] == "Discord Title"


@pytest.mark.asyncio
async def test_dispatch_matrix_notification():
    settings = {
        "wecom_webhook_url": "https://qyapi.weixin.qq.com/webhook",
        "feishu_webhook_url": "https://open.feishu.cn/webhook",
        "dingtalk_webhook_url": "https://oapi.dingtalk.com/webhook",
        "discord_webhook_url": "https://discord.com/webhook",
    }
    with patch("backend.services.push_notifications.send_wecom_message", new_callable=AsyncMock) as mock_wecom, \
         patch("backend.services.push_notifications.send_feishu_message", new_callable=AsyncMock) as mock_feishu, \
         patch("backend.services.push_notifications.send_dingtalk_message", new_callable=AsyncMock) as mock_ding, \
         patch("backend.services.push_notifications.send_discord_message", new_callable=AsyncMock) as mock_discord:

        await dispatch_matrix_notification(
            settings,
            title="Matrix Notification Test",
            fields=[("Account", "Acc1"), ("Task", "Task1")],
            footer="Done",
        )

        mock_wecom.assert_called_once()
        mock_feishu.assert_called_once()
        mock_ding.assert_called_once()
        mock_discord.assert_called_once()

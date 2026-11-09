from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.config_mixins import AIConfigMixin


class DummyService(AIConfigMixin):
    def __init__(self, config):
        self._config = config

    def get_ai_config(self):
        return self._config


class TestCloudflareConfigMixin:
    @pytest.mark.asyncio
    async def test_cloudflare_connection_success_without_openai_client(self):
        service = DummyService(
            {
                "api_key": "fake-key",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/fake-acc/ai",
                "model": "@cf/meta/llama-3.2-11b-vision-instruct",
            }
        )

        mock_post_result = {
            "success": True,
            "result": {"response": "test ok"},
        }

        with (
            patch("openai.AsyncOpenAI") as mock_openai,
            patch(
                "tg_signer.ai_tools.AITools._cloudflare_post", new_callable=AsyncMock
            ) as mock_post,
        ):
            mock_post.return_value = mock_post_result

            res = await service.test_ai_connection()
            assert res["success"] is True
            assert "Cloudflare 响应: test ok" in res["message"]
            assert res["model_used"] == "@cf/meta/llama-3.2-11b-vision-instruct"
            mock_openai.assert_not_called()
            assert mock_post.await_count == 1

    @pytest.mark.asyncio
    async def test_cloudflare_connection_detects_via_model_prefix_alone(self):
        # Even if base_url is not CF, @cf/ model should route to Cloudflare logic
        service = DummyService(
            {
                "api_key": "fake-key",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/custom-acc/ai",
                "model": "@cf/meta/llama-3.2-11b-vision-instruct",
            }
        )

        mock_post_result = {
            "success": True,
            "result": {"description": ["hello from cloudflare"]},
        }

        with (
            patch("openai.AsyncOpenAI") as mock_openai,
            patch(
                "tg_signer.ai_tools.AITools._cloudflare_post", new_callable=AsyncMock
            ) as mock_post,
        ):
            mock_post.return_value = mock_post_result

            res = await service.test_ai_connection()
            assert res["success"] is True
            assert "Cloudflare 响应: hello from cloudflare" in res["message"]
            assert res["model_used"] == "@cf/meta/llama-3.2-11b-vision-instruct"
            mock_openai.assert_not_called()

    @pytest.mark.asyncio
    async def test_cloudflare_connection_failure_returns_failure_dict(self):
        service = DummyService(
            {
                "api_key": "fake-key",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/fake-acc/ai",
                "model": "@cf/meta/llama-3.2-11b-vision-instruct",
            }
        )

        with patch(
            "tg_signer.ai_tools.AITools._cloudflare_post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.side_effect = RuntimeError(
                "Cloudflare API error 401: Unauthorized"
            )

            res = await service.test_ai_connection()
            assert res["success"] is False
            assert "连接失败: Cloudflare API error 401: Unauthorized" in res["message"]

    @pytest.mark.asyncio
    async def test_openai_model_still_routes_to_openai_client(self):
        service = DummyService(
            {
                "api_key": "fake-key",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-5-nano",
            }
        )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="test ok"))]

        with patch("openai.AsyncOpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_openai.return_value = mock_client

            res = await service.test_ai_connection()
            assert res["success"] is True
            assert "模型响应: test ok" in res["message"]
            assert res["model_used"] == "gpt-5-nano"
            mock_openai.assert_called_once()

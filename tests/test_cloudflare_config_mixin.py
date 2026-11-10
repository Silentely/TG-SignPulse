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
            "result": {"answer": "test ok"},
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

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "invalid_body",
        [
            {},  # ① 空 body
            {"result": {}},  # ② result 为空 dict
            {"result": {"answer": "   "}},  # ③ answer 为空字符串
        ],
    )
    async def test_cloudflare_connection_detects_empty_answer_as_failure(
        self, invalid_body
    ):
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
            mock_post.return_value = invalid_body
            res = await service.test_ai_connection()
            assert res["success"] is False
            assert "连接失败" in res["message"]

    @pytest.mark.asyncio
    async def test_cloudflare_connection_sanitizes_token_in_error_message(self):
        full_token = "secret-token-abcdef123456"
        service = DummyService(
            {
                "api_key": full_token,
                "base_url": "https://api.cloudflare.com/client/v4/accounts/fake-acc/ai",
                "model": "@cf/meta/llama-3.2-11b-vision-instruct",
            }
        )
        with patch(
            "tg_signer.ai_tools.AITools._cloudflare_post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.side_effect = RuntimeError(
                f"Unauthorized with Bearer {full_token} on remote"
            )
            res = await service.test_ai_connection()
            assert res["success"] is False
            assert full_token not in res["message"]
            assert "secr***" in res["message"]

    @pytest.mark.asyncio
    async def test_tiny_png_is_valid_1x1_and_connectivity_succeeds(self):
        """B2 验收：断言 TINY_1X1_PNG 为合法 1x1 PNG（标准库可解析且 CRC 校验正确），且探测成功。"""
        import struct
        import zlib

        from backend.services.config_mixins import TINY_1X1_PNG

        assert TINY_1X1_PNG.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(TINY_1X1_PNG) >= 24
        pos = 8
        length, chunk_type = struct.unpack(">I4s", TINY_1X1_PNG[pos : pos + 8])
        assert chunk_type == b"IHDR"
        width, height = struct.unpack(">II", TINY_1X1_PNG[pos + 8 : pos + 16])
        assert width == 1 and height == 1

        ihdr_data = TINY_1X1_PNG[pos + 4 : pos + 8 + length]
        expected_crc = struct.unpack(
            ">I", TINY_1X1_PNG[pos + 8 + length : pos + 12 + length]
        )[0]
        actual_crc = zlib.crc32(ihdr_data)
        assert actual_crc == expected_crc

        service = DummyService(
            {
                "api_key": "fake-key",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/fake-acc/ai",
                "model": "@cf/meta/llama-3.2-11b-vision-instruct",
            }
        )
        mock_post_result = {
            "success": True,
            "result": {"answer": "test ok"},
        }
        with patch(
            "tg_signer.ai_tools.AITools._cloudflare_post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = mock_post_result
            res = await service.test_ai_connection()
            assert res["success"] is True
            assert "Cloudflare 响应: test ok" in res["message"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "scenario",
        ["success_echo", "exception_cause_chain", "api_error_response"],
    )
    async def test_cloudflare_connection_masks_token_across_all_entrypoints(
        self, scenario
    ):
        """B3 验收：覆盖成功回显、异常 __cause__ 链、API 错误响应 3 个入口，断言完整 token 绝不泄露。"""
        full_token = "secret-token-abcdef123456"
        service = DummyService(
            {
                "api_key": full_token,
                "base_url": "https://api.cloudflare.com/client/v4/accounts/fake-acc/ai",
                "model": "@cf/meta/llama-3.2-11b-vision-instruct",
            }
        )
        with patch(
            "tg_signer.ai_tools.AITools._cloudflare_post", new_callable=AsyncMock
        ) as mock_post:
            if scenario == "success_echo":
                mock_post.return_value = {
                    "success": True,
                    "result": {"answer": f"Echoing secret token {full_token}"},
                }
            elif scenario == "exception_cause_chain":
                exc = RuntimeError("Top level vision failure")
                exc.__cause__ = ValueError(f"Chained header Bearer {full_token}")
                mock_post.side_effect = exc
            elif scenario == "api_error_response":
                mock_post.side_effect = RuntimeError(
                    f"Cloudflare status 401: token={full_token} unauthorized"
                )

            res = await service.test_ai_connection()
            assert full_token not in res["message"]
            if scenario == "success_echo":
                assert res["success"] is True
                assert "secr***" in res["message"]
            else:
                assert res["success"] is False
                assert "secr***" in res["message"]

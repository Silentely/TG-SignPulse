from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from tg_signer.ai_tools import (
    AITools,
    _CloudflareAPIError,
    _RetryableAIResponseError,
    is_cloudflare_vision,
)


class TestCloudflareVisionDetection:
    def test_model_prefix_detection(self):
        tools = AITools({"api_key": "fake-key", "base_url": "https://example.com/v1"})
        assert (
            tools._is_cloudflare_vision("@cf/meta/llama-3.2-11b-vision-instruct")
            is True
        )
        assert tools._is_cloudflare_vision("@cf/other-model") is True
        assert tools._is_cloudflare_vision("gpt-4o") is False
        assert is_cloudflare_vision("@cf/meta/model") is True
        assert is_cloudflare_vision("gpt-5-nano") is False

    def test_base_url_detection(self):
        cf_url = "https://api.cloudflare.com/client/v4/accounts/acc12345/ai"
        cf_url_trailing = "https://api.cloudflare.com/client/v4/accounts/acc12345/ai/"
        cf_url_run = (
            "https://api.cloudflare.com/client/v4/accounts/acc12345/ai/run/@cf/meta"
        )
        non_cf_url = "https://api.openai.com/v1"
        invalid_cf_url = "https://api.cloudflare.com/client/v4/accounts//ai"

        tools = AITools({"api_key": "fake-key", "base_url": cf_url})
        assert tools._is_cloudflare_vision("custom-vision-model") is True

        tools_trailing = AITools({"api_key": "fake-key", "base_url": cf_url_trailing})
        assert tools_trailing._is_cloudflare_vision() is True

        assert is_cloudflare_vision(base_url=cf_url) is True
        assert is_cloudflare_vision(base_url=cf_url_trailing) is True
        assert is_cloudflare_vision(base_url=cf_url_run) is True
        assert is_cloudflare_vision(base_url=non_cf_url) is False
        assert is_cloudflare_vision(base_url=invalid_cf_url) is False


class TestCloudflareUrlConstruction:
    def test_cloudflare_run_url(self):
        tools = AITools(
            {
                "api_key": "fake-key",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/acc12345/ai",
            }
        )
        url = tools._cloudflare_run_url("@cf/meta/llama-3.2-11b-vision-instruct")
        assert (
            url
            == "https://api.cloudflare.com/client/v4/accounts/acc12345/ai/run/@cf/meta/llama-3.2-11b-vision-instruct"
        )

    def test_cloudflare_run_url_without_ai_suffix(self):
        tools = AITools(
            {
                "api_key": "fake-key",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/acc12345",
            }
        )
        url = tools._cloudflare_run_url("@cf/meta/llama-3.2-11b-vision-instruct")
        assert (
            url
            == "https://api.cloudflare.com/client/v4/accounts/acc12345/ai/run/@cf/meta/llama-3.2-11b-vision-instruct"
        )

    def test_cloudflare_run_url_missing_base_url_raises(self):
        tools = AITools({"api_key": "fake-key"})
        with pytest.raises(ValueError, match="base_url"):
            tools._cloudflare_run_url("@cf/meta/llama-3.2-11b-vision-instruct")


class TestCloudflarePostAndUnwrap:
    @pytest.mark.asyncio
    async def test_cloudflare_post_success(self):
        tools = AITools(
            {
                "api_key": "test-bearer-token",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/acc12345/ai",
            }
        )

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "result": {"answer": "motorcycle"},
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            body = await tools._cloudflare_post(
                "https://api.cloudflare.com/client/v4/accounts/acc12345/ai/run/model",
                {"task": "query"},
            )
            assert body["success"] is True
            assert body["result"]["answer"] == "motorcycle"

            # Check Authorization header
            call_kwargs = mock_post.call_args.kwargs
            assert call_kwargs["headers"]["Authorization"] == "Bearer test-bearer-token"

    @pytest.mark.asyncio
    async def test_cloudflare_post_http_4xx_raises_cloudflare_api_error(self):
        tools = AITools(
            {
                "api_key": "test-token",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/acc12345/ai",
            }
        )

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.text = "Bad Request: invalid payload"

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            with pytest.raises(_CloudflareAPIError) as exc_info:
                await tools._cloudflare_post(
                    "https://api.cloudflare.com/client/v4/accounts/acc12345/ai/run/model",
                    {},
                )
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_cloudflare_post_invalid_json_raises_retryable_error(self):
        tools = AITools(
            {
                "api_key": "test-token",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/acc12345/ai",
            }
        )

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.text = "<html>502 Bad Gateway</html>"
        mock_response.json.side_effect = ValueError("Invalid JSON")

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            with pytest.raises(_RetryableAIResponseError):
                await tools._cloudflare_post(
                    "https://api.cloudflare.com/client/v4/accounts/acc12345/ai/run/model",
                    {},
                )

    @pytest.mark.asyncio
    async def test_cloudflare_post_success_false_raises_retryable_error(self):
        tools = AITools(
            {
                "api_key": "test-token",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/acc12345/ai",
            }
        )

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": False,
            "errors": [{"code": 1000, "message": "Internal error"}],
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            with pytest.raises(_RetryableAIResponseError, match="success is False"):
                await tools._cloudflare_post(
                    "https://api.cloudflare.com/client/v4/accounts/acc12345/ai/run/model",
                    {},
                )

    def test_unwrap_cloudflare_result(self):
        assert AITools._unwrap_cloudflare_result({"result": {"answer": "cat"}}) == {
            "answer": "cat"
        }
        assert AITools._unwrap_cloudflare_result(
            {"result": {"result": {"answer": "cat"}}}
        ) == {"answer": "cat"}
        assert AITools._unwrap_cloudflare_result(
            {"result": {"description": ["dog"]}}
        ) == {"description": ["dog"]}
        assert AITools._unwrap_cloudflare_result({"answer": "fox"}) == {"answer": "fox"}


class TestCloudflareVisionQuery:
    @pytest.mark.asyncio
    async def test_vision_query_request_payload_and_description_unpacking(self):
        tools = AITools(
            {
                "api_key": "fake-key",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/acc12345/ai",
            }
        )

        fake_image = b"fake-jpeg-bytes"
        expected_url = tools._format_image_url(fake_image)

        async def fake_post(url, payload):
            assert payload["task"] == "query"
            assert payload["image"] == expected_url
            assert payload["question"] == "图中是什么？"
            assert payload["reasoning"] is False
            assert payload["stream"] is False
            assert payload["temperature"] == 0.1
            assert payload["max_tokens"] == 128
            return {"success": True, "result": {"description": ["  motorcycle  "]}}

        with patch.object(tools, "_cloudflare_post", side_effect=fake_post):
            answer = await tools._cloudflare_vision_query(
                fake_image,
                "图中是什么？",
                model="@cf/meta/llama-3.2-11b-vision-instruct",
                max_tokens=128,
                temperature=0.1,
            )
            assert answer == "motorcycle"

    @pytest.mark.asyncio
    async def test_vision_query_fallback_to_answer(self):
        tools = AITools(
            {
                "api_key": "fake-key",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/acc12345/ai",
            }
        )

        async def fake_post_empty_desc(url, payload):
            return {"success": True, "result": {"description": [], "answer": "router"}}

        with patch.object(tools, "_cloudflare_post", side_effect=fake_post_empty_desc):
            answer = await tools._cloudflare_vision_query(
                b"img",
                "question",
                model="@cf/meta/llama-3.2-11b-vision-instruct",
                max_tokens=256,
                temperature=0.1,
            )
            assert answer == "router"

    @pytest.mark.asyncio
    async def test_vision_query_empty_answer_raises_retryable_error(self):
        tools = AITools(
            {
                "api_key": "fake-key",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/acc12345/ai",
            }
        )

        async def fake_post_none(url, payload):
            return {"success": True, "result": {"description": [""], "answer": ""}}

        with patch.object(tools, "_cloudflare_post", side_effect=fake_post_none):
            with pytest.raises(_RetryableAIResponseError, match="empty answer"):
                await tools._cloudflare_vision_query(
                    b"img",
                    "question",
                    model="@cf/meta/llama-3.2-11b-vision-instruct",
                    max_tokens=256,
                    temperature=0.1,
                )


class TestCloudflareRetryLogic:
    @pytest.mark.asyncio
    async def test_retries_on_retryable_error_until_success(self):
        tools = AITools(
            {
                "api_key": "fake-key",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/acc12345/ai",
            }
        )

        calls = 0

        async def mock_query(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise _RetryableAIResponseError("Temporary empty result")
            return "motorcycle"

        with (
            patch.object(tools, "_vision_retry_attempts", return_value=3),
            patch.object(tools, "_vision_retry_delay", return_value=0.01),
            patch.object(tools, "_cloudflare_vision_query", side_effect=mock_query),
        ):
            answer = await tools._call_cloudflare_vision_with_retries(
                b"img",
                "question",
                model="@cf/meta/llama-3.2-11b-vision-instruct",
            )
            assert answer == "motorcycle"
            assert calls == 2

    @pytest.mark.asyncio
    async def test_retries_on_transient_http_error(self):
        tools = AITools(
            {
                "api_key": "fake-key",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/acc12345/ai",
            }
        )

        calls = 0

        async def mock_query(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise _CloudflareAPIError("Rate limited", status_code=429)
            return "car"

        with (
            patch.object(tools, "_vision_retry_attempts", return_value=2),
            patch.object(tools, "_vision_retry_delay", return_value=0.01),
            patch.object(tools, "_cloudflare_vision_query", side_effect=mock_query),
        ):
            answer = await tools._call_cloudflare_vision_with_retries(
                b"img",
                "question",
                model="@cf/meta/llama-3.2-11b-vision-instruct",
            )
            assert answer == "car"
            assert calls == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_http_400_error(self):
        tools = AITools(
            {
                "api_key": "fake-key",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/acc12345/ai",
            }
        )

        calls = 0

        async def mock_query(*args, **kwargs):
            nonlocal calls
            calls += 1
            raise _CloudflareAPIError("Bad Request: invalid model", status_code=400)

        with (
            patch.object(tools, "_vision_retry_attempts", return_value=3),
            patch.object(tools, "_cloudflare_vision_query", side_effect=mock_query),
        ):
            with pytest.raises(_CloudflareAPIError) as exc_info:
                await tools._call_cloudflare_vision_with_retries(
                    b"img",
                    "question",
                    model="@cf/meta/llama-3.2-11b-vision-instruct",
                )
            assert exc_info.value.status_code == 400
            assert calls == 1


class TestCloudflareVisionFullIntegration:
    @pytest.mark.asyncio
    async def test_choose_option_by_image_with_cloudflare_model(self):
        tools = AITools(
            {
                "api_key": "fake-key",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/acc12345/ai",
                "model": "@cf/meta/llama-3.2-11b-vision-instruct",
            }
        )

        options = [(1, "摩托车"), (2, "汽车"), (3, "飞机")]

        with patch.object(
            tools, "_call_cloudflare_vision_with_retries", new_callable=AsyncMock
        ) as mock_call:
            mock_call.return_value = "motorcycle"

            idx = await tools.choose_option_by_image(
                image=b"fake-image-bytes",
                query="请选择图中的物体",
                options=options,
            )
            # "motorcycle" matches "摩托车" (index 1) via Task 3's bilingual mapping
            assert idx == 1
            assert mock_call.await_count == 1

    @pytest.mark.asyncio
    async def test_vision_query_prioritizes_answer_over_description(self):
        tools = AITools(
            {
                "api_key": "fake-key",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/acc12345/ai",
            }
        )

        async def fake_post_both(url, payload):
            return {
                "success": True,
                "result": {
                    "answer": "answer_first",
                    "description": ["description_fallback"],
                },
            }

        with patch.object(tools, "_cloudflare_post", side_effect=fake_post_both):
            answer = await tools._cloudflare_vision_query(
                b"img",
                "question",
                model="@cf/meta/llama-3.2-11b-vision-instruct",
            )
            assert answer == "answer_first"

    @pytest.mark.asyncio
    async def test_cloudflare_post_sanitizes_token_in_error_and_log(self, caplog):
        full_token = "secret-cf-token-12345678"
        tools = AITools(
            {
                "api_key": full_token,
                "base_url": "https://api.cloudflare.com/client/v4/accounts/acc12345/ai",
            }
        )

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 401
        mock_resp.text = f"Invalid token {full_token} supplied in header"

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            with pytest.raises(_CloudflareAPIError) as exc_info:
                await tools._cloudflare_post(
                    "https://api.cloudflare.com/client/v4/accounts/acc12345/ai/run/model",
                    {"prompt": "test"},
                )
            assert full_token not in str(exc_info.value)
            assert "secr***" in str(exc_info.value)

            for record in caplog.records:
                assert full_token not in record.message

    @pytest.mark.asyncio
    async def test_cloudflare_translation_cache_class_level_sharing(self):
        tools1 = AITools(
            {
                "api_key": "fake-key",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/acc12345/ai",
            }
        )
        tools2 = AITools(
            {
                "api_key": "fake-key-2",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/acc12345/ai",
            }
        )

        AITools._cloudflare_translation_cache.clear()
        initial_size = len(AITools._cloudflare_translation_cache)

        post_calls = 0

        async def fake_post(url, payload):
            nonlocal post_calls
            post_calls += 1
            return {
                "success": True,
                "result": {"translated_text": "electric drill"},
            }

        with patch.object(AITools, "_cloudflare_post", side_effect=fake_post):
            res1 = await tools1._cloudflare_translate_text("电钻工具")
            assert res1 == "electric drill"
            assert post_calls == 1
            assert len(AITools._cloudflare_translation_cache) == initial_size + 1
            assert AITools._cloudflare_translation_cache["电钻工具"] == "electric drill"

            res2 = await tools2._cloudflare_translate_text("电钻工具")
            assert res2 == "electric drill"
            assert post_calls == 1

    @pytest.mark.asyncio
    async def test_cloudflare_production_option_resolution_translates_and_caches(
        self,
    ):
        AITools._cloudflare_translation_cache.clear()

        tools = AITools(
            {
                "api_key": "fake-key",
                "base_url": "https://api.cloudflare.com/client/v4/accounts/acc12345/ai",
                "model": "@cf/meta/llama-3.2-11b-vision-instruct",
            }
        )

        options = [(0, "汽车"), (1, "新设备无人机")]
        unknown_word = "新设备无人机"

        post_calls = []

        async def fake_post(url: str, payload: dict):
            post_calls.append((url, payload))
            if "@cf/meta/m2m100-1.2b" in url:
                return {
                    "success": True,
                    "result": {"translated_text": "new drone device"},
                }
            return {
                "success": True,
                "result": {"answer": "drone"},
            }

        with patch.object(tools, "_cloudflare_post", side_effect=fake_post):
            # 第一次调用完整解析入口
            idx1 = await tools.choose_option_by_image(
                image=b"\x89PNG\r\n\x1a\nfake",
                query="哪个是无人机？",
                options=options,
            )
            assert idx1 == 1
            # 断言缓存已写入
            assert unknown_word in AITools._cloudflare_translation_cache
            assert (
                AITools._cloudflare_translation_cache[unknown_word]
                == "new drone device"
            )

            # 统计翻译请求次数
            trans_calls_1 = [c for c in post_calls if "@cf/meta/m2m100-1.2b" in c[0]]
            assert len(trans_calls_1) == 1

            # 第二次相同输入调用完整解析入口
            idx2 = await tools.choose_option_by_image(
                image=b"\x89PNG\r\n\x1a\nfake",
                query="哪个是无人机？",
                options=options,
            )
            assert idx2 == 1

            # 第二次命中缓存，底层翻译接口没有发起新的请求（总次数仍然为 1）
            trans_calls_2 = [c for c in post_calls if "@cf/meta/m2m100-1.2b" in c[0]]
            assert len(trans_calls_2) == 1

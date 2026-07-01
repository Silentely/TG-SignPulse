import os
import unittest
from io import BytesIO
from types import SimpleNamespace

from PIL import Image

from tg_signer.ai_tools import AITools
from tg_signer.core import _is_callback_confirmation_unavailable


class AIToolsOptionParsingTest(unittest.TestCase):
    def setUp(self):
        self.options = [(1, "social"), (2, "shopping"), (3, "lipstick"), (4, "mask")]

    def test_coerce_option_index_accepts_list_response(self):
        self.assertEqual(AITools._coerce_option_index([{"option": 4}], self.options), 4)

    def test_coerce_option_index_accepts_answer_text(self):
        self.assertEqual(AITools._coerce_option_index({"answer": "mask"}, self.options), 4)

    def test_coerce_option_indexes_accepts_list_payload(self):
        self.assertEqual(AITools._coerce_option_indexes([{"options": [4]}], self.options), [4])

    def test_coerce_option_indexes_accepts_text_payload(self):
        self.assertEqual(AITools._coerce_option_indexes({"answer": "mask"}, self.options), [4])

    def test_coerce_option_index_rejects_unknown_response(self):
        with self.assertRaises(ValueError):
            AITools._coerce_option_index({"reason": "no option"}, self.options)

    def test_extract_relevant_query_prefers_question_line(self):
        query = (
            "请在 30 秒内点击图中事物的按钮以完成签到\n\n"
            "每天只有一次机会, 失败或者过期当天不可重试"
        )
        self.assertEqual(
            AITools._extract_relevant_query(query),
            "请在 30 秒内点击图中事物的按钮以完成签到",
        )

    def test_prepare_vision_image_resizes_large_input(self):
        image = Image.new("RGB", (1600, 1200), "white")
        for x in range(420, 1180):
            for y in range(260, 940):
                image.putpixel((x, y), (20, 20, 20))

        buffer = BytesIO()
        image.save(buffer, format="PNG")

        prepared = AITools._prepare_vision_image(buffer.getvalue())
        with Image.open(BytesIO(prepared)) as prepared_image:
            self.assertLessEqual(max(prepared_image.size), 640)
            self.assertLess(prepared_image.width, 1600)
            self.assertLess(prepared_image.height, 1200)


if __name__ == "__main__":
    unittest.main()


class CallbackFallbackTest(unittest.TestCase):
    def test_channel_invalid_is_treated_as_confirmation_fallback(self):
        self.assertTrue(
            _is_callback_confirmation_unavailable(
                RuntimeError("Telegram says: [400 CHANNEL_INVALID] - invalid channel")
            )
        )

    def test_unrelated_bad_request_is_not_treated_as_confirmation_fallback(self):
        self.assertFalse(
            _is_callback_confirmation_unavailable(
                RuntimeError("Telegram says: [400 MESSAGE_NOT_MODIFIED]")
            )
        )


class _FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class AIToolsJsonFallbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_choose_options_by_image_retries_without_json_mode(self):
        fake_completions = _FakeCompletions(
            [
                RuntimeError("Error code: 403 - {'message': 'openai_error', 'code': 'bad_response_status_code', 'detail': 'response_format json_object unsupported'}"),
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content='{"options":[2]}')
                        )
                    ]
                ),
            ]
        )
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=fake_completions)
        )
        tools = AITools({"api_key": "test", "model": "gpt-4o"})
        tools.client = fake_client

        result = await tools.choose_options_by_image(
            b"fake-image",
            "Choose the correct option",
            [(1, "apple"), (2, "banana")],
        )

        self.assertEqual(result, [2])
        self.assertIn("response_format", fake_completions.calls[0])
        self.assertNotIn("response_format", fake_completions.calls[1])


class TransientErrorRetryTest(unittest.TestCase):
    """AI 视觉瞬时错误重试基础设施测试。"""

    def test_extracts_status_code_from_exception_attribute(self):
        exc = RuntimeError("something")
        exc.status_code = 503
        self.assertEqual(AITools._get_exception_status_code(exc), 503)

    def test_extracts_status_code_from_error_text(self):
        exc = RuntimeError("Error code: 429 - rate limited")
        self.assertEqual(AITools._get_exception_status_code(exc), 429)

    def test_extracts_code_from_json_in_error_text(self):
        exc = RuntimeError('{"code": 500, "message": "internal error"}')
        self.assertEqual(AITools._get_exception_status_code(exc), 500)

    def test_returns_none_for_no_status(self):
        exc = RuntimeError("some random error")
        self.assertIsNone(AITools._get_exception_status_code(exc))

    def test_timeout_is_treated_as_transient(self):
        self.assertTrue(AITools._should_retry_transient_ai_error(TimeoutError()))

    def test_quota_exhaustion_is_not_retried(self):
        exc = RuntimeError(
            "Error code: 429 - {'error': {'status': 'RESOURCE_EXHAUSTED', "
            "'message': 'You exceeded your current quota, free_tier'}}"
        )
        self.assertFalse(AITools._should_retry_transient_ai_error(exc))

    def test_503_unavailable_is_retried(self):
        exc = RuntimeError("Error code: 503 - {'error': {'status': 'UNAVAILABLE'}}")
        self.assertTrue(AITools._should_retry_transient_ai_error(exc))

    def test_400_bad_request_is_not_retried(self):
        exc = RuntimeError("Error code: 400 - bad request")
        self.assertFalse(AITools._should_retry_transient_ai_error(exc))

    def test_rate_limit_text_is_retried(self):
        exc = RuntimeError("rate limit exceeded, try again later")
        self.assertTrue(AITools._should_retry_transient_ai_error(exc))

    def test_high_demand_text_is_retried(self):
        exc = RuntimeError("server is experiencing high demand")
        self.assertTrue(AITools._should_retry_transient_ai_error(exc))

    def test_vision_retry_attempts_reads_from_env(self):
        old = os.environ.get("AI_VISION_RETRY_ATTEMPTS")
        try:
            os.environ["AI_VISION_RETRY_ATTEMPTS"] = "5"
            self.assertEqual(AITools._vision_retry_attempts(), 5)
        finally:
            if old is None:
                os.environ.pop("AI_VISION_RETRY_ATTEMPTS", None)
            else:
                os.environ["AI_VISION_RETRY_ATTEMPTS"] = old

    def test_vision_retry_attempts_uses_default(self):
        old = os.environ.get("AI_VISION_RETRY_ATTEMPTS")
        try:
            os.environ.pop("AI_VISION_RETRY_ATTEMPTS", None)
            self.assertEqual(AITools._vision_retry_attempts(), 2)
        finally:
            if old is not None:
                os.environ["AI_VISION_RETRY_ATTEMPTS"] = old

    def test_vision_retry_delay_scales_with_attempt(self):
        delay1 = AITools._vision_retry_delay(1)
        delay3 = AITools._vision_retry_delay(3)
        self.assertGreaterEqual(delay1, 0.0)
        self.assertGreaterEqual(delay3, delay1)


class VisualCompletionRetryTest(unittest.IsolatedAsyncioTestCase):
    """_create_visual_completion 瞬时错误重试集成测试。"""

    async def test_retries_on_transient_503_error(self):
        fake_completions = _FakeCompletions(
            [
                RuntimeError("Error code: 503 - {'error': {'status': 'UNAVAILABLE'}}"),
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content='{"options":[2]}')
                        )
                    ]
                ),
            ]
        )
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=fake_completions)
        )
        tools = AITools({"api_key": "test", "model": "gpt-4o"})
        tools.client = fake_client

        result = await tools.choose_options_by_image(
            b"fake-image",
            "Choose the correct option",
            [(1, "apple"), (2, "banana")],
        )

        self.assertEqual(result, [2])
        self.assertEqual(len(fake_completions.calls), 2)

    async def test_does_not_retry_on_quota_exhaustion(self):
        fake_completions = _FakeCompletions(
            [
                RuntimeError(
                    "Error code: 429 - {'error': {'status': 'RESOURCE_EXHAUSTED', "
                    "'message': 'You exceeded your current quota, free_tier'}}"
                ),
            ]
        )
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=fake_completions)
        )
        tools = AITools({"api_key": "test", "model": "gpt-4o"})
        tools.client = fake_client

        with self.assertRaises(RuntimeError):
            await tools.choose_options_by_image(
                b"fake-image",
                "Choose the correct option",
                [(1, "apple"), (2, "banana")],
            )
        self.assertEqual(len(fake_completions.calls), 1)

    async def test_retries_on_timeout(self):
        call_count = 0
        original_create = None

        async def slow_create(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("request timed out")
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"options":[1]}')
                    )
                ]
            )

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=slow_create))
        )
        tools = AITools({"api_key": "test", "model": "gpt-4o"})
        tools.client = fake_client

        result = await tools.choose_options_by_image(
            b"fake-image",
            "Choose the correct option",
            [(1, "apple"), (2, "banana")],
        )

        self.assertEqual(result, [1])
        self.assertEqual(call_count, 2)

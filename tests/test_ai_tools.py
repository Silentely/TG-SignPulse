import os
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

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

    async def test_get_reply_retries_transient_error(self):
        """get_reply 统一走受保护调用：瞬时错误按重试策略恢复成功。"""
        call_count = 0

        async def flaky_create(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("request timed out")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="回复内容"))]
            )

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=flaky_create))
        )
        tools = AITools({"api_key": "test", "model": "gpt-4o"})
        tools.client = fake_client

        result = await tools.get_reply("提示词", "问题")
        self.assertEqual(result, "回复内容")
        self.assertEqual(call_count, 2)

    async def test_calculate_problem_passes_timeout_budget(self):
        """calculate_problem 统一走受保护调用：max_tokens 预算下发且可正常返回。"""
        fake_completions = _FakeCompletions(
            [
                SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="42"))]
                ),
            ]
        )
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=fake_completions)
        )
        tools = AITools({"api_key": "test", "model": "gpt-4o"})
        tools.client = fake_client

        result = await tools.calculate_problem("1+1=?")
        self.assertEqual(result, "42")
        self.assertIn("max_tokens", fake_completions.calls[0])

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

    async def test_json_fallback_works_with_retry_attempts_1(self):
        """AI_VISION_RETRY_ATTEMPTS=1 时 JSON fallback 仍应成功。"""
        old = os.environ.get("AI_VISION_RETRY_ATTEMPTS")
        try:
            os.environ["AI_VISION_RETRY_ATTEMPTS"] = "1"
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
            self.assertEqual(len(fake_completions.calls), 2)
            # 第一次调用有 response_format，第二次没有
            self.assertIn("response_format", fake_completions.calls[0])
            self.assertNotIn("response_format", fake_completions.calls[1])
        finally:
            if old is None:
                os.environ.pop("AI_VISION_RETRY_ATTEMPTS", None)
            else:
                os.environ["AI_VISION_RETRY_ATTEMPTS"] = old

    async def test_json_fallback_then_transient_error_still_retries(self):
        """JSON fallback 后遇到 503 仍应按瞬时重试策略处理。"""
        fake_completions = _FakeCompletions(
            [
                RuntimeError("Error code: 403 - response_format json_object unsupported"),
                RuntimeError("Error code: 503 - UNAVAILABLE"),
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
        self.assertEqual(len(fake_completions.calls), 3)

    async def test_consecutive_transient_failures_respect_max_attempts(self):
        """连续瞬时失败时调用次数应受限于 AI_VISION_RETRY_ATTEMPTS。"""
        old = os.environ.get("AI_VISION_RETRY_ATTEMPTS")
        try:
            os.environ["AI_VISION_RETRY_ATTEMPTS"] = "3"
            fake_completions = _FakeCompletions(
                [
                    RuntimeError("Error code: 503 - UNAVAILABLE"),
                    RuntimeError("Error code: 503 - UNAVAILABLE"),
                    RuntimeError("Error code: 503 - UNAVAILABLE"),
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
            # 总调用次数 = AI_VISION_RETRY_ATTEMPTS（3 次）
            self.assertEqual(len(fake_completions.calls), 3)
        finally:
            if old is None:
                os.environ.pop("AI_VISION_RETRY_ATTEMPTS", None)
            else:
                os.environ["AI_VISION_RETRY_ATTEMPTS"] = old


class AIMaxTokensTest(unittest.IsolatedAsyncioTestCase):
    """AI 视觉 max_tokens 与 reasoning_effort 配置测试。"""

    def setUp(self):
        self._old_max_tokens = os.environ.pop("AI_VISION_MAX_TOKENS", None)
        self._old_reasoning_effort = os.environ.pop("AI_VISION_REASONING_EFFORT", None)

    def tearDown(self):
        if self._old_max_tokens is None:
            os.environ.pop("AI_VISION_MAX_TOKENS", None)
        else:
            os.environ["AI_VISION_MAX_TOKENS"] = self._old_max_tokens
        if self._old_reasoning_effort is None:
            os.environ.pop("AI_VISION_REASONING_EFFORT", None)
        else:
            os.environ["AI_VISION_REASONING_EFFORT"] = self._old_reasoning_effort

    def _tools(self, responses):
        fake_completions = _FakeCompletions(responses)
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))
        tools = AITools({"api_key": "test", "model": "gpt-4o"})
        tools.client = fake_client
        return tools, fake_completions

    async def test_choose_options_by_image_defaults_to_512(self):
        tools, fake_completions = self._tools(
            [
                SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content='{"options":[2]}'))]
                )
            ]
        )

        result = await tools.choose_options_by_image(
            b"fake-image",
            "Choose the correct option",
            [(1, "apple"), (2, "banana")],
        )

        self.assertEqual(result, [2])
        self.assertEqual(fake_completions.calls[0]["max_tokens"], 512)

    async def test_choose_options_by_image_respects_env_override(self):
        os.environ["AI_VISION_MAX_TOKENS"] = "768"
        tools, fake_completions = self._tools(
            [
                SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content='{"options":[2]}'))]
                )
            ]
        )

        await tools.choose_options_by_image(
            b"fake-image",
            "Choose the correct option",
            [(1, "apple"), (2, "banana")],
        )

        self.assertEqual(fake_completions.calls[0]["max_tokens"], 768)

    async def test_choose_option_by_image_uses_same_env(self):
        tools, fake_completions = self._tools(
            [
                SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content='{"option":2}'))]
                )
            ]
        )

        result = await tools.choose_option_by_image(
            b"fake-image",
            "Choose the correct option",
            [(1, "apple"), (2, "banana")],
        )

        self.assertEqual(result, 2)
        self.assertEqual(fake_completions.calls[0]["max_tokens"], 512)

    async def test_omits_reasoning_effort_by_default(self):
        """未配置 AI_VISION_REASONING_EFFORT 时不发送该参数。"""
        tools, fake_completions = self._tools(
            [
                SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content='{"options":[2]}'))]
                )
            ]
        )

        await tools.choose_options_by_image(
            b"fake-image",
            "Choose the correct option",
            [(1, "apple"), (2, "banana")],
        )

        self.assertNotIn("reasoning_effort", fake_completions.calls[0])

    async def test_sends_reasoning_effort_from_env(self):
        """AI_VISION_REASONING_EFFORT=none 应透传到请求（大小写不敏感）。"""
        os.environ["AI_VISION_REASONING_EFFORT"] = "None"
        tools, fake_completions = self._tools(
            [
                SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content='{"options":[2]}'))]
                )
            ]
        )

        await tools.choose_options_by_image(
            b"fake-image",
            "Choose the correct option",
            [(1, "apple"), (2, "banana")],
        )

        self.assertEqual(fake_completions.calls[0]["reasoning_effort"], "none")

    async def test_ignores_invalid_reasoning_effort(self):
        """非法 reasoning_effort 值应忽略，不发送参数。"""
        os.environ["AI_VISION_REASONING_EFFORT"] = "banana"
        tools, fake_completions = self._tools(
            [
                SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content='{"options":[2]}'))]
                )
            ]
        )

        await tools.choose_options_by_image(
            b"fake-image",
            "Choose the correct option",
            [(1, "apple"), (2, "banana")],
        )

        self.assertNotIn("reasoning_effort", fake_completions.calls[0])


class ParamDegradationTest(unittest.IsolatedAsyncioTestCase):
    """AI 视觉请求参数兼容降级阶梯测试（Vercel 类严格网关场景）。"""

    def setUp(self):
        self._old_reasoning_effort = os.environ.pop("AI_VISION_REASONING_EFFORT", None)

    def tearDown(self):
        if self._old_reasoning_effort is None:
            os.environ.pop("AI_VISION_REASONING_EFFORT", None)
        else:
            os.environ["AI_VISION_REASONING_EFFORT"] = self._old_reasoning_effort

    @staticmethod
    def _tools(responses):
        fake_completions = _FakeCompletions(responses)
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))
        tools = AITools({"api_key": "test", "model": "gpt-4o"})
        tools.client = fake_client
        return tools, fake_completions

    @staticmethod
    def _ok(content='{"options":[2]}'):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content=content),
                )
            ]
        )

    @staticmethod
    def _invalid_input():
        return RuntimeError(
            "Error code: 400 - {'error': {'message': 'Invalid input', "
            "'type': 'invalid_request_error'}}"
        )

    async def test_vercel_invalid_input_degrades_to_reasoning_object(self):
        """Vercel 拒绝 reasoning_effort/json_object 时逐级降级，最终用 reasoning 对象成功。"""
        os.environ["AI_VISION_REASONING_EFFORT"] = "none"
        tools, fake_completions = self._tools(
            [
                self._invalid_input(),
                self._invalid_input(),
                self._invalid_input(),
                self._ok(),
            ]
        )

        result = await tools.choose_options_by_image(
            b"fake-image",
            "Choose the correct option",
            [(1, "apple"), (2, "banana")],
        )

        self.assertEqual(result, [2])
        self.assertEqual(len(fake_completions.calls), 4)
        last = fake_completions.calls[-1]
        self.assertEqual(last.get("reasoning"), {"enabled": False})
        self.assertNotIn("response_format", last)
        self.assertNotIn("reasoning_effort", last)
        # 首档仍携带完整参数
        self.assertEqual(fake_completions.calls[0].get("reasoning_effort"), "none")
        self.assertIn("response_format", fake_completions.calls[0])

    async def test_degrades_to_bare_request_when_all_stages_rejected(self):
        """连 reasoning 对象也被拒绝时，最终退回裸请求。"""
        os.environ["AI_VISION_REASONING_EFFORT"] = "none"
        tools, fake_completions = self._tools(
            [
                self._invalid_input(),
                self._invalid_input(),
                self._invalid_input(),
                self._invalid_input(),
                self._invalid_input(),
                self._ok(),
            ]
        )

        result = await tools.choose_options_by_image(
            b"fake-image",
            "Choose the correct option",
            [(1, "apple"), (2, "banana")],
        )

        self.assertEqual(result, [2])
        self.assertEqual(len(fake_completions.calls), 6)
        last = fake_completions.calls[-1]
        self.assertNotIn("response_format", last)
        self.assertNotIn("reasoning_effort", last)
        self.assertNotIn("reasoning", last)

    async def test_rejects_only_effort_keeps_json_and_disables_thinking(self):
        """仅拒绝 reasoning_effort 但接受 reasoning 对象 + JSON mode 的网关：
        降级后应同时保留 JSON mode 并关闭思考（不退回 thinking 开启的纯 JSON 档）。"""
        os.environ["AI_VISION_REASONING_EFFORT"] = "none"
        tools, fake_completions = self._tools(
            [
                RuntimeError("Error code: 400 - Invalid value for 'reasoning_effort'"),
                RuntimeError("Error code: 400 - Invalid value for 'reasoning_effort'"),
                self._ok(),
            ]
        )

        result = await tools.choose_options_by_image(
            b"fake-image",
            "Choose the correct option",
            [(1, "apple"), (2, "banana")],
        )

        self.assertEqual(result, [2])
        self.assertEqual(len(fake_completions.calls), 3)
        last = fake_completions.calls[-1]
        self.assertIn("response_format", last)
        self.assertEqual(last.get("reasoning"), {"enabled": False})
        self.assertNotIn("reasoning_effort", last)

    async def test_non_none_effort_never_sends_reasoning_object(self):
        """low/medium/high 的降级不应引入 reasoning: {enabled: false}（会静默关闭思考）。"""
        os.environ["AI_VISION_REASONING_EFFORT"] = "medium"
        tools, fake_completions = self._tools(
            [
                RuntimeError("Error code: 400 - Invalid value for 'reasoning_effort'"),
                RuntimeError("Error code: 400 - Invalid value for 'reasoning_effort'"),
                RuntimeError("Error code: 400 - Invalid value for 'response_format'"),
                self._ok(),
            ]
        )

        result = await tools.choose_options_by_image(
            b"fake-image",
            "Choose the correct option",
            [(1, "apple"), (2, "banana")],
        )

        self.assertEqual(result, [2])
        self.assertEqual(len(fake_completions.calls), 4)
        for call in fake_completions.calls:
            self.assertNotIn("reasoning", call)
        last = fake_completions.calls[-1]
        self.assertNotIn("response_format", last)
        self.assertNotIn("reasoning_effort", last)

    async def test_context_length_error_not_degraded(self):
        """上下文超长（code=context_length_exceeded）不触发参数降级，只请求一次。"""
        os.environ["AI_VISION_REASONING_EFFORT"] = "none"
        exc = RuntimeError("Error code: 400 - maximum context length exceeded")
        exc.body = {
            "error": {
                "message": "This model's maximum context length is 128000 tokens...",
                "type": "invalid_request_error",
                "code": "context_length_exceeded",
                "param": None,
            }
        }
        tools, fake_completions = self._tools([exc])

        with self.assertRaises(RuntimeError):
            await tools.choose_options_by_image(
                b"fake-image",
                "Choose the correct option",
                [(1, "apple"), (2, "banana")],
            )
        self.assertEqual(len(fake_completions.calls), 1)

    def test_param_rejection_via_structured_param_field(self):
        """错误 param 字段明确指向我们控制的参数时判定为参数不兼容。"""
        exc = RuntimeError("invalid input")
        exc.body = {
            "error": {
                "message": "bad value",
                "type": "invalid_request_error",
                "code": None,
                "param": "reasoning_effort",
            }
        }
        self.assertTrue(AITools._is_param_rejection_error(exc))

    def test_structured_code_excludes_context_length(self):
        """结构化 code 为 context_length_exceeded 时不判定为参数不兼容。"""
        exc = RuntimeError("invalid input")
        exc.body = {
            "error": {
                "message": "Invalid input",
                "type": "invalid_request_error",
                "code": "context_length_exceeded",
                "param": None,
            }
        }
        self.assertFalse(AITools._is_param_rejection_error(exc))

    async def test_plain_400_not_degraded_or_retried(self):
        """普通 400（非参数不兼容）不触发降级，也不按瞬时错误重试。"""
        os.environ["AI_VISION_REASONING_EFFORT"] = "none"
        tools, fake_completions = self._tools(
            [RuntimeError("Error code: 400 - bad request")]
        )

        with self.assertRaises(RuntimeError):
            await tools.choose_options_by_image(
                b"fake-image",
                "Choose the correct option",
                [(1, "apple"), (2, "banana")],
            )
        self.assertEqual(len(fake_completions.calls), 1)

    async def test_stage_degradation_position_survives_transient_retry(self):
        """降级位置跨瞬时重试保留（不退回第一档）。"""
        os.environ["AI_VISION_REASONING_EFFORT"] = "none"
        tools, fake_completions = self._tools(
            [
                self._invalid_input(),
                RuntimeError("Error code: 503 - UNAVAILABLE"),
                self._ok(),
            ]
        )

        result = await tools.choose_options_by_image(
            b"fake-image",
            "Choose the correct option",
            [(1, "apple"), (2, "banana")],
        )

        self.assertEqual(result, [2])
        self.assertEqual(len(fake_completions.calls), 3)
        # 第二次重试从降级后的第二档继续，不再回退到带 json_object 的首档
        self.assertNotIn("response_format", fake_completions.calls[1])
        self.assertNotIn("response_format", fake_completions.calls[2])


class VisualTruncationRetryTest(unittest.IsolatedAsyncioTestCase):
    """max_tokens 截断时放宽预算重试测试。"""

    def setUp(self):
        self._old_max_tokens = os.environ.pop("AI_VISION_MAX_TOKENS", None)
        self._old_retry_attempts = os.environ.pop("AI_VISION_RETRY_ATTEMPTS", None)

    def tearDown(self):
        if self._old_max_tokens is None:
            os.environ.pop("AI_VISION_MAX_TOKENS", None)
        else:
            os.environ["AI_VISION_MAX_TOKENS"] = self._old_max_tokens
        if self._old_retry_attempts is None:
            os.environ.pop("AI_VISION_RETRY_ATTEMPTS", None)
        else:
            os.environ["AI_VISION_RETRY_ATTEMPTS"] = self._old_retry_attempts

    @staticmethod
    def _truncated(content=None):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="length",
                    message=SimpleNamespace(content=content),
                )
            ]
        )

    @staticmethod
    def _ok(content):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content=content),
                )
            ]
        )

    async def test_retries_with_doubled_budget_on_truncation(self):
        """首次响应被 max_tokens 截断时，应放宽预算重试并最终成功。"""
        fake_completions = _FakeCompletions(
            [
                self._truncated(content=None),
                self._ok('{"options":[2]}'),
            ]
        )
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))
        tools = AITools({"api_key": "test", "model": "gpt-4o"})
        tools.client = fake_client

        result = await tools.choose_options_by_image(
            b"fake-image",
            "Choose the correct option",
            [(1, "apple"), (2, "banana")],
        )

        self.assertEqual(result, [2])
        self.assertEqual(len(fake_completions.calls), 2)
        self.assertEqual(fake_completions.calls[0]["max_tokens"], 512)
        self.assertEqual(fake_completions.calls[1]["max_tokens"], 1024)

    async def test_raises_when_truncated_on_last_attempt(self):
        """全部尝试均被截断时，应抛出明确的 RuntimeError。"""
        fake_completions = _FakeCompletions(
            [
                self._truncated(content=None),
                self._truncated(content=None),
            ]
        )
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))
        tools = AITools({"api_key": "test", "model": "gpt-4o"})
        tools.client = fake_client

        with self.assertRaises(RuntimeError):
            await tools.choose_options_by_image(
                b"fake-image",
                "Choose the correct option",
                [(1, "apple"), (2, "banana")],
            )
        self.assertEqual(len(fake_completions.calls), 2)

    async def test_truncation_retry_stops_at_cap(self):
        """max_tokens 已到封顶（4096）时不再翻倍，直接抛错避免超出厂商上限。"""
        os.environ["AI_VISION_MAX_TOKENS"] = "4096"
        fake_completions = _FakeCompletions(
            [
                self._truncated(content=None),
            ]
        )
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))
        tools = AITools({"api_key": "test", "model": "gpt-4o"})
        tools.client = fake_client

        with self.assertRaises(RuntimeError):
            await tools.choose_options_by_image(
                b"fake-image",
                "Choose the correct option",
                [(1, "apple"), (2, "banana")],
            )
        self.assertEqual(len(fake_completions.calls), 1)
        self.assertEqual(fake_completions.calls[0]["max_tokens"], 4096)

    def test_is_truncated_completion_heuristics(self):
        self.assertTrue(AITools._is_truncated_completion(self._truncated()))
        self.assertFalse(AITools._is_truncated_completion(self._ok('{"options":[1]}')))
        self.assertFalse(AITools._is_truncated_completion(SimpleNamespace(choices=[])))
        self.assertFalse(AITools._is_truncated_completion(SimpleNamespace()))


class AITimeoutTest(unittest.TestCase):
    """AI 视觉超时默认值测试。"""

    def test_default_timeout_is_15_seconds(self):
        old = os.environ.get("AI_VISION_TIMEOUT")
        try:
            os.environ.pop("AI_VISION_TIMEOUT", None)
            self.assertEqual(AITools._ai_timeout(), 15.0)
        finally:
            if old is not None:
                os.environ["AI_VISION_TIMEOUT"] = old

    def test_env_timeout_overrides_default(self):
        old = os.environ.get("AI_VISION_TIMEOUT")
        try:
            os.environ["AI_VISION_TIMEOUT"] = "20"
            self.assertEqual(AITools._ai_timeout(), 20.0)
        finally:
            if old is not None:
                os.environ["AI_VISION_TIMEOUT"] = old

    def test_timeout_minimum_is_3_seconds(self):
        old = os.environ.get("AI_VISION_TIMEOUT")
        try:
            os.environ["AI_VISION_TIMEOUT"] = "1"
            self.assertEqual(AITools._ai_timeout(), 3.0)
        finally:
            if old is not None:
                os.environ["AI_VISION_TIMEOUT"] = old


class ImageUrlFormatTest(unittest.IsolatedAsyncioTestCase):
    """Zhipu/Z.ai GLM Vision 图片 URL 格式适配测试。"""

    async def test_zhipu_base_url_sends_raw_base64(self):
        for base_url in (
            "https://open.bigmodel.cn/api/paas/v4",
            "https://api.z.ai/api/paas/v4",
        ):
            with self.subTest(base_url=base_url):
                fake_completions = _FakeCompletions(
                    [
                        SimpleNamespace(
                            choices=[
                                SimpleNamespace(
                                    message=SimpleNamespace(content='{"options":[1]}')
                                )
                            ]
                        ),
                    ]
                )
                fake_client = SimpleNamespace(
                    chat=SimpleNamespace(completions=fake_completions)
                )
                tools = AITools(
                    {
                        "api_key": "test",
                        "base_url": base_url,
                        "model": "GLM-4.6V-Flash",
                    }
                )
                tools.client = fake_client

                await tools.choose_options_by_image(
                    b"fake-image",
                    "Choose the correct option",
                    [(1, "apple"), (2, "banana")],
                )

                image_url = fake_completions.calls[0]["messages"][1]["content"][1]["image_url"]["url"]
                self.assertEqual(image_url, "ZmFrZS1pbWFnZQ==")

    async def test_standard_base_url_sends_data_url(self):
        fake_completions = _FakeCompletions(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content='{"options":[1]}')
                        )
                    ]
                ),
            ]
        )
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=fake_completions)
        )
        tools = AITools(
            {
                "api_key": "test",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o",
            }
        )
        tools.client = fake_client

        await tools.choose_options_by_image(
            b"fake-image",
            "Choose the correct option",
            [(1, "apple"), (2, "banana")],
        )

        image_url = fake_completions.calls[0]["messages"][1]["content"][1]["image_url"]["url"]
        self.assertEqual(image_url, "data:image/jpeg;base64,ZmFrZS1pbWFnZQ==")

    async def test_extract_text_uses_correct_format_for_zhipu(self):
        fake_completions = _FakeCompletions(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content="IkKR")
                        )
                    ]
                ),
            ]
        )
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=fake_completions)
        )
        tools = AITools(
            {
                "api_key": "test",
                "base_url": "https://open.bigmodel.cn/api/paas/v4",
                "model": "GLM-4.6V-Flash",
            }
        )
        tools.client = fake_client

        await tools.extract_text_by_image(b"fake-image")

        image_url = fake_completions.calls[0]["messages"][1]["content"][1]["image_url"]["url"]
        self.assertEqual(image_url, "ZmFrZS1pbWFnZQ==")

    async def test_similar_domain_not_mistaken_for_zhipu(self):
        """相似域名（如 open.bigmodel.cn.evil.com）不应被识别为 Zhipu。"""
        for base_url in (
            "https://open.bigmodel.cn.evil.com/api/paas/v4",
            "https://evil-open.bigmodel.cn.attacker.test/v1",
            "https://api.openai.com/v1?next=open.bigmodel.cn",
            "https://user:pass@open.bigmodel.cn.evil.com/v1",
        ):
            with self.subTest(base_url=base_url):
                fake_completions = _FakeCompletions(
                    [
                        SimpleNamespace(
                            choices=[
                                SimpleNamespace(
                                    message=SimpleNamespace(content='{"options":[1]}')
                                )
                            ]
                        ),
                    ]
                )
                fake_client = SimpleNamespace(
                    chat=SimpleNamespace(completions=fake_completions)
                )
                tools = AITools(
                    {
                        "api_key": "test",
                        "base_url": base_url,
                        "model": "gpt-4o",
                    }
                )
                tools.client = fake_client

                await tools.choose_options_by_image(
                    b"fake-image",
                    "Choose the correct option",
                    [(1, "apple"), (2, "banana")],
                )

                image_url = fake_completions.calls[0]["messages"][1]["content"][1]["image_url"]["url"]
                self.assertTrue(
                    image_url.startswith("data:image/jpeg;base64,"),
                    f"Expected data URL for {base_url}, got: {image_url}",
                )

    async def test_uppercase_zhipu_host_still_recognized(self):
        """大写 hostname 仍应被识别为 Zhipu。"""
        fake_completions = _FakeCompletions(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content='{"options":[1]}')
                        )
                    ]
                ),
            ]
        )
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=fake_completions)
        )
        tools = AITools(
            {
                "api_key": "test",
                "base_url": "HTTPS://OPEN.BIGMODEL.CN/api/paas/v4",
                "model": "GLM-4.6V-Flash",
            }
        )
        tools.client = fake_client

        await tools.choose_options_by_image(
            b"fake-image",
            "Choose the correct option",
            [(1, "apple"), (2, "banana")],
        )

        image_url = fake_completions.calls[0]["messages"][1]["content"][1]["image_url"]["url"]
        self.assertEqual(image_url, "ZmFrZS1pbWFnZQ==")


class MidFlowTerminalSuccessTest(unittest.IsolatedAsyncioTestCase):
    """执行中终态停止：预检已删除；发送后/历史回退边界。"""

    def test_precheck_helpers_removed(self):
        """签到前扫历史预检相关 API 必须不存在。"""
        from tg_signer.core import UserSigner

        self.assertFalse(hasattr(UserSigner, "_chat_has_today_terminal_success"))
        self.assertFalse(hasattr(UserSigner, "_should_precheck_today_terminal_success"))
        self.assertFalse(hasattr(UserSigner, "_message_is_from_today"))
        # 执行中终态判定仍保留
        self.assertTrue(hasattr(UserSigner, "_wait_for_terminal_success"))
        self.assertTrue(hasattr(UserSigner, "_message_has_terminal_success_text"))
        self.assertTrue(hasattr(UserSigner, "_text_has_terminal_success_text"))
        self.assertTrue(hasattr(UserSigner, "_callback_text_has_terminal_success_text"))
        self.assertTrue(hasattr(UserSigner, "_message_is_actionable_target"))
        self.assertTrue(hasattr(UserSigner, "_maybe_stop_after_send"))

    def test_callback_already_signed_is_terminal(self):
        from tg_signer.core import UserSigner

        signer = object.__new__(UserSigner)
        self.assertTrue(
            signer._callback_text_has_terminal_success_text("今日已签到")
        )
        self.assertTrue(
            signer._callback_text_has_terminal_success_text("您今天已经签到")
        )

    def test_actionable_target_skips_terminal_and_non_bot(self):
        from tg_signer.core import UserSigner

        signer = object.__new__(UserSigner)
        # 已终态：不可再作为操作对象
        done = SimpleNamespace(
            text="🎉 签到成功，获得了 1 积分",
            caption=None,
            from_user=SimpleNamespace(is_bot=True),
        )
        self.assertFalse(signer._message_is_actionable_target(done))
        # 群聊路人：不可操作
        human = SimpleNamespace(
            text="请点击下方按钮",
            caption=None,
            from_user=SimpleNamespace(is_bot=False),
        )
        self.assertFalse(signer._message_is_actionable_target(human))
        # bot 验证消息：可操作
        bot_challenge = SimpleNamespace(
            text="请选择正确图片",
            caption=None,
            from_user=SimpleNamespace(is_bot=True),
        )
        self.assertTrue(signer._message_is_actionable_target(bot_challenge))
        # 无 from_user（频道等）：可操作
        channel = SimpleNamespace(text="请完成验证", caption=None, from_user=None)
        self.assertTrue(signer._message_is_actionable_target(channel))

    def test_post_send_terminal_timeout_env(self):
        from tg_signer.core import UserSigner

        signer = object.__new__(UserSigner)
        old = os.environ.pop("SIGN_TASK_POST_SEND_TERMINAL_TIMEOUT", None)
        try:
            self.assertEqual(signer._post_send_terminal_timeout(), 3.0)
            os.environ["SIGN_TASK_POST_SEND_TERMINAL_TIMEOUT"] = "0"
            self.assertEqual(signer._post_send_terminal_timeout(), 0.0)
            os.environ["SIGN_TASK_POST_SEND_TERMINAL_TIMEOUT"] = "5.5"
            self.assertEqual(signer._post_send_terminal_timeout(), 5.5)
        finally:
            if old is None:
                os.environ.pop("SIGN_TASK_POST_SEND_TERMINAL_TIMEOUT", None)
            else:
                os.environ["SIGN_TASK_POST_SEND_TERMINAL_TIMEOUT"] = old

    async def test_maybe_stop_after_send_sets_flag_on_terminal(self):
        from tg_signer.core import UserSigner

        signer = object.__new__(UserSigner)
        signer.log = lambda *a, **k: None
        signer.context = signer.ensure_ctx()
        signer._post_send_terminal_timeout = lambda: 1.0

        async def fake_wait(*args, **kwargs):
            signer.context.stop_reason = "今日已签到"
            return True

        signer._wait_for_terminal_success = fake_wait

        chat = SimpleNamespace(chat_id=1, message_thread_id=None)
        await signer._maybe_stop_after_send(
            chat, before_state={1: ("x",)}, history_limit=8
        )
        self.assertTrue(signer.context.stop_after_current_action)
        self.assertEqual(signer.context.stop_reason, "今日已签到")

    async def test_maybe_stop_after_send_disabled_when_timeout_zero(self):
        from tg_signer.core import UserSigner

        signer = object.__new__(UserSigner)
        signer.log = lambda *a, **k: None
        signer.context = signer.ensure_ctx()
        signer._post_send_terminal_timeout = lambda: 0.0
        signer._wait_for_terminal_success = AsyncMock(return_value=True)

        chat = SimpleNamespace(chat_id=1, message_thread_id=None)
        await signer._maybe_stop_after_send(
            chat, before_state={}, history_limit=8
        )
        self.assertFalse(signer.context.stop_after_current_action)
        signer._wait_for_terminal_success.assert_not_called()


class SuccessTextDetectionTest(unittest.TestCase):
    """签到成功文本检测增强测试。"""

    def test_strong_success_overrides_prior_verification_error(self):
        """验证码错误文本后跟签到成功，应判定为成功。"""
        from tg_signer.core import UserSigner

        signer = object.__new__(UserSigner)
        text = "验证码错误!\n🎉 签到成功，获得了 20积分\n💰总积分：1563"
        self.assertTrue(signer._text_has_terminal_success_text(text))

    def test_additional_chinese_checkin_success_markers(self):
        """测试打卡成功、今日已完成签到、明天再来等中文签到终止标记。"""
        from tg_signer.core import UserSigner

        signer = object.__new__(UserSigner)
        self.assertTrue(signer._text_has_terminal_success_text("今日已完成签到，请明天再来"))
        self.assertTrue(signer._text_has_terminal_success_text("打卡成功，获得 5 积分"))
        self.assertTrue(signer._text_has_terminal_success_text("今日已打卡"))
        self.assertTrue(signer._text_has_terminal_success_text("明天再来吧"))
        self.assertTrue(signer._callback_text_has_terminal_success_text("今日已打卡"))
        self.assertTrue(signer._callback_text_has_terminal_success_text("今日已完成签到"))

    def test_sign_opportunity_exhausted_is_success(self):
        """签到机会已用完表示今日已签到。"""
        from tg_signer.core import UserSigner

        signer = object.__new__(UserSigner)
        self.assertTrue(signer._text_has_terminal_success_text("签到机会已用完"))

    def test_today_cannot_sign_again_is_success(self):
        """今天不能再签到表示今日已签到。"""
        from tg_signer.core import UserSigner

        signer = object.__new__(UserSigner)
        self.assertTrue(signer._text_has_terminal_success_text("今天不能再签到"))

    def test_contradictory_same_line_is_not_success(self):
        """同一行内矛盾文本（签到失败，签到成功）不应判定为成功。"""
        from tg_signer.core import UserSigner

        signer = object.__new__(UserSigner)
        self.assertFalse(signer._text_has_terminal_success_text("签到失败，签到成功"))

    def test_failure_prefix_negates_success(self):
        """否定前缀（未签到成功）不应判定为成功。"""
        from tg_signer.core import UserSigner

        signer = object.__new__(UserSigner)
        self.assertFalse(signer._text_has_terminal_success_text("未签到成功"))

    def test_action_required_before_success_is_not_success(self):
        """需要先完成验证的消息不应判定为成功。"""
        from tg_signer.core import UserSigner

        signer = object.__new__(UserSigner)
        self.assertFalse(signer._text_has_terminal_success_text("请完成验证后签到成功"))

    def test_newline_separated_failure_then_success_is_success(self):
        """不同行的失败+成功应判定为成功（如验证码错误后跟签到成功）。"""
        from tg_signer.core import UserSigner

        signer = object.__new__(UserSigner)
        self.assertTrue(signer._text_has_terminal_success_text("验证码错误!\n签到成功，获得积分"))


class OpenAIConfigCacheTest(unittest.TestCase):
    """OpenAIConfigManager 文件配置按 mtime 缓存：热路径免重复读盘与解密。"""

    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from tg_signer.ai_tools import _FILE_CFG_CACHE

        _FILE_CFG_CACHE.clear()
        self.addCleanup(_FILE_CFG_CACHE.clear)

    def test_second_load_uses_cache_without_decrypt(self):
        """同 mtime 复用缓存：新实例第二次加载不再触发解密与读盘。"""
        import tg_signer.ai_tools as ai_tools
        from tg_signer.ai_tools import OpenAIConfigManager

        mgr = OpenAIConfigManager(self.tmp.name)
        mgr.save_config("sk-test-1", "https://api.example.com", "gpt-x")
        first = mgr.load_file_config()
        self.assertEqual(first["api_key"], "sk-test-1")

        calls = []
        real = ai_tools.decrypt_secret
        ai_tools.decrypt_secret = lambda v: (calls.append(v), real(v))[1]
        try:
            # 新实例（ensure_ai_cfg 每次新建）也应命中进程级缓存
            second = OpenAIConfigManager(self.tmp.name).load_file_config()
        finally:
            ai_tools.decrypt_secret = real
        self.assertEqual(second["api_key"], "sk-test-1")
        self.assertEqual(calls, [])

    def test_rewrite_invalidates_cache(self):
        """写盘后再次加载返回新值。"""
        from tg_signer.ai_tools import OpenAIConfigManager

        mgr = OpenAIConfigManager(self.tmp.name)
        mgr.save_config("sk-old")
        self.assertEqual(mgr.load_file_config()["api_key"], "sk-old")
        mgr.save_config("sk-new")
        self.assertEqual(
            OpenAIConfigManager(self.tmp.name).load_file_config()["api_key"], "sk-new"
        )

    def test_returned_config_is_copy(self):
        """返回拷贝：调用方修改不污染缓存。"""
        from tg_signer.ai_tools import OpenAIConfigManager

        mgr = OpenAIConfigManager(self.tmp.name)
        mgr.save_config("sk-1")
        cfg = mgr.load_file_config()
        cfg["api_key"] = "mutated"
        self.assertEqual(mgr.load_file_config()["api_key"], "sk-1")


class TokenBudgetCompatibilityTest(unittest.IsolatedAsyncioTestCase):
    """max_tokens 与 max_completion_tokens 兼容性与自适应测试。"""

    def test_prefers_max_completion_tokens(self):
        from tg_signer.ai_tools import prefers_max_completion_tokens

        # GPT-5 系列
        self.assertTrue(prefers_max_completion_tokens("gpt-5"))
        self.assertTrue(prefers_max_completion_tokens("gpt-5-nano"))
        self.assertTrue(prefers_max_completion_tokens("gpt-5.4-mini"))
        self.assertTrue(prefers_max_completion_tokens("openai/gpt-5-mini"))

        # o 系列
        self.assertTrue(prefers_max_completion_tokens("o1"))
        self.assertTrue(prefers_max_completion_tokens("o1-mini"))
        self.assertTrue(prefers_max_completion_tokens("o1-preview"))
        self.assertTrue(prefers_max_completion_tokens("o3-mini"))
        self.assertTrue(prefers_max_completion_tokens("o4-mini"))

        # 传统与第三方模型
        self.assertFalse(prefers_max_completion_tokens("gpt-4o"))
        self.assertFalse(prefers_max_completion_tokens("gpt-4o-mini"))
        self.assertFalse(prefers_max_completion_tokens("claude-3-5-sonnet"))
        self.assertFalse(prefers_max_completion_tokens("deepseek-chat"))
        self.assertFalse(prefers_max_completion_tokens(""))
        self.assertFalse(prefers_max_completion_tokens(None))

    def test_is_token_param_rejection_error_detection(self):
        # 结构化错误 (param="max_tokens")
        exc_structured = SimpleNamespace(
            body={"error": {"param": "max_tokens", "code": "unsupported_parameter"}},
            status_code=400,
        )
        self.assertEqual(
            AITools._is_token_param_rejection_error(exc_structured), "max_tokens"
        )

        # 文本型错误 (Issue #11 真实报错格式)
        exc_text = Exception(
            "Error code: 400 - {'error': {'message': \"Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead.\", 'type': 'invalid_request_error', 'param': 'max_tokens', 'code': 'unsupported_parameter'}}"
        )
        self.assertEqual(
            AITools._is_token_param_rejection_error(exc_text), "max_tokens"
        )

        # 反向不支持 (max_completion_tokens)
        exc_reverse = Exception(
            "Error code: 400 - {'error': {'message': \"Unsupported parameter: 'max_completion_tokens' is not supported with this model. Use 'max_tokens' instead.\", 'param': 'max_completion_tokens'}}"
        )
        self.assertEqual(
            AITools._is_token_param_rejection_error(exc_reverse), "max_completion_tokens"
        )

        # 无关错误 (如 401 认证失败或无关 400)
        exc_auth = SimpleNamespace(status_code=401, body={"error": {"code": "invalid_api_key"}})
        self.assertIsNone(AITools._is_token_param_rejection_error(exc_auth))

    def test_build_visual_request_stages_token_param(self):
        # gpt-5 初始 stage 包含 max_completion_tokens
        stages_gpt5 = AITools._build_visual_request_stages(
            messages=[],
            model="gpt-5-nano",
            temperature=0.0,
            max_tokens=512,
            expect_json=True,
        )
        self.assertIn("max_completion_tokens", stages_gpt5[0])
        self.assertNotIn("max_tokens", stages_gpt5[0])
        self.assertEqual(stages_gpt5[0]["max_completion_tokens"], 512)

        # gpt-4o 初始 stage 包含 max_tokens
        stages_gpt4 = AITools._build_visual_request_stages(
            messages=[],
            model="gpt-4o",
            temperature=0.0,
            max_tokens=512,
            expect_json=True,
        )
        self.assertIn("max_tokens", stages_gpt4[0])
        self.assertNotIn("max_completion_tokens", stages_gpt4[0])
        self.assertEqual(stages_gpt4[0]["max_tokens"], 512)

    async def test_runtime_auto_switch_on_token_param_rejection(self):
        """当遇到 max_tokens 被拒时，自动无缝切换为 max_completion_tokens 重试并成功。"""
        fake_completions = _FakeCompletions(
            [
                Exception(
                    "Error code: 400 - {'error': {'message': \"Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead.\", 'param': 'max_tokens', 'code': 'unsupported_parameter'}}"
                ),
                SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"options":[1]}'), finish_reason="stop")]),
            ]
        )
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))
        tools = AITools({"api_key": "test", "model": "custom-unrecognized-gpt"})
        tools.client = fake_client

        res = await tools.choose_options_by_image(
            b"fake-image",
            "Choose",
            [(1, "apple"), (2, "banana")],
        )
        self.assertEqual(res, [1])
        self.assertEqual(len(fake_completions.calls), 2)
        # 第一次请求带有 max_tokens
        self.assertIn("max_tokens", fake_completions.calls[0])
        # 重试时自动切换为 max_completion_tokens
        self.assertIn("max_completion_tokens", fake_completions.calls[1])
        self.assertNotIn("max_tokens", fake_completions.calls[1])
        self.assertEqual(fake_completions.calls[1]["max_completion_tokens"], 512)

    async def test_truncation_retry_with_max_completion_tokens(self):
        """GPT-5 截断时 max_completion_tokens 正常翻倍重试。"""
        fake_completions = _FakeCompletions(
            [
                SimpleNamespace(
                    choices=[SimpleNamespace(finish_reason="length", message=SimpleNamespace(content="trunc"))]
                ),
                SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"options":[2]}'), finish_reason="stop")]),
            ]
        )
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))
        tools = AITools({"api_key": "test", "model": "gpt-5-nano"})
        tools.client = fake_client

        res = await tools.choose_options_by_image(
            b"fake-image",
            "Choose",
            [(1, "apple"), (2, "banana")],
        )
        self.assertEqual(res, [2])
        self.assertEqual(len(fake_completions.calls), 2)
        self.assertEqual(fake_completions.calls[0]["max_completion_tokens"], 512)
        self.assertEqual(fake_completions.calls[1]["max_completion_tokens"], 1024)

    def test_invalid_value_or_quota_error_not_misidentified(self):
        """参数数值不合法（invalid_value）等非参数名不支持的错误，不应误判为 token 参数不支持。"""
        from tg_signer.ai_tools import is_token_param_rejection_error

        exc_invalid_val = SimpleNamespace(
            status_code=400,
            body={"error": {"param": "max_tokens", "code": "invalid_value", "message": "max_tokens must be <= 4096"}},
        )
        self.assertIsNone(is_token_param_rejection_error(exc_invalid_val))

        exc_too_large = Exception("Error code: 400 - max_tokens is too large, must be at most 2048")
        self.assertIsNone(is_token_param_rejection_error(exc_too_large))

    def test_unrelated_status_code_not_misidentified(self):
        """非 400/422 状态码（如 401 认证失败）即使文本中提到参数名，也不应判定为 token 参数被拒。"""
        from tg_signer.ai_tools import is_token_param_rejection_error

        exc_401 = SimpleNamespace(
            status_code=401,
            body={"error": {"message": "Invalid API key for max_completion_tokens"}},
        )
        self.assertIsNone(is_token_param_rejection_error(exc_401))

    async def test_runtime_oscillation_guard_prevents_infinite_loop(self):
        """当上游交替拒绝 max_tokens 与 max_completion_tokens 时，至多互换一次，防止死循环。"""
        err1 = Exception(
            'Error code: 400 - {"error": {"message": "Unsupported parameter: \'max_tokens\'. Use \'max_completion_tokens\' instead.", "param": "max_tokens", "code": "unsupported_parameter"}}'
        )
        err2 = Exception(
            'Error code: 400 - {"error": {"message": "Unsupported parameter: \'max_completion_tokens\'. Use \'max_tokens\' instead.", "param": "max_completion_tokens", "code": "unsupported_parameter"}}'
        )
        fake_completions = _FakeCompletions([err1, err2, err2, err2])
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))
        tools = AITools({"api_key": "test", "model": "oscillation-test-model"})
        tools.client = fake_client

        with self.assertRaises(Exception) as ctx:
            await tools.choose_options_by_image(
                b"fake-image",
                "Choose",
                [(1, "apple"), (2, "banana")],
            )
        # 验证在尝试完 1 次互换与正常 stage 降级后立即终止抛出异常，绝不发生无限死循环
        self.assertLessEqual(len(fake_completions.calls), 3)
        self.assertIn("max_completion_tokens", str(ctx.exception))

    async def test_truncation_exception_message_matches_active_key(self):
        """当模型输出截断且超过重试预算时，抛出的 RuntimeError 错误信息中准确显示对应的 token 键名。"""
        fake_completions = _FakeCompletions(
            [
                SimpleNamespace(
                    choices=[SimpleNamespace(finish_reason="length", message=SimpleNamespace(content="trunc"))]
                ),
            ] * 5
        )
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))
        tools = AITools({"api_key": "test", "model": "gpt-5-nano"})
        tools.client = fake_client

        with self.assertRaises(RuntimeError) as ctx:
            await tools.choose_options_by_image(
                b"fake-image",
                "Choose",
                [(1, "apple")],
            )
        # 验证提示信息中动态包含正确的键名 max_completion_tokens= 而非写死的 max_tokens=
        self.assertIn("max_completion_tokens=1024", str(ctx.exception))

    def test_azure_unrecognized_argument_supplied_format_recognized(self):
        """Azure OpenAI 旧版 api-version 报错 Unrecognized request argument supplied 能被精准识别。"""
        from tg_signer.ai_tools import is_token_param_rejection_error

        azure_err = SimpleNamespace(
            status_code=400,
            body={
                "error": {
                    "message": "Unrecognized request argument supplied: max_completion_tokens",
                    "type": "invalid_request_error",
                    "param": None,
                    "code": None,
                }
            },
        )
        self.assertEqual(is_token_param_rejection_error(azure_err), "max_completion_tokens")

        azure_err_old_tokens = Exception(
            "Error code: 400 - {'error': {'message': 'Unrecognized request argument supplied: max_tokens'}}"
        )
        self.assertEqual(is_token_param_rejection_error(azure_err_old_tokens), "max_tokens")

    def test_flat_body_error_fields_extraction(self):
        """第三方代理返回顶层扁平结构（无 error 包装）时也能正确提取错误字段。"""
        tools = AITools({"api_key": "test", "model": "test-model"})
        flat_exc = SimpleNamespace(
            status_code=400,
            body={"message": "Unrecognized request argument: max_completion_tokens", "param": "max_completion_tokens"},
        )
        fields = tools._extract_error_fields(flat_exc)
        self.assertEqual(fields.get("param"), "max_completion_tokens")
        self.assertEqual(tools._is_token_param_rejection_error(flat_exc), "max_completion_tokens")

    def test_gpt5_stages_built_without_temperature(self):
        """GPT-5 / o 系列推理模型构建视觉请求 stages 时默认不带 temperature 参数。"""
        tools = AITools({"api_key": "test", "model": "gpt-5-nano"})
        stages = tools._build_visual_request_stages(
            messages=[{"role": "user", "content": "hi"}],
            model="gpt-5-nano",
            temperature=0.1,
            max_tokens=512,
            expect_json=True,
        )
        for stage in stages:
            self.assertNotIn("temperature", stage)
            self.assertIn("max_completion_tokens", stage)

    async def test_temperature_auto_removed_when_rejected(self):
        """对于未预判的自定义模型，若上游报错不支持 temperature，自动移除 temperature 并重试成功。"""
        temp_err = Exception(
            'Error code: 400 - {"error": {"message": "Unsupported value: \'temperature\' does not support 0.1 with this model. Only the default (1) value is supported.", "param": "temperature", "code": "unsupported_value"}}'
        )
        success_resp = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"options":[1]}'), finish_reason="stop")]
        )
        fake_completions = _FakeCompletions([temp_err, success_resp])
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))
        tools = AITools({"api_key": "test", "model": "custom-reasoning-model"})
        tools.client = fake_client

        res = await tools.choose_options_by_image(
            b"fake-image",
            "Choose",
            [(1, "apple")],
        )
        self.assertEqual(res, [1])
        self.assertEqual(len(fake_completions.calls), 2)
        # 第一次请求带有 temperature
        self.assertIn("temperature", fake_completions.calls[0])
        # 重试时自动移除了 temperature
        self.assertNotIn("temperature", fake_completions.calls[1])

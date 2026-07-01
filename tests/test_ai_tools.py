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


class AITimeoutTest(unittest.TestCase):
    """AI 视觉超时默认值测试。"""

    def test_default_timeout_is_8_seconds(self):
        old = os.environ.get("AI_VISION_TIMEOUT")
        try:
            os.environ.pop("AI_VISION_TIMEOUT", None)
            self.assertEqual(AITools._ai_timeout(), 8.0)
        finally:
            if old is not None:
                os.environ["AI_VISION_TIMEOUT"] = old

    def test_env_timeout_overrides_default(self):
        old = os.environ.get("AI_VISION_TIMEOUT")
        try:
            os.environ["AI_VISION_TIMEOUT"] = "15"
            self.assertEqual(AITools._ai_timeout(), 15.0)
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


class TodayTerminalSuccessTest(unittest.IsolatedAsyncioTestCase):
    """签到前今日已完成检测测试。"""

    def test_message_from_today_returns_true(self):
        from tg_signer.core import UserSigner
        from datetime import datetime, timezone

        signer = object.__new__(UserSigner)
        message = SimpleNamespace(
            date=datetime.now(timezone.utc),
        )
        self.assertTrue(signer._message_is_from_today(message))

    def test_message_from_yesterday_returns_false(self):
        from tg_signer.core import UserSigner
        from datetime import datetime, timedelta, timezone

        signer = object.__new__(UserSigner)
        message = SimpleNamespace(
            date=datetime.now(timezone.utc) - timedelta(days=1),
        )
        self.assertFalse(signer._message_is_from_today(message))

    def test_message_without_date_returns_false(self):
        from tg_signer.core import UserSigner

        signer = object.__new__(UserSigner)
        message = SimpleNamespace(date=None)
        self.assertFalse(signer._message_is_from_today(message))

    async def test_chat_has_today_terminal_success_from_cache(self):
        from tg_signer.core import UserSigner
        from datetime import datetime, timezone

        signer = object.__new__(UserSigner)
        signer.log = lambda *args, **kwargs: None
        signer.context = signer.ensure_ctx()

        chat = SimpleNamespace(chat_id=123, message_thread_id=None)
        message = SimpleNamespace(
            id=1,
            chat=SimpleNamespace(id=123),
            text="🎉 签到成功，获得了 20积分",
            caption=None,
            date=datetime.now(timezone.utc),
            edit_date=None,
            message_thread_id=None,
            reply_to_top_message_id=None,
        )
        signer.context.chat_messages[123] = {1: message}
        signer.app = SimpleNamespace()

        result = await signer._chat_has_today_terminal_success(chat, history_limit=20)
        self.assertTrue(result)

    async def test_chat_has_no_success_returns_false(self):
        from tg_signer.core import UserSigner

        signer = object.__new__(UserSigner)
        signer.log = lambda *args, **kwargs: None
        signer.context = signer.ensure_ctx()

        chat = SimpleNamespace(chat_id=123, message_thread_id=None)
        signer.context.chat_messages[123] = {}

        async def fake_history(*args, **kwargs):
            for msg in []:
                yield msg

        signer.app = SimpleNamespace(get_chat_history=fake_history)

        result = await signer._chat_has_today_terminal_success(chat, history_limit=20)
        self.assertFalse(result)

    async def test_non_bot_message_does_not_trigger_skip(self):
        """群里非 bot 用户的成功消息不应导致跳过。"""
        from tg_signer.core import UserSigner
        from datetime import datetime, timezone

        signer = object.__new__(UserSigner)
        signer.log = lambda *args, **kwargs: None
        signer.context = signer.ensure_ctx()

        chat = SimpleNamespace(chat_id=-100123, message_thread_id=None)
        # 模拟非 bot 用户发送的消息（from_user.is_bot=False）
        message = SimpleNamespace(
            id=1,
            chat=SimpleNamespace(id=-100123),
            text="🎉 张三签到成功，获得了 20积分",
            caption=None,
            from_user=SimpleNamespace(is_bot=False),
            date=datetime.now(timezone.utc),
            edit_date=None,
            message_thread_id=None,
            reply_to_top_message_id=None,
        )
        signer.context.chat_messages[-100123] = {1: message}
        signer.app = SimpleNamespace()

        result = await signer._chat_has_today_terminal_success(chat, history_limit=20)
        self.assertFalse(result)

    async def test_bot_message_triggers_skip(self):
        """bot 发送的成功消息应导致跳过。"""
        from tg_signer.core import UserSigner
        from datetime import datetime, timezone

        signer = object.__new__(UserSigner)
        signer.log = lambda *args, **kwargs: None
        signer.context = signer.ensure_ctx()

        chat = SimpleNamespace(chat_id=-100123, message_thread_id=None)
        # 模拟 bot 发送的消息（from_user.is_bot=True）
        message = SimpleNamespace(
            id=1,
            chat=SimpleNamespace(id=-100123),
            text="🎉 签到成功，获得了 20积分",
            caption=None,
            from_user=SimpleNamespace(is_bot=True),
            date=datetime.now(timezone.utc),
            edit_date=None,
            message_thread_id=None,
            reply_to_top_message_id=None,
        )
        signer.context.chat_messages[-100123] = {1: message}
        signer.app = SimpleNamespace()

        result = await signer._chat_has_today_terminal_success(chat, history_limit=20)
        self.assertTrue(result)

    async def test_no_from_user_still_checks(self):
        """没有 from_user 的消息（如系统消息）仍应检查。"""
        from tg_signer.core import UserSigner
        from datetime import datetime, timezone

        signer = object.__new__(UserSigner)
        signer.log = lambda *args, **kwargs: None
        signer.context = signer.ensure_ctx()

        chat = SimpleNamespace(chat_id=123, message_thread_id=None)
        message = SimpleNamespace(
            id=1,
            chat=SimpleNamespace(id=123),
            text="🎉 签到成功，获得了 20积分",
            caption=None,
            from_user=None,
            date=datetime.now(timezone.utc),
            edit_date=None,
            message_thread_id=None,
            reply_to_top_message_id=None,
        )
        signer.context.chat_messages[123] = {1: message}
        signer.app = SimpleNamespace()

        result = await signer._chat_has_today_terminal_success(chat, history_limit=20)
        self.assertTrue(result)


class SuccessTextDetectionTest(unittest.TestCase):
    """签到成功文本检测增强测试。"""

    def test_strong_success_overrides_prior_verification_error(self):
        """验证码错误文本后跟签到成功，应判定为成功。"""
        from tg_signer.core import UserSigner

        signer = object.__new__(UserSigner)
        text = "验证码错误!\n🎉 签到成功，获得了 20积分\n💰总积分：1563"
        self.assertTrue(signer._text_has_terminal_success_text(text))

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

import unittest
from io import BytesIO

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

import unittest

from tg_signer.ai_tools import AITools


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


if __name__ == "__main__":
    unittest.main()

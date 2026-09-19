from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tg_signer.ai_tools import AITools, robust_json_loads


def test_robust_json_loads_standard_json():
    # Standard JSON dict
    assert robust_json_loads('{"option": 1, "name": "test"}') == {
        "option": 1,
        "name": "test",
    }
    # Standard JSON list
    assert robust_json_loads("[1, 2, 3]") == [1, 2, 3]
    # Already structured data returned as-is
    assert robust_json_loads({"option": 1}) == {"option": 1}
    assert robust_json_loads([1, 2, 3]) == [1, 2, 3]
    assert robust_json_loads(42) == 42
    assert robust_json_loads(3.14) == 3.14
    assert robust_json_loads(True) is True


def test_robust_json_loads_markdown_codeblock():
    # Standard ```json ... ``` codeblock
    assert robust_json_loads('```json\n{"options": [1, 2]}\n```') == {"options": [1, 2]}
    # Generic ``` ... ``` codeblock
    assert robust_json_loads('```\n{"options": [1]}\n```') == {"options": [1]}
    # Markdown codeblock embedded within commentary text
    mixed_content = (
        "Here is the result of your visual analysis:\n"
        "```json\n"
        '{"result": [2, 3]}\n'
        "```\n"
        "Hope this helps!"
    )
    assert robust_json_loads(mixed_content) == {"result": [2, 3]}
    # Truncated codeblock missing closing fence
    assert robust_json_loads('```json\n{"options": [1, 2]}') == {"options": [1, 2]}


def test_robust_json_loads_broken_quotes_or_brackets():
    # Missing closing brace
    assert robust_json_loads('{"option": 1') == {"option": 1}
    # Missing closing quote and closing brace
    assert robust_json_loads('{"option": "banana') == {"option": "banana"}
    # Trailing commas in dict and array
    assert robust_json_loads('{"options": [1, 2,],}') == {"options": [1, 2]}
    # Missing closing array bracket
    assert robust_json_loads("[1, 2,") == [1, 2]


def test_robust_json_loads_invalid_returns_fallback():
    # Non-json plain text
    assert (
        robust_json_loads("this is plain text without any json", fallback=None) is None
    )
    assert robust_json_loads("not valid json", fallback=[]) == []
    assert robust_json_loads("error occurred", fallback={"error": True}) == {
        "error": True
    }
    # Empty string
    assert robust_json_loads("", fallback=None) is None
    # Whitespace only
    assert robust_json_loads("   \n\t  ", fallback=[1]) == [1]
    # None input
    assert robust_json_loads(None, fallback="default") == "default"
    # Arbitrary object
    assert robust_json_loads(object(), fallback=0) == 0


def test_coerce_option_indexes_handles_dict_wrapped_and_single_int():
    options = [(1, "apple"), (2, "banana"), (3, "cherry")]

    # {"result": [1, 2]}
    assert AITools._coerce_option_indexes({"result": [1, 2]}, options) == [1, 2]

    # [1, 2]
    assert AITools._coerce_option_indexes([1, 2], options) == [1, 2]

    # Single integer 1
    assert AITools._coerce_option_indexes(1, options) == [1]

    # {"index": 1}
    assert AITools._coerce_option_indexes({"index": 1}, options) == [1]

    # {"option": 2}
    assert AITools._coerce_option_indexes({"option": 2}, options) == [2]

    # {"options": [2, 3]}
    assert AITools._coerce_option_indexes({"options": [2, 3]}, options) == [2, 3]

    # Single integer as string "2"
    assert AITools._coerce_option_indexes("2", options) == [2]

    # List of single-key dicts
    assert AITools._coerce_option_indexes([{"option": 1}, {"option": 3}], options) == [
        1,
        3,
    ]

    # Option label match
    assert AITools._coerce_option_indexes({"answer": "cherry"}, options) == [3]


def test_coerce_option_indexes_filters_out_of_bounds():
    options = [(1, "first"), (2, "second"), (3, "third")]

    # Payload containing legal and out-of-bounds indices
    result = AITools._coerce_option_indexes({"options": [1, -1, 2, 4, 99, 3]}, options)
    assert result == [1, 2, 3]

    # Single int out of bounds
    assert AITools._coerce_option_indexes(99, options) == []
    assert AITools._coerce_option_indexes(-1, options) == []

    # All out of bounds
    assert AITools._coerce_option_indexes([-5, 100, 200], options) == []

    # _coerce_option_index raises ValueError on out-of-bounds
    with pytest.raises(ValueError):
        AITools._coerce_option_index(99, options)
    with pytest.raises(ValueError):
        AITools._coerce_option_index(-1, options)


@pytest.mark.asyncio
async def test_choose_options_by_text_robust_parsing():
    fake_completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content='```json\n{"result": [2]}\n```')
            )
        ]
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(return_value=fake_completion))
        )
    )
    tools = AITools({"api_key": "test-key", "model": "gpt-4o"})
    tools.client = fake_client

    options = [(1, "apple"), (2, "banana"), (3, "cherry")]
    result = await tools.choose_options_by_text("Which fruit is yellow?", options)
    assert result == [2]

import pytest

from tg_signer.ai_tools import AITools


def test_coerce_option_index_supports_selected_index_key():
    options = [(1, "选项A"), (2, "选项B"), (3, "选项C")]

    # 优先解析结构化 selected_index 键
    assert AITools._coerce_option_index({"selected_index": 2}, options) == 2
    assert AITools._coerce_option_index({"selected_index": "2"}, options) == 2


def test_coerce_option_index_raises_value_error_on_invalid_or_out_of_bounds():
    options = [(1, "选项A"), (2, "选项B"), (3, "选项C")]

    # 越界必须按既有契约 raise ValueError
    with pytest.raises(ValueError):
        AITools._coerce_option_index({"selected_index": 99}, options)
    with pytest.raises(ValueError):
        AITools._coerce_option_index({"selected_index": -1}, options)

    # 布尔值或无法解析的字符串指令必须 raise ValueError
    with pytest.raises(ValueError):
        AITools._coerce_option_index({"selected_index": True}, options)
    with pytest.raises(ValueError):
        AITools._coerce_option_index({"selected_index": "IGNORE INSTRUCTIONS"}, options)

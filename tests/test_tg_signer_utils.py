"""
tg_signer/utils.py 单元测试

覆盖范围：
- numbering：各编号语言取值、未知数字/语言回退
- UserInput：序号自增自减、index_str 格式化、交互调用
- print_to_user：拼接写入、自定义输出流、编码回退、flush 失败容忍
"""

from __future__ import annotations

import io
from unittest.mock import patch

from tg_signer.utils import (
    UserInput,
    numbering,
    numbering_systems,
    print_to_user,
)

ALL_LANGS = list(next(iter(numbering_systems.values())).keys())


class TestNumbering:
    """numbering() 取值与回退"""

    def test_known_values(self):
        assert numbering(1, "arabic") == "1"
        assert numbering(1, "chinese_simple") == "一"
        assert numbering(2, "roman") == "II"
        assert numbering(2, "roman_lower") == "ii"
        assert numbering(1, "tian_gan") == "甲"
        assert numbering(1, "di_zhi") == "子"
        assert numbering(10, "emoji") == "🔟"

    def test_all_langs_for_supported_numbers(self):
        # 编号表内每个数字的每种语言都必须有非空映射
        for num, mapping in numbering_systems.items():
            for lang in ALL_LANGS:
                value = numbering(num, lang)
                assert value, f"numbering_systems[{num}][{lang!r}] 为空"
                assert value == mapping[lang]

    def test_unknown_number_falls_back_to_str(self):
        assert numbering(0, "arabic") == "0"
        assert numbering(999, "chinese_simple") == "999"

    def test_unknown_lang_falls_back_to_str(self):
        # 非法语言名触发 KeyError 回退，行为与未知数字一致
        assert numbering(1, "not_a_lang") == "1"


class TestUserInput:
    """UserInput 序号状态机"""

    def test_default_index_and_str(self):
        ui = UserInput()
        assert ui.index == 1
        assert ui.index_str == "1. "

    def test_incr_and_decr(self):
        ui = UserInput(index=1)
        ui.incr()
        assert ui.index == 2
        ui.incr(3)
        assert ui.index == 5
        ui.decr()
        assert ui.index == 4
        ui.decr(2)
        assert ui.index == 2

    def test_index_str_follows_lang(self):
        ui = UserInput(index=2, numbering_lang="chinese_simple")
        assert ui.index_str == "二. "
        ui.incr()
        assert ui.index_str == "三. "

    def test_index_str_out_of_range_falls_back(self):
        ui = UserInput(index=999)
        assert ui.index_str == "999. "

    def test_call_prompts_and_increments(self):
        ui = UserInput(index=1)
        with patch("builtins.input", return_value="hello") as mock_input:
            result = ui("你的选择: ")
        assert result == "hello"
        assert ui.index == 2
        (prompt,), _ = mock_input.call_args
        assert prompt == "1. 你的选择: "


class TestPrintToUser:
    """print_to_user() 输出与容错"""

    def test_writes_joined_text_to_stdout(self, capsys):
        print_to_user("a", "b", 1)
        captured = capsys.readouterr()
        assert captured.out == "a b 1\n"

    def test_custom_sep_end_and_file(self):
        stream = io.StringIO()
        print_to_user("x", "y", sep="/", end="", file=stream)
        assert stream.getvalue() == "x/y"

    def test_unicode_fallback_on_encode_error(self):
        class AsciiOnlyStream:
            encoding = "ascii"

            def __init__(self):
                self.writes: list[str] = []

            def write(self, text: str) -> int:
                self.writes.append(text)
                text.encode("ascii")
                return len(text)

        stream = AsciiOnlyStream()
        print_to_user("中文", file=stream)
        # 第一次写入触发 UnicodeEncodeError 后，应以 backslashreplace 安全文本重试成功
        assert len(stream.writes) == 2
        assert stream.writes[0] == "中文\n"
        assert "\\u4e2d\\u6587" in stream.writes[1]

    def test_write_failure_without_encoding_attr(self):
        class NoEncodingStream:
            """无 encoding 属性的流：遇非 ASCII 内容拒绝写入"""

            def __init__(self):
                self.writes: list[str] = []

            def write(self, text: str) -> int:
                self.writes.append(text)
                text.encode("ascii")
                return len(text)

        stream = NoEncodingStream()
        print_to_user("中文", file=stream)
        # encoding 缺失时按 ascii 做 backslashreplace 兜底，重试写入成功
        assert len(stream.writes) == 2
        assert "\\u4e2d\\u6587" in stream.writes[1]

    def test_flush_failure_is_tolerated(self):
        class BrokenFlushStream(io.StringIO):
            def flush(self) -> None:
                raise OSError("flush broken")

        stream = BrokenFlushStream()
        print_to_user("ok", file=stream, flush=True)
        assert stream.getvalue() == "ok\n"

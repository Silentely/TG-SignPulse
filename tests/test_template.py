from __future__ import annotations

import datetime

from tg_signer.core.template import (
    render_template,
    render_template_recursive,
)


def test_render_template_plain_text():
    assert render_template("Hello world") == "Hello world"
    assert render_template("") == ""
    assert render_template(None) is None


def test_render_template_builtins():
    now_date = datetime.datetime.now().strftime("%Y-%m-%d")
    res = render_template("Today is {{ date }}")
    assert res == f"Today is {now_date}"

    res = render_template("Time format: {{ now.strftime('%Y') }}")
    assert res == f"Time format: {datetime.datetime.now().year}"

    res = render_template("Random: {{ random_int(10, 10) }}")
    assert res == "Random: 10"

    res = render_template("Choice: {{ random_choice('single') }}")
    assert res == "Choice: single"

    res = render_template("UUID: {{ uuid(short=True) }}")
    assert len(res.replace("UUID: ", "")) == 8


def test_render_template_custom_context():
    ctx = {
        "account": {"name": "Alice", "phone": "+12345678"},
        "prev_output": "code_9876",
        "step": {1: {"output": "result_1"}},
    }
    assert (
        render_template("Hello {{ account.name }}, prev is {{ prev_output }}", ctx)
        == "Hello Alice, prev is code_9876"
    )
    assert (
        render_template("Step 1 output: {{ step[1].output }}", ctx)
        == "Step 1 output: result_1"
    )


def test_render_template_security_sandbox():
    # 禁止访问私有属性
    assert render_template("{{ ().__class__ }}") == "{{ ().__class__ }}"
    # 禁止调用 eval 或 os
    assert (
        render_template("{{ __import__('os').system('ls') }}")
        == "{{ __import__('os').system('ls') }}"
    )
    # 未定义变量保留原文本
    assert (
        render_template("Unknown: {{ nonexistent_var }}")
        == "Unknown: {{ nonexistent_var }}"
    )


def test_render_template_recursive():
    payload = {
        "text": "Date: {{ date }}",
        "nested": {
            "count": "{{ random_int(5, 5) }}",
            "items": ["prefix_{{ account.name }}"],
        },
        "number": 42,
    }
    rendered = render_template_recursive(payload, {"account": {"name": "Bob"}})
    assert rendered["nested"]["count"] == "5"
    assert rendered["nested"]["items"] == ["prefix_Bob"]
    assert rendered["number"] == 42


def test_render_template_unpacking_and_starred():
    # 字典解包 **kwargs / **dict
    res = render_template("{{ dict({'a': 1}, **extra)['b'] }}", {"extra": {"b": 99}})
    assert res == "99"

    # 函数调用 *args 解包
    res = render_template("{{ min(*nums) }}", {"nums": [10, 3, 25]})
    assert res == "3"

    # 列表与元组解包
    res = render_template("{{ [1, *(2, 3), 4] }}")
    assert res == "[1, 2, 3, 4]"


def test_render_template_recursive_tuple():
    payload = ("Hello {{ name }}", 123, ["nested {{ name }}"])
    res = render_template_recursive(payload, {"name": "World"})
    assert res == ("Hello World", 123, ["nested World"])


def test_render_template_convenience_aliases():
    now = datetime.datetime.now()
    res = render_template(
        "Year: {{ year }}, Month: {{ month }}, Day: {{ day }}, Weekday: {{ weekday }}"
    )
    assert f"Year: {now.year}" in res
    assert f"Month: {now.month:02d}" in res
    assert f"Day: {now.day:02d}" in res
    assert f"Weekday: {now.isoweekday()}" in res

    # randint 与 choice 别名
    assert render_template("{{ randint(7, 7) }}") == "7"
    assert render_template("{{ choice('single') }}") == "single"
    assert render_template("{{ sum([1, 2, 3, 4]) }}") == "10"


def test_render_template_custom_data_dict_resolver():
    from tg_signer.core.template import get_data_dict_resolver, set_data_dict_resolver

    prev_resolver = get_data_dict_resolver()
    try:
        set_data_dict_resolver(lambda name, mode: f"mocked_{name}_{mode}")
        res = render_template("Prefix {dict:greetings:round_robin} Suffix")
        assert res == "Prefix mocked_greetings_round_robin Suffix"
        res2 = render_template("Prefix {{ dict_entry('test', 'random') }} Suffix")
        assert res2 == "Prefix mocked_test_random Suffix"
    finally:
        set_data_dict_resolver(prev_resolver)


def test_render_template_extended_json_and_extract_builtins():
    # 测试 timestamp_ms
    res_ts = render_template("{{ timestamp_ms }}")
    assert res_ts.isdigit() and len(res_ts) >= 13

    # 测试 json_dumps 与 json_loads
    res_json = render_template("{{ json_dumps({'name': 'tg', 'val': 100}) }}")
    assert '"name": "tg"' in res_json
    assert '"val": 100' in res_json

    res_load = render_template("{{ json_loads('{\"score\": 99}')['score'] }}")
    assert res_load == "99"

    # 测试 extract 与 re_search
    sample_text = "Verification code is: 8848."
    res_ext = render_template("{{ extract(r'\\d{4}', text) }}", {"text": sample_text})
    assert res_ext == "8848"
    res_re = render_template(
        "{{ re_search(r'code is: (\\d+)', text, 1) }}", {"text": sample_text}
    )
    assert res_re == "8848"


def test_template_math_and_ternary_expressions():
    ctx = {"score": 85, "threshold": 60, "val": 15, "min_val": 10, "max_val": 20}

    # 算术运算函数
    assert render_template("{{ add(score, 5) }}", ctx) == "90"
    assert render_template("{{ sub(score, 10) }}", ctx) == "75"
    assert render_template("{{ mul(score, 2) }}", ctx) == "170"
    assert render_template("{{ div(100, 4) }}", ctx) == "25.0"
    assert render_template("{{ div(100, 0) }}", ctx) == "0"
    assert render_template("{{ mod(17, 5) }}", ctx) == "2"
    assert render_template("{{ clamp(25, 10, 20) }}", ctx) == "20"
    assert render_template("{{ clamp(5, 10, 20) }}", ctx) == "10"

    # 三元运算函数
    assert (
        render_template('{{ ternary(score >= threshold, "通过", "未通过") }}', ctx)
        == "通过"
    )
    assert (
        render_template('{{ iff(score < threshold, "通过", "未通过") }}', ctx)
        == "未通过"
    )

    # AST 三元语法支持
    assert render_template('{{ score >= 60 ? "及格" : "不及格" }}', ctx) == "及格"
    assert render_template('{{ "及格" if score >= 60 else "不及格" }}', ctx) == "及格"

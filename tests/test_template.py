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
    assert render_template("{{ __import__('os').system('ls') }}") == "{{ __import__('os').system('ls') }}"
    # 未定义变量保留原文本
    assert render_template("Unknown: {{ nonexistent_var }}") == "Unknown: {{ nonexistent_var }}"


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

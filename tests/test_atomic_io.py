"""backend/utils/atomic_io.py 单元测试。

覆盖：原子写回读、不可序列化数据失败时不残留 .tmp 文件、
损坏 JSON 读取回退默认值。
"""
from __future__ import annotations

import json

from backend.utils.atomic_io import read_json_safe, write_json_atomic


def test_write_atomic_and_read_back(tmp_path):
    target = tmp_path / "sub" / "cfg.json"
    write_json_atomic(target, {"a": 1, "b": [1, 2]})
    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1, "b": [1, 2]}


def test_write_atomic_no_tmp_leak_on_serialize_error(tmp_path):
    """不可序列化数据抛异常时不得残留 .tmp 文件。"""
    target = tmp_path / "bad.json"
    try:
        write_json_atomic(target, {"bad": object()})  # object() 不可 JSON 序列化
    except TypeError:
        pass
    else:
        raise AssertionError("expected TypeError")
    assert not target.exists()
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == [], f"残留临时文件: {leftovers}"


def test_read_safe_returns_default_on_corrupt(tmp_path):
    target = tmp_path / "corrupt.json"
    target.write_text("{not-json", encoding="utf-8")
    assert read_json_safe(target, default="fallback") == "fallback"


def test_read_safe_returns_default_on_missing(tmp_path):
    assert read_json_safe(tmp_path / "missing.json", default=[]) == []

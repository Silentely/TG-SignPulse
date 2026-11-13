from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Import DataDictService and helpers from backend.services.data_dict
from backend.services.data_dict import DataDictService
from tests.test_api import _auth, _login
from tg_signer.core.template import render_template, render_template_recursive

pytest_plugins = ("tests.test_api",)


def test_data_dict_save_and_list(tmp_path: Path):
    service = DataDictService(base_dir=tmp_path)
    entries = ["早上好", "中午好", "晚上好"]
    service.save_dict("greetings", entries, remark="日常问候语")

    dicts = service.list_dicts()
    assert len(dicts) == 1
    d = dicts[0]
    assert d["name"] == "greetings"
    assert d["count"] == 3
    assert d["remark"] == "日常问候语"
    assert "updated_at" in d

    detail = service.get_dict("greetings")
    assert detail["name"] == "greetings"
    assert detail["entries"] == entries
    assert detail["cursor"] == 0
    assert detail["remark"] == "日常问候语"
    assert "updated_at" in detail


def test_data_dict_random_returns_existing_entry(tmp_path: Path):
    service = DataDictService(base_dir=tmp_path)
    entries = ["Apple", "Banana", "Cherry"]
    service.save_dict("fruits", entries)

    for _ in range(20):
        entry = service.get_entry("fruits", mode="random")
        assert entry in entries


def test_data_dict_round_robin_wraps(tmp_path: Path):
    service = DataDictService(base_dir=tmp_path)
    entries = ["1", "2", "3"]
    service.save_dict("digits", entries)

    # 1 -> 2 -> 3 -> 1 -> 2
    assert service.get_entry("digits", mode="round_robin") == "1"
    assert service.get_entry("digits", mode="round_robin") == "2"
    assert service.get_entry("digits", mode="round_robin") == "3"
    assert service.get_entry("digits", mode="round_robin") == "1"
    assert service.get_entry("digits", mode="round_robin") == "2"

    # Test cursor persistence with a new service instance reading from disk
    service2 = DataDictService(base_dir=tmp_path)
    assert service2.get_entry("digits", mode="round_robin") == "3"
    assert service2.get_entry("digits", mode="round_robin") == "1"


def test_data_dict_rejects_invalid_name(tmp_path: Path):
    service = DataDictService(base_dir=tmp_path)
    invalid_names = [
        "",
        "hello world",
        "foo/bar",
        "foo\\bar",
        "foo.json",
        "@dict",
        "bad:name",
    ]
    for name in invalid_names:
        with pytest.raises(ValueError, match="INVALID_DICT_NAME"):
            service.save_dict(name, ["val"])


def test_data_dict_rejects_empty_entries(tmp_path: Path):
    service = DataDictService(base_dir=tmp_path)
    with pytest.raises(ValueError, match="DATA_DICT_EMPTY"):
        service.save_dict("empty1", [])

    with pytest.raises(ValueError, match="DATA_DICT_EMPTY"):
        service.save_dict("empty2", ["", "   ", "\n", "\t"])


def test_template_resolves_dict_macro(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    service = DataDictService(base_dir=tmp_path)
    service.save_dict("cheers", ["Cheers", "Salute"])

    # Monkeypatch the singleton accessor to return our test service
    import backend.services.data_dict as dd_module

    monkeypatch.setattr(dd_module, "get_data_dict_service", lambda: service)

    # Test random macro
    res_rand = render_template("Drink: {dict:cheers}")
    assert res_rand in ("Drink: Cheers", "Drink: Salute")

    # Test round_robin macro sequence
    assert render_template("Round: {dict:cheers:round_robin}") == "Round: Cheers"
    assert render_template("Round: {dict:cheers:round_robin}") == "Round: Salute"
    assert render_template("Round: {dict:cheers:round_robin}") == "Round: Cheers"

    # Test context dict_entry builtin
    ctx_res = render_template('Context: {{ dict_entry("cheers", mode="round_robin") }}')
    assert ctx_res == "Context: Salute"

    # Test fallback on nonexistent dict
    assert render_template("Hello {dict:nonexistent}") == "Hello {dict:nonexistent}"

    # Test recursive rendering with dict macro
    nested = {
        "msg": "Send: {dict:cheers:round_robin}",
        "sub": ["Item: {dict:cheers:round_robin}"],
    }
    rendered_nested = render_template_recursive(nested)
    assert rendered_nested["msg"] == "Send: Cheers"
    assert rendered_nested["sub"] == ["Item: Salute"]


def test_data_dict_api_routes(
    api_client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Setup data_dict service using tmp_path
    service = DataDictService(base_dir=tmp_path)
    import backend.api.routes.data_dict as data_dict_routes

    monkeypatch.setattr(data_dict_routes, "get_data_dict_service", lambda: service)

    # 1. Unauthenticated request should return 401
    resp = api_client.get("/api/data-dict")
    assert resp.status_code == 401

    # 2. Authenticated user
    token = _login(api_client)
    headers = _auth(token)

    # List empty
    resp = api_client.get("/api/data-dict", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []

    # Create with invalid name -> 400
    resp = api_client.post(
        "/api/data-dict",
        headers=headers,
        json={"name": "invalid name!", "entries": ["a", "b"]},
    )
    assert resp.status_code == 400

    # Create with empty entries -> 400
    resp = api_client.post(
        "/api/data-dict",
        headers=headers,
        json={"name": "empty_dict", "entries": ["   ", ""]},
    )
    assert resp.status_code == 400

    # Create valid dictionary
    resp = api_client.post(
        "/api/data-dict",
        headers=headers,
        json={
            "name": "quotes",
            "entries": ["To be, or not to be", "Knowledge is power"],
            "remark": "Famous quotes",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True

    # List dictionaries
    resp = api_client.get("/api/data-dict", headers=headers)
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["name"] == "quotes"
    assert items[0]["count"] == 2
    assert items[0]["remark"] == "Famous quotes"

    # Get details
    resp = api_client.get("/api/data-dict/quotes", headers=headers)
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["name"] == "quotes"
    assert detail["entries"] == ["To be, or not to be", "Knowledge is power"]
    assert detail["remark"] == "Famous quotes"

    # Sample random
    resp = api_client.get("/api/data-dict/quotes/sample?mode=random", headers=headers)
    assert resp.status_code == 200
    sample_data = resp.json()
    assert sample_data["name"] == "quotes"
    assert sample_data["entry"] in ["To be, or not to be", "Knowledge is power"]

    # Sample round-robin
    resp1 = api_client.get(
        "/api/data-dict/quotes/sample?mode=round_robin", headers=headers
    )
    resp2 = api_client.get(
        "/api/data-dict/quotes/sample?mode=round_robin", headers=headers
    )
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["entry"] == "To be, or not to be"
    assert resp2.json()["entry"] == "Knowledge is power"

    # Delete dictionary
    resp = api_client.delete("/api/data-dict/quotes", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Get deleted dictionary -> 404
    resp = api_client.get("/api/data-dict/quotes", headers=headers)
    assert resp.status_code == 404


def test_builtin_dict_presets_listed_and_referenced(tmp_path: Path):
    service = DataDictService(base_dir=tmp_path)

    builtins = service.list_builtin_dicts()
    assert [item["name"] for item in builtins] == [
        "greetings",
        "checkin",
        "blessings",
        "thanks",
        "chitchat",
    ]
    assert all(item["exists"] is False for item in builtins)
    assert all(item["entries"] for item in builtins)

    created = service.create_from_builtin("greetings")
    assert created["name"] == "greetings"
    assert created["entries"]
    assert service.list_dicts() == [
        {
            "name": "greetings",
            "count": len(created["entries"]),
            "remark": created["remark"],
            "updated_at": created["updated_at"],
        }
    ]

    refreshed = {item["name"]: item for item in service.list_builtin_dicts()}
    assert refreshed["greetings"]["exists"] is True
    assert refreshed["checkin"]["exists"] is False


def test_builtin_dict_reference_does_not_overwrite_user_dict(tmp_path: Path):
    service = DataDictService(base_dir=tmp_path)
    service.save_dict("greetings", ["自定义问候"])

    with pytest.raises(ValueError, match="DATA_DICT_EXISTS"):
        service.create_from_builtin("greetings")

    assert service.get_dict("greetings")["entries"] == ["自定义问候"]


def test_builtin_dict_rejects_unknown_name(tmp_path: Path):
    service = DataDictService(base_dir=tmp_path)
    with pytest.raises(ValueError, match="BUILTIN_DICT_NOT_FOUND"):
        service.create_from_builtin("not-a-preset")


def test_builtin_dict_api_routes(
    api_client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    service = DataDictService(base_dir=tmp_path)
    import backend.api.routes.data_dict as data_dict_routes

    monkeypatch.setattr(data_dict_routes, "get_data_dict_service", lambda: service)

    resp = api_client.get("/api/data-dict-presets")
    assert resp.status_code == 401

    token = _login(api_client)
    headers = _auth(token)

    resp = api_client.get("/api/data-dict-presets", headers=headers)
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 5
    assert all(item["exists"] is False for item in items)

    resp = api_client.post("/api/data-dict-presets/greetings", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "greetings"

    resp = api_client.post("/api/data-dict-presets/greetings", headers=headers)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "DATA_DICT_EXISTS"

    resp = api_client.post("/api/data-dict-presets/unknown", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "BUILTIN_DICT_NOT_FOUND"

    resp = api_client.get("/api/data-dict", headers=headers)
    assert resp.status_code == 200
    assert [item["name"] for item in resp.json()] == ["greetings"]


def test_builtin_presets_do_not_shadow_user_dict_routes(
    api_client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    service = DataDictService(base_dir=tmp_path)
    service.save_dict("builtins", ["用户自己的字典"])
    import backend.api.routes.data_dict as data_dict_routes

    monkeypatch.setattr(data_dict_routes, "get_data_dict_service", lambda: service)

    token = _login(api_client)
    headers = _auth(token)

    # 预设使用独立路径，用户仍可通过常规详情接口读取同名自定义字典
    resp = api_client.get("/api/data-dict/builtins", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "builtins"
    assert resp.json()["entries"] == ["用户自己的字典"]

    resp = api_client.get("/api/data-dict-presets", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 5


def test_data_dict_null_byte_filtering_and_negative_cursor(tmp_path: Path):
    service = DataDictService(base_dir=tmp_path)
    # 含有 null 字节与空白
    entries = ["hello\x00world", "  \x00  ", "safe"]
    service.save_dict("cleantest", entries)
    d = service.get_dict("cleantest")
    assert d["entries"] == ["helloworld", "safe"]

    # 模拟人为或异常写入负数游标
    file_path = tmp_path / "data_dicts" / "cleantest.json"
    from backend.utils.atomic_io import read_json_safe, write_json_atomic

    data = read_json_safe(file_path)
    data["cursor"] = -5
    write_json_atomic(file_path, data)

    # 抽取时不崩溃且安全返回
    entry = service.get_entry("cleantest", mode="round_robin")
    assert entry in ("helloworld", "safe")


def test_get_entry_records_usage_and_stats_api(tmp_path: Path):
    service = DataDictService(base_dir=tmp_path)
    service.save_dict("greetings", ["你好", "早上好"])
    service.save_dict("fruits", ["苹果", "香蕉"])

    # random 与 round_robin 抽取都计入统计
    service.get_entry("greetings", mode="random")
    service.get_entry("greetings", mode="round_robin")
    service.get_entry("greetings", mode="round_robin")
    service.get_entry("fruits", mode="random")

    stats = service.get_usage_stats()
    assert stats["greetings"]["count"] == 3
    assert stats["fruits"]["count"] == 1
    assert stats["greetings"]["last_used"]
    assert "quotes" not in stats


def test_get_entry_record_false_skips_stats(tmp_path: Path):
    service = DataDictService(base_dir=tmp_path)
    service.save_dict("fruits", ["苹果"])

    service.get_entry("fruits", mode="random", record=False)
    service.get_entry("fruits", mode="random", record=False)

    stats = service.get_usage_stats()
    assert stats == {}


def test_usage_stats_persist_across_reload_and_delete(tmp_path: Path):
    service = DataDictService(base_dir=tmp_path)
    service.save_dict("greetings", ["你好"])
    service.get_entry("greetings", mode="random")
    service.get_entry("greetings", mode="random")
    # 读取统计会触发一次落盘
    assert service.get_usage_stats()["greetings"]["count"] == 2

    # 新实例从磁盘加载统计
    service2 = DataDictService(base_dir=tmp_path)
    assert service2.get_usage_stats()["greetings"]["count"] == 2

    service2.delete_dict("greetings")
    stats = service2.get_usage_stats()
    assert "greetings" not in stats


def test_list_and_stats_exclude_stats_file(tmp_path: Path):
    service = DataDictService(base_dir=tmp_path)
    service.save_dict("greetings", ["你好"])
    service.get_entry("greetings", mode="random")

    names = [d["name"] for d in service.list_dicts()]
    assert names == ["greetings"]


def test_data_dict_stats_api_routes(
    api_client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    service = DataDictService(base_dir=tmp_path)
    import backend.api.routes.data_dict as data_dict_routes

    monkeypatch.setattr(data_dict_routes, "get_data_dict_service", lambda: service)

    # 未登录 -> 401
    assert api_client.get("/api/data-dict/stats").status_code == 401

    token = _login(api_client)
    headers = _auth(token)

    # 无字典时返回空统计
    resp = api_client.get("/api/data-dict/stats", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["dicts"] == {}
    assert resp.json()["total"] == 0

    # 正常取词后统计有值
    service.save_dict("greetings", ["你好"])
    service.get_entry("greetings", mode="random")
    resp = api_client.get("/api/data-dict/stats", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["dicts"]["greetings"]["count"] == 1

    # 采样接口不污染统计
    api_client.get("/api/data-dict/greetings/sample?mode=random", headers=headers)
    resp = api_client.get("/api/data-dict/stats", headers=headers)
    assert resp.json()["dicts"]["greetings"]["count"] == 1

    # /stats 不会与 /{name} 路由冲突
    resp = api_client.get("/api/data-dict/nonexistent", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "DATA_DICT_NOT_FOUND"

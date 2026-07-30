"""sign_task_chats 纯函数测试。"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.services.sign_task_chats import (
    empty_chat_search_page,
    load_chats_cache_file,
    map_pyrogram_chat,
    save_chats_cache_file,
    search_chats_in_cache,
)


def test_empty_page_clamps_limit():
    page = empty_chat_search_page(limit=0, offset=-3)
    assert page["limit"] == 1
    assert page["offset"] == 0
    assert page["items"] == []


def test_search_by_title_and_username():
    data = [
        {"id": 1, "title": "签到群", "username": "checkin"},
        {"id": 2, "title": "Other", "username": "foo"},
    ]
    res = search_chats_in_cache(data, "签到", limit=10, offset=0)
    assert res["total"] == 1
    assert res["items"][0]["id"] == 1
    res2 = search_chats_in_cache(data, "FOO", limit=10, offset=0)
    assert res2["total"] == 1
    assert res2["items"][0]["id"] == 2


def test_search_by_numeric_id():
    data = [
        {"id": -100123, "title": "A", "username": None},
        {"id": 42, "title": "B", "username": None},
    ]
    res = search_chats_in_cache(data, "-100", limit=10, offset=0)
    assert res["total"] == 1
    assert res["items"][0]["id"] == -100123
    res2 = search_chats_in_cache(data, "42", limit=10, offset=0)
    assert res2["total"] == 1


def test_search_pagination_and_empty_query():
    data = [{"id": i, "title": f"t{i}", "username": None} for i in range(5)]
    res = search_chats_in_cache(data, "", limit=2, offset=2)
    assert res["total"] == 5
    assert [c["id"] for c in res["items"]] == [2, 3]


def test_search_invalid_data_returns_empty():
    res = search_chats_in_cache({"not": "list"}, "x", limit=5, offset=0)
    assert res["total"] == 0
    assert res["items"] == []


def test_map_pyrogram_chat():
    chat = SimpleNamespace(
        id=99,
        title="Hello",
        username="hello",
        type=SimpleNamespace(name="SUPERGROUP"),
        first_name=None,
    )
    mapped = map_pyrogram_chat(chat)
    assert mapped == {
        "id": 99,
        "title": "Hello",
        "username": "hello",
        "type": "supergroup",
    }
    assert map_pyrogram_chat(None) is None
    assert map_pyrogram_chat(SimpleNamespace(id=None)) is None


def test_resolve_telegram_api_credentials():
    from backend.services.telegram.credentials import resolve_telegram_api_credentials

    api_id, api_hash = resolve_telegram_api_credentials(
        {"api_id": "123", "api_hash": " abc "},
    )
    assert api_id == 123
    assert api_hash == "abc"
    with pytest.raises(ValueError):
        resolve_telegram_api_credentials({})


@pytest.mark.parametrize(
    ("tg_config", "env_id", "env_hash", "expected"),
    [
        # env 优先于配置
        ({"api_id": "111", "api_hash": "cfg"}, "222", "env", (222, "env")),
        # env 仅部分提供时，另一半回退配置
        ({"api_id": "111", "api_hash": "cfg"}, "222", None, (222, "cfg")),
        ({"api_id": "111", "api_hash": "cfg"}, None, "env", (111, "env")),
        # int 型 api_id 原样可用，返回类型统一为 (int, str)
        ({"api_id": 42, "api_hash": "h"}, None, None, (42, "h")),
    ],
)
def test_resolve_telegram_api_credentials_precedence(tg_config, env_id, env_hash, expected):
    from backend.services.telegram.credentials import resolve_telegram_api_credentials

    assert (
        resolve_telegram_api_credentials(
            tg_config, env_api_id=env_id, env_api_hash=env_hash
        )
        == expected
    )


@pytest.mark.parametrize(
    ("tg_config", "env_id", "env_hash"),
    [
        # api_id 为 0 / "0"（Telegram 合法 id 从 1 起，0 视为无效）
        ({"api_id": 0, "api_hash": "h"}, None, None),
        ({"api_id": "0", "api_hash": "h"}, None, None),
        # 非数字 id
        ({"api_id": "abc", "api_hash": "h"}, None, None),
        # hash 缺失 / 空串 / 纯空白
        ({"api_id": "1"}, None, None),
        ({"api_id": "1", "api_hash": ""}, None, None),
        ({"api_id": "1", "api_hash": "   "}, None, None),
    ],
)
def test_resolve_telegram_api_credentials_rejects_invalid(tg_config, env_id, env_hash):
    from backend.services.telegram.credentials import resolve_telegram_api_credentials

    with pytest.raises(ValueError):
        resolve_telegram_api_credentials(
            tg_config, env_api_id=env_id, env_api_hash=env_hash
        )


def test_resolve_account_session_string_mode(tmp_path: Path):
    from backend.services.sign_task_chats import resolve_account_session_for_chats

    info = resolve_account_session_for_chats(
        "acc1",
        session_dir=tmp_path,
        session_mode="string",
        get_session_string=lambda n: "sess-token",
        load_session_string_file_fn=lambda d, n: None,
    )
    assert info["session_string"] == "sess-token"
    assert info["used_fallback_session"] is False


def test_load_save_cache_roundtrip(tmp_path: Path):
    path = tmp_path / "acc" / "chats_cache.json"
    chats = [{"id": 1, "title": "A", "username": None, "type": "private"}]
    assert save_chats_cache_file(path, chats) is True
    loaded = load_chats_cache_file(path)
    assert loaded == chats
    assert load_chats_cache_file(tmp_path / "missing.json") is None

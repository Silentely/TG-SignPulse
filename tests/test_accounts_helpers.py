"""accounts_helpers 纯函数测试。"""

from __future__ import annotations

import pytest

from backend.api.routes.accounts_helpers import (
    build_status_check_error_item,
    clamp_status_check_timeout,
    find_account_by_name,
    normalize_unique_account_names,
    resolve_account_rename_target,
)


def test_normalize_unique_account_names():
    assert normalize_unique_account_names([" a ", "a", "", "b", "b "]) == ["a", "b"]
    assert normalize_unique_account_names(None, fallback_names=["x", "x", "y"]) == [
        "x",
        "y",
    ]
    assert normalize_unique_account_names([]) == []


def test_clamp_status_check_timeout():
    assert clamp_status_check_timeout(0) == 1.0
    assert clamp_status_check_timeout(100) == 20.0
    assert clamp_status_check_timeout(None) == 8.0
    assert clamp_status_check_timeout("bad") == 8.0
    assert clamp_status_check_timeout(6.5) == 6.5


def test_build_status_check_error_item():
    item = build_status_check_error_item("acc", RuntimeError("boom"))
    assert item["account_name"] == "acc"
    assert item["ok"] is False
    assert item["code"] == "STATUS_CHECK_FAILED"
    assert "boom" in item["message"]


def test_resolve_account_rename_target():
    assert resolve_account_rename_target("old", None) == ("old", False)
    assert resolve_account_rename_target("old", "  ") == ("old", False)
    assert resolve_account_rename_target("old", "new") == ("new", True)


def test_find_account_by_name():
    accounts = [{"name": "Alice"}, {"name": "bob"}]
    assert find_account_by_name(accounts, "alice")["name"] == "Alice"
    assert find_account_by_name(accounts, "missing") is None


def test_qr_uri_to_data_url_empty():
    from backend.api.routes.accounts_helpers import qr_uri_to_data_url

    assert qr_uri_to_data_url("") is None
    # qrcode may or may not be installed; if present returns data url
    out = qr_uri_to_data_url("tg://login?token=abc")
    if out is not None:
        assert out.startswith("data:image/png;base64,")


def test_extract_last_bot_message_prefers_stored_field():
    """accounts 路由依赖该 helper；import * 不会带入下划线私有名。"""
    from backend.api.routes import accounts
    from backend.api.routes.accounts_schemas import _extract_last_bot_message

    assert hasattr(accounts, "_extract_last_bot_message")
    assert _extract_last_bot_message({"last_target_message": "  已签到  "}) == "已签到"
    assert (
        _extract_last_bot_message({"flow_logs": ["任务对象最后一条消息: 签到成功"]})
        == "签到成功"
    )
    assert _extract_last_bot_message({}) == ""


def test_natural_sort_key():
    from backend.utils.names import natural_sort_key

    names = ["11", "1", "9", "账号11", "账号9", "账号1"]
    sorted_names = sorted(names, key=natural_sort_key)
    assert sorted_names == ["1", "9", "11", "账号1", "账号9", "账号11"]


@pytest.mark.asyncio
async def test_safe_close_client_handles_uninitialized_client():
    from tg_signer.core.client import _safe_close_client

    class UninitializedClient:
        def __init__(self):
            self.is_connected = True
            self.is_initialized = False
            self.disconnected = False
            self.stopped = False

        async def stop(self):
            self.stopped = True
            raise ConnectionError("Client is already terminated")

        async def disconnect(self):
            self.disconnected = True

    client = UninitializedClient()
    await _safe_close_client(client)
    assert client.stopped is False
    assert client.disconnected is True


@pytest.mark.asyncio
async def test_safe_close_client_handles_initialized_client():
    from tg_signer.core.client import _safe_close_client

    class InitializedClient:
        def __init__(self):
            self.is_connected = True
            self.is_initialized = True
            self.stopped = False

        async def stop(self):
            self.stopped = True

        async def disconnect(self):
            pass

    client = InitializedClient()
    await _safe_close_client(client)
    assert client.stopped is True

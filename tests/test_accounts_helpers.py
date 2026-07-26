"""accounts_helpers 纯函数测试。"""
from __future__ import annotations

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

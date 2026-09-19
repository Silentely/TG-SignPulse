"""单元测试：设备指纹画像池与账号持久化绑定。

测试覆盖：
1. 预设池画像结构完整性及随机生成校验
2. 跨平台防穿崩校验（如 Windows 平台配置 iPhone 机型必须拒绝）
3. 账号启动及 _build_account_client 时正确注入绑定的设备指纹画像
4. 设备指纹在 accounts.json 中的持久化保存与读取
5. 账号在线/活跃时修改设备画像的安全保护 (HTTP 409 / ACCOUNT_BUSY)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.services.telegram.accounts import TelegramAccountsMixin
from backend.services.telegram.device_profiles import (
    DEVICE_PRESET_POOL,
    get_random_profile,
    validate_device_profile,
)
from backend.utils.tg_session import get_account_profile, set_account_profile
from tests.test_api import _auth, _login
from tg_signer.core.client import _CLIENT_REFS

pytest_plugins = ("tests.test_api",)


def test_get_random_profile_matches_family_preset():
    """验证从指定 family 中随机获取的画像符合预设结构与规范。"""
    for family in ("desktop", "android", "macos", "ios"):
        profile = get_random_profile(family)
        assert profile is not None
        assert profile.get("device_family") == family
        assert "device_model" in profile and profile["device_model"]
        assert "system_version" in profile and profile["system_version"]
        assert "app_version" in profile and profile["app_version"]
        assert "lang_code" in profile and profile["lang_code"]
        assert "system_lang_code" in profile and profile["system_lang_code"]

        # 验证机型在预设池中
        models = [p["device_model"] for p in DEVICE_PRESET_POOL[family]]
        assert profile["device_model"] in models


def test_validate_device_profile_rejects_cross_family_mismatch():
    """验证跨平台冲突校验：例如桌面端配置了手机机型，或系统版本与机型不匹配。"""
    # 合法 profile 应验证通过并返回
    valid_android = {
        "device_family": "android",
        "device_model": "Samsung SM-S918B",
        "system_version": "SDK 34",
        "app_version": "11.1.3 (5234)",
        "lang_code": "en",
        "system_lang_code": "en",
    }
    validated = validate_device_profile(valid_android)
    assert validated["device_model"] == "Samsung SM-S918B"

    # 冲突：iPhone 机型但标注 device_family 为 desktop
    conflicting_profile = {
        "device_family": "desktop",
        "device_model": "iPhone 15 Pro",
        "system_version": "Windows 11",
        "app_version": "5.4.1 x64",
        "lang_code": "en",
        "system_lang_code": "en-US",
    }
    with pytest.raises(ValueError, match="Cross-family"):
        validate_device_profile(conflicting_profile)

    # 冲突：PC 桌面机型但标注系统为 iOS
    conflicting_system = {
        "device_family": "desktop",
        "device_model": "PC 64bit",
        "system_version": "iOS 17.5.1",
        "app_version": "5.4.1 x64",
        "lang_code": "en",
        "system_lang_code": "en-US",
    }
    with pytest.raises(ValueError, match="Cross-family"):
        validate_device_profile(conflicting_system)


def test_build_account_client_injects_device_profile(tmp_path, monkeypatch):
    """验证 _build_account_client 从 profile 提取设备画像并注入 get_client。"""
    session_dir = tmp_path / "sessions"
    session_dir.mkdir(parents=True)
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))

    # 创建虚拟 session 文件
    session_file = session_dir / "test_acc.session"
    session_file.write_text("dummy session")

    account_name = "test_acc"
    custom_profile = {
        "device_model": "Samsung SM-S918B",
        "system_version": "SDK 34",
        "app_version": "11.1.3 (5234)",
        "lang_code": "en",
        "system_lang_code": "en",
    }
    set_account_profile(
        account_name,
        device_family="android",
        device_profile=custom_profile,
    )

    class DummyService(TelegramAccountsMixin):
        def __init__(self, s_dir: Path):
            self.session_dir = s_dir
            self._accounts_cache = None

    svc = DummyService(session_dir)

    with patch("tg_signer.core.get_client") as mock_get_client:
        mock_get_client.return_value = MagicMock()
        client, proxy = svc._build_account_client(account_name)

        mock_get_client.assert_called_once()
        kwargs = mock_get_client.call_args.kwargs
        assert kwargs.get("device_model") == "Samsung SM-S918B"
        assert kwargs.get("system_version") == "SDK 34"
        assert kwargs.get("app_version") == "11.1.3 (5234)"
        assert kwargs.get("lang_code") == "en"
        assert kwargs.get("system_lang_code") == "en"


def test_device_profile_persisted_in_account_profile(tmp_path, monkeypatch):
    """验证设备画像能正确持久化至 accounts.json 并被 list_accounts 读取。"""
    session_dir = tmp_path / "sessions"
    session_dir.mkdir(parents=True)
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))

    account_name = "persist_acc"
    (session_dir / f"{account_name}.session").write_text("session")

    profile_data = {
        "device_model": "MacBook Pro",
        "system_version": "macOS 14.5",
        "app_version": "10.15.1",
        "lang_code": "en",
        "system_lang_code": "en-US",
    }
    set_account_profile(
        account_name,
        device_family="macos",
        device_profile=profile_data,
    )

    stored = get_account_profile(account_name)
    assert stored.get("device_family") == "macos"
    assert stored.get("device_profile") == profile_data

    class DummyService(TelegramAccountsMixin):
        def __init__(self, s_dir: Path):
            self.session_dir = s_dir
            self._accounts_cache = None

    svc = DummyService(session_dir)
    accounts = svc.list_accounts(force_refresh=True)
    matched = next((a for a in accounts if a["name"] == account_name), None)
    assert matched is not None
    assert matched.get("device_family") == "macos"
    assert matched.get("device_profile") == profile_data


def test_update_account_device_profile_refuses_when_client_active(api_client, db, monkeypatch):
    """验证 Client 处于活跃引用 (_CLIENT_REFS > 0) 时，修改设备画像返回 HTTP 409 (ACCOUNT_BUSY)。"""
    from backend.services.telegram import get_telegram_service

    service = get_telegram_service()
    session_dir = service.session_dir
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "busy_acc.session").write_text("dummy")

    client = api_client
    token = _login(client)
    headers = _auth(token)

    # 模拟 Client 活跃引用
    _CLIENT_REFS["busy_acc"] = 1
    try:
        resp = client.patch(
            "/api/accounts/busy_acc",
            headers=headers,
            json={"device_family": "android"},
        )
        assert resp.status_code == 409
        assert resp.json().get("detail") == "ACCOUNT_BUSY"
    finally:
        _CLIENT_REFS.pop("busy_acc", None)

    # 当无活跃引用时，更新成功
    resp2 = client.patch(
        "/api/accounts/busy_acc",
        headers=headers,
        json={"device_family": "android"},
    )
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["success"] is True
    assert data["account"]["device_family"] == "android"
    assert data["account"]["device_profile"] is not None

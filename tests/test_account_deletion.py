"""账号删除（TelegramAccountsMixin.delete_account）回归测试。

覆盖三类容易回归的清理语义：
1. 仅存在于账号库（accounts.json）中的账号仍可删除，避免备注/代理/标签/设备画像永久残留；
2. 登录中会话（手机号/扫码轮询记录）随账号一并清理，避免账号删除后仍出现在列表；
3. .session_string 缓存文件与当前会话模式解耦清理，避免模式切换后残留。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.core.config import get_settings
from backend.services.telegram.accounts import TelegramAccountsMixin
from backend.services.telegram.sessions import _login_sessions, _qr_login_sessions
from backend.utils.tg_session import (
    _account_store_cache,
    get_account_profile,
    list_account_names,
    set_account_profile,
)


class DummyAccountService(TelegramAccountsMixin):
    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        self._accounts_cache = None

    def _normalize_account_name(self, name: str) -> str:
        return name


@pytest.fixture(autouse=True)
def reset_store():
    _account_store_cache.clear()
    get_settings.cache_clear()
    _login_sessions.clear()
    _qr_login_sessions.clear()
    yield
    _account_store_cache.clear()
    get_settings.cache_clear()
    _login_sessions.clear()
    _qr_login_sessions.clear()


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    session_dir = tmp_path / "sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    return DummyAccountService(session_dir)


def _patch_close_client():
    return patch("tg_signer.core.close_client_by_name", new_callable=AsyncMock)


@pytest.mark.asyncio
async def test_delete_account_removes_store_only_account(service):
    """仅存在于账号库、没有 session 文件的账号也必须可删除。"""
    set_account_profile("ghost", remark="遗留备注", proxy="socks5://127.0.0.1:1080")
    assert "ghost" in list_account_names()
    assert not (service.session_dir / "ghost.session").exists()

    with _patch_close_client():
        assert await service.delete_account("ghost") is True

    assert "ghost" not in list_account_names()
    assert get_account_profile("ghost") == {}


@pytest.mark.asyncio
async def test_delete_account_purges_pending_login_records(service):
    """删除账号时必须清理登录中会话，否则账号会继续出现在账号列表中。"""
    (service.session_dir / "acc_pending.session").write_bytes(b"sqlite")
    class _MockLoginClient:
        def __init__(self):
            self.is_initialized = True
            self.stopped = False
        async def stop(self):
            self.stopped = True

    mock_c = _MockLoginClient()
    _login_sessions["acc_pending_+8613800000000"] = {
        "account_name": "acc_pending",
        "client": mock_c,
    }
    _qr_login_sessions["qr-login-1"] = {
        "account_name": "acc_pending",
        "status": "waiting",
    }

    with _patch_close_client():
        assert await service.delete_account("acc_pending") is True

    assert _login_sessions == {}
    assert _qr_login_sessions == {}
    assert mock_c.stopped is True


@pytest.mark.asyncio
async def test_delete_account_cleans_session_string_file_regardless_of_mode(service):
    """.session_string 残留与当前会话模式无关，必须一并清理。"""
    (service.session_dir / "acc_str.session").write_bytes(b"sqlite")
    (service.session_dir / "acc_str.session_string").write_text("dummy", encoding="utf-8")

    with _patch_close_client():
        assert await service.delete_account("acc_str") is True

    assert not (service.session_dir / "acc_str.session").exists()
    assert not (service.session_dir / "acc_str.session_string").exists()


@pytest.mark.asyncio
async def test_delete_account_returns_false_when_nothing_to_delete(service):
    """无任何痕迹时返回 False，供路由映射 404 ACCOUNT_NOT_FOUND。"""
    with _patch_close_client():
        assert await service.delete_account("never_existed") is False

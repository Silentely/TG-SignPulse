"""登录流程账号锁所有权（AccountLockLease）回归测试。

覆盖的核心不变式：**本次流程未获取的锁绝不释放**。
登录流程跨 HTTP 请求复用同一把账号锁，后一个请求无法从 ``lock.locked()``
区分「本流程持有」与「他人持有」。修复前 ``_release_account_lock`` 只看
``locked()``，会把他人正在使用的锁提前放开，导致两个协程同时写 session。
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.telegram.login_phone import TelegramPhoneLoginMixin
from backend.services.telegram.login_qr import TelegramQrLoginMixin
from backend.services.telegram.sessions import (
    _login_sessions,
    _qr_login_sessions,
    _release_login_session,
)
from backend.utils.account_locks import AccountLockLease, get_account_lock


class _SemaphoreStub:
    """替代全局并发信号量，避免受其它用例影响。"""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeLoginClient:
    def __init__(self, connected: bool = True):
        self.is_connected = connected
        self.connect_calls = 0
        self.disconnect_calls = 0

    async def connect(self):
        self.connect_calls += 1
        self.is_connected = True

    async def disconnect(self):
        self.disconnect_calls += 1
        self.is_connected = False

    async def sign_in(self, *args, **kwargs):
        raise RuntimeError("boom")

    async def get_me(self):
        raise AssertionError("不应进入成功分支")


class _PhoneService(TelegramPhoneLoginMixin):
    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        self._accounts_cache = None

    def _normalize_account_name(self, name: str) -> str:
        return name

    async def verify_account_proxy(self, account_name, proxy_dict):
        return None

    async def _persist_client_session(self, client, account_name, proxy=None):
        return None


class _QrService(TelegramQrLoginMixin):
    def __init__(self, session_dir: Path):
        self.session_dir = session_dir

    def _normalize_account_name(self, name: str) -> str:
        return name

    def _log_qr_state(self, login_id, state, data=None):
        pass


@pytest.fixture(autouse=True)
def clean_session_stores():
    _login_sessions.clear()
    _qr_login_sessions.clear()
    yield
    _login_sessions.clear()
    _qr_login_sessions.clear()


@pytest.fixture
def phone_service(tmp_path):
    return _PhoneService(tmp_path)


@pytest.fixture
def qr_service(tmp_path):
    return _QrService(tmp_path)


@pytest.mark.asyncio
async def test_release_login_session_skips_unowned_lease():
    """会话被他人接管后，清理路径不得释放别人的锁。"""
    lock = asyncio.Lock()
    await lock.acquire()
    lease = AccountLockLease(lock)  # 未 mark_owned：锁属于其他协程

    await _release_login_session({"lock": lock, "lock_lease": lease})

    assert lock.locked() is True


@pytest.mark.asyncio
async def test_release_login_session_releases_owned_lease():
    """本流程持有的锁由清理路径正常释放。"""
    lock = asyncio.Lock()
    await lock.acquire()
    lease = AccountLockLease(lock)
    lease.mark_owned()

    await _release_login_session({"lock": lock, "lock_lease": lease})

    assert lock.locked() is False


@pytest.mark.asyncio
async def test_release_login_session_falls_back_without_lease():
    """无租约的旧会话结构仍按 locked() 兜底释放。"""
    lock = asyncio.Lock()
    await lock.acquire()

    await _release_login_session({"lock": lock})

    assert lock.locked() is False


@pytest.mark.asyncio
async def test_verify_login_keeps_foreign_lock_locked(phone_service):
    """续接请求发现锁被他人持有时，失败清理不得释放该锁。"""
    account = "lease_verify_foreign"
    lock = get_account_lock(account)
    client = _FakeLoginClient()

    # 其他协程持有锁：本流程的租约未标记 owned
    await lock.acquire()
    _login_sessions[f"{account}_+8613800000000"] = {
        "client": client,
        "phone_code_hash": "hash",
        "phone_number": "+8613800000000",
        "lock": lock,
        "lock_lease": AccountLockLease(lock),
        "account_name": account,
    }

    with patch(
        "backend.services.telegram.login_phone.get_global_semaphore",
        return_value=_SemaphoreStub(),
    ):
        with pytest.raises(ValueError):
            await phone_service.verify_login(
                account, "+8613800000000", "12345", "hash"
            )

    # 他人的锁仍在，会话已被清理
    assert lock.locked() is True
    assert _login_sessions == {}
    assert client.disconnect_calls == 1

    lock.release()


@pytest.mark.asyncio
async def test_verify_login_reacquires_free_lock(phone_service):
    """锁已空闲时续接请求自行获取，并在结束后释放。"""
    account = "lease_verify_free"
    lock = get_account_lock(account)
    client = _FakeLoginClient()
    lease = AccountLockLease(lock)

    _login_sessions[f"{account}_+8613800000000"] = {
        "client": client,
        "phone_code_hash": "hash",
        "phone_number": "+8613800000000",
        "lock": lock,
        "lock_lease": lease,
        "account_name": account,
    }

    with patch(
        "backend.services.telegram.login_phone.get_global_semaphore",
        return_value=_SemaphoreStub(),
    ):
        with pytest.raises(ValueError):
            await phone_service.verify_login(
                account, "+8613800000000", "12345", "hash"
            )

    assert lock.locked() is False
    assert _login_sessions == {}


@pytest.mark.asyncio
async def test_verify_login_keeps_lock_across_2fa_roundtrip(phone_service):
    """2FA 缺密码时报错但保留会话，锁必须仍由本流程持有。"""
    from pyrogram.errors import SessionPasswordNeeded

    account = "lease_verify_2fa"
    lock = get_account_lock(account)

    class _NeedPasswordClient(_FakeLoginClient):
        async def sign_in(self, *args, **kwargs):
            raise SessionPasswordNeeded()

    client = _NeedPasswordClient()
    lease = AccountLockLease(lock)
    lease.mark_owned()

    _login_sessions[f"{account}_+8613800000000"] = {
        "client": client,
        "phone_code_hash": "hash",
        "phone_number": "+8613800000000",
        "lock": lock,
        "lock_lease": lease,
        "account_name": account,
    }

    with patch(
        "backend.services.telegram.login_phone.get_global_semaphore",
        return_value=_SemaphoreStub(),
    ):
        with pytest.raises(ValueError, match="两步验证"):
            await phone_service.verify_login(
                account, "+8613800000000", "12345", "hash"
            )

    # 会话保留 → 锁继续由本流程持有，供下一次提交 2FA 密码使用
    assert f"{account}_+8613800000000" in _login_sessions
    assert lock.locked() is True
    assert lease.owned is True

    lease.release()


@pytest.mark.asyncio
async def test_start_login_forces_stale_session_lock(phone_service, monkeypatch):
    """残留登录会话的锁必须被强制释放，否则账号锁永久滞留。"""
    account = "lease_start_stale"
    lock = get_account_lock(account)
    stale_client = _FakeLoginClient()
    stale_lease = AccountLockLease(lock)
    stale_lease.mark_owned()

    _login_sessions[f"{account}_+8613800000000"] = {
        "client": stale_client,
        "lock": lock,
        "lock_lease": stale_lease,
        "account_name": account,
    }
    await lock.acquire()

    monkeypatch.setattr(
        "backend.services.telegram.login_phone._cleanup_expired_login_sessions",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "backend.services.telegram.login_phone.get_session_mode", lambda: "string"
    )
    monkeypatch.setattr(
        "backend.services.telegram.login_phone.get_global_semaphore",
        lambda: _SemaphoreStub(),
    )
    monkeypatch.setattr("tg_signer.core.close_client_by_name", AsyncMock())

    sent_code = MagicMock()
    sent_code.phone_code_hash = "new-hash"
    fake_client = _FakeLoginClient(connected=False)
    fake_client.send_code = AsyncMock(return_value=sent_code)

    config_service = MagicMock()
    config_service.get_telegram_config.return_value = {}
    config_service.get_global_proxy.return_value = None
    config_service.require_proxy_for_telegram.return_value = False

    with patch("pyrogram.Client", return_value=fake_client), patch(
        "backend.services.config.get_config_service", return_value=config_service
    ), patch(
        "backend.services.telegram.credentials.resolve_telegram_api_credentials",
        return_value=(12345, "api-hash"),
    ):
        result = await phone_service.start_login(account, "+8613800000000")

    assert result["phone_code_hash"] == "new-hash"
    # 残留会话已清理，其锁被强制释放，新流程重新持有
    assert stale_client.disconnect_calls == 1
    assert stale_lease.owned is False
    assert lock.locked() is True
    new_lease = _login_sessions[f"{account}_+8613800000000"]["lock_lease"]
    assert new_lease.owned is True

    new_lease.release()


@pytest.mark.asyncio
async def test_start_login_releases_own_lock_on_api_error(phone_service, monkeypatch):
    """凭据缺失等早期失败也必须释放本流程自己获取的锁。"""
    account = "lease_start_error"
    lock = get_account_lock(account)

    monkeypatch.setattr(
        "backend.services.telegram.login_phone._cleanup_expired_login_sessions",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "backend.services.telegram.login_phone.get_session_mode", lambda: "string"
    )
    monkeypatch.setattr(
        "backend.services.telegram.login_phone.get_global_semaphore",
        lambda: _SemaphoreStub(),
    )
    monkeypatch.setattr("tg_signer.core.close_client_by_name", AsyncMock())

    config_service = MagicMock()
    config_service.get_telegram_config.return_value = {}
    config_service.get_global_proxy.return_value = None
    config_service.require_proxy_for_telegram.return_value = False

    with patch(
        "backend.services.config.get_config_service", return_value=config_service
    ), patch(
        "backend.services.telegram.credentials.resolve_telegram_api_credentials",
        side_effect=ValueError("no api"),
    ):
        with pytest.raises(ValueError, match="Telegram API ID"):
            await phone_service.start_login(account, "+8613800000000")

    assert lock.locked() is False


@pytest.mark.asyncio
async def test_qr_cleanup_skips_unowned_lease(qr_service):
    """扫码会话被他人接管后，清理不得释放别人的锁。"""
    account = "lease_qr_foreign"
    lock = get_account_lock(account)
    await lock.acquire()
    lease = AccountLockLease(lock)

    _qr_login_sessions["qr-1"] = {
        "account_name": account,
        "lock": lock,
        "lock_lease": lease,
    }

    await qr_service._cleanup_qr_login("qr-1")

    assert lock.locked() is True
    assert _qr_login_sessions == {}

    lock.release()


@pytest.mark.asyncio
async def test_qr_cleanup_releases_owned_lease(qr_service):
    """本流程持有的扫码锁由清理路径正常释放。"""
    account = "lease_qr_owned"
    lock = get_account_lock(account)
    await lock.acquire()
    lease = AccountLockLease(lock)
    lease.mark_owned()

    _qr_login_sessions["qr-2"] = {
        "account_name": account,
        "lock": lock,
        "lock_lease": lease,
    }

    await qr_service._cleanup_qr_login("qr-2")

    assert lock.locked() is False
    assert _qr_login_sessions == {}


@pytest.mark.asyncio
async def test_submit_qr_password_keeps_foreign_lock_locked(qr_service):
    """扫码续接请求发现锁被他人持有时不得释放该锁。"""
    account = "lease_qr_submit_foreign"
    lock = get_account_lock(account)
    await lock.acquire()

    client = _FakeLoginClient()
    _qr_login_sessions["qr-3"] = {
        "account_name": account,
        "client": client,
        "status": "waiting_scan",
        "expires_ts": __import__("time").time() + 600,
        "lock": lock,
        "lock_lease": AccountLockLease(lock),
    }

    with patch(
        "backend.services.telegram.login_qr.get_global_semaphore",
        return_value=_SemaphoreStub(),
    ):
        with patch.object(
            qr_service, "_finalize_qr_password_login", new_callable=AsyncMock
        ) as finalize:
            finalize.side_effect = RuntimeError("boom")
            with pytest.raises(ValueError):
                await qr_service.submit_qr_password("qr-3", "pw")

    assert lock.locked() is True
    assert client.disconnect_calls == 1

    lock.release()


@pytest.mark.asyncio
async def test_qr_start_force_releases_stale_session_lock(qr_service, monkeypatch):
    """残留扫码会话的锁必须被强制释放。"""
    account = "lease_qr_start_stale"
    lock = get_account_lock(account)
    stale_lease = AccountLockLease(lock)
    stale_lease.mark_owned()

    _qr_login_sessions["qr-old"] = {
        "account_name": account,
        "lock": lock,
        "lock_lease": stale_lease,
    }
    await lock.acquire()

    monkeypatch.setattr(
        "backend.services.telegram.login_qr._cleanup_expired_login_sessions",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "backend.services.telegram.login_qr.get_session_mode", lambda: "string"
    )
    monkeypatch.setattr(
        "backend.services.telegram.login_qr.get_global_semaphore",
        lambda: _SemaphoreStub(),
    )
    monkeypatch.setattr("tg_signer.core.close_client_by_name", AsyncMock())

    config_service = MagicMock()
    config_service.get_global_proxy.return_value = None
    config_service.require_proxy_for_telegram.return_value = False

    result_token = MagicMock()
    result_token.token = b"tok"
    result_token.expires = None
    result_token.dc_id = 2
    fake_client = _FakeLoginClient(connected=False)
    fake_client.invoke = AsyncMock(return_value=result_token)
    fake_client.add_handler = MagicMock(return_value=("group", 0))

    with contextlib.suppress(Exception):
        with patch("pyrogram.Client", return_value=fake_client), patch(
            "backend.services.config.get_config_service",
            return_value=config_service,
        ), patch.object(
            qr_service, "_resolve_api_credentials", return_value=(1, "hash")
        ), patch(
            "backend.services.telegram.login_qr.create_logged_task",
            return_value=MagicMock(done=lambda: True),
        ):
            monkeypatch.setattr(
                "backend.services.telegram.login_qr.secrets.token_urlsafe",
                lambda n: "fixed-login-id",
            )
            await qr_service.start_qr_login(account)

    # 无论启动结果如何，残留锁都不允许继续滞留
    assert stale_lease.owned is False
    if lock.locked():
        lock.release()

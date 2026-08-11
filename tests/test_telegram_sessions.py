"""
backend/services/telegram/sessions.py 单元测试

覆盖范围：
- _release_login_session：连接断开、异常容忍、锁释放、空值容错
- _cleanup_expired_login_sessions：过期清理、新鲜保留、无时间戳保留、
  登录/扫码独立存活期、超量按最旧逐出
"""

from __future__ import annotations

import asyncio
import time

import pytest

from backend.services.telegram import sessions as sessions_mod


class _FakeClient:
    """模拟 Pyrogram 客户端的最小接口"""

    def __init__(self, connected: bool = True, fail: bool = False):
        self.is_connected = connected
        self.disconnect_calls = 0
        self._fail = fail

    async def disconnect(self):
        self.disconnect_calls += 1
        if self._fail:
            raise RuntimeError("disconnect boom")


@pytest.fixture(autouse=True)
def clean_session_stores():
    """每个用例前后清空全局 session 存储，避免串扰"""
    sessions_mod._login_sessions.clear()
    sessions_mod._qr_login_sessions.clear()
    yield
    sessions_mod._login_sessions.clear()
    sessions_mod._qr_login_sessions.clear()


class TestReleaseLoginSession:
    """_release_login_session() 释放逻辑"""

    @pytest.mark.asyncio
    async def test_disconnects_connected_client(self):
        client = _FakeClient(connected=True)
        await sessions_mod._release_login_session({"client": client})
        assert client.disconnect_calls == 1

    @pytest.mark.asyncio
    async def test_skips_disconnected_client(self):
        client = _FakeClient(connected=False)
        await sessions_mod._release_login_session({"client": client})
        assert client.disconnect_calls == 0

    @pytest.mark.asyncio
    async def test_tolerates_disconnect_failure(self):
        client = _FakeClient(connected=True, fail=True)
        await sessions_mod._release_login_session({"client": client})
        assert client.disconnect_calls == 1

    @pytest.mark.asyncio
    async def test_releases_held_lock(self):
        lock = asyncio.Lock()
        await lock.acquire()
        await sessions_mod._release_login_session({"lock": lock})
        assert lock.locked() is False

    @pytest.mark.asyncio
    async def test_empty_value_is_noop(self):
        await sessions_mod._release_login_session({})
        await sessions_mod._release_login_session({"client": None, "lock": None})


class TestCleanupExpiredLoginSessions:
    """_cleanup_expired_login_sessions() 过期与超量清理"""

    @pytest.mark.asyncio
    async def test_expired_login_session_removed_and_released(self):
        client = _FakeClient()
        sessions_mod._login_sessions["old"] = {
            "client": client,
            "_created_at": time.monotonic() - 1900,  # 超过 30 分钟存活期
        }
        await sessions_mod._cleanup_expired_login_sessions()
        assert "old" not in sessions_mod._login_sessions
        assert client.disconnect_calls == 1

    @pytest.mark.asyncio
    async def test_fresh_and_timeless_sessions_kept(self):
        now = time.monotonic()
        sessions_mod._login_sessions["fresh"] = {"client": _FakeClient(), "_created_at": now}
        sessions_mod._login_sessions["timeless"] = {"client": _FakeClient()}
        await sessions_mod._cleanup_expired_login_sessions()
        assert set(sessions_mod._login_sessions) == {"fresh", "timeless"}

    @pytest.mark.asyncio
    async def test_qr_sessions_use_shorter_max_age(self):
        # 扫码登录存活期 600s：700s 前的应清理；手机号登录 1800s 同时间点应保留
        client_qr = _FakeClient()
        client_login = _FakeClient()
        created = time.monotonic() - 700
        sessions_mod._qr_login_sessions["qr"] = {"client": client_qr, "_created_at": created}
        sessions_mod._login_sessions["login"] = {"client": client_login, "_created_at": created}
        await sessions_mod._cleanup_expired_login_sessions()
        assert "qr" not in sessions_mod._qr_login_sessions
        assert "login" in sessions_mod._login_sessions

    @pytest.mark.asyncio
    async def test_overflow_evicts_oldest(self, monkeypatch):
        monkeypatch.setattr(sessions_mod, "_MAX_LOGIN_SESSIONS", 2)
        now = time.monotonic()
        oldest_client = _FakeClient()
        for key, age, client in (
            ("oldest", 100, oldest_client),
            ("middle", 50, _FakeClient()),
            ("newest", 1, _FakeClient()),
        ):
            sessions_mod._login_sessions[key] = {
                "client": client,
                "_created_at": now - age,
            }
        await sessions_mod._cleanup_expired_login_sessions()
        assert set(sessions_mod._login_sessions) == {"middle", "newest"}
        assert oldest_client.disconnect_calls == 1

    @pytest.mark.asyncio
    async def test_missing_created_at_eviction_uses_inf(self, monkeypatch):
        # 无 _created_at 的条目按 float("inf") 视为最新，不得被优先逐出
        monkeypatch.setattr(sessions_mod, "_MAX_LOGIN_SESSIONS", 1)
        now = time.monotonic()
        old_client = _FakeClient()
        sessions_mod._login_sessions["timed"] = {"client": old_client, "_created_at": now - 50}
        sessions_mod._login_sessions["timeless"] = {"client": _FakeClient()}
        await sessions_mod._cleanup_expired_login_sessions()
        assert set(sessions_mod._login_sessions) == {"timeless"}
        assert old_client.disconnect_calls == 1

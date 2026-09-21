"""QR 登录授权用户解析回归测试。

kurigram 2.2.10 起 ``types.User._parse`` 由同步方法改为协程：漏 await 会拿到 coroutine
对象，``user.id`` 直接抛 AttributeError，导致扫码登录收尾与 2FA 密码提交失败。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pyrogram import raw, types

from backend.services.telegram.login_qr import TelegramQrLoginMixin


def _raw_user(user_id: int) -> raw.types.User:
    return raw.types.User(
        id=user_id,
        is_self=False,
        first_name="Tester",
        username="tester",
        access_hash=999,
    )


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.storage = MagicMock()
    client.storage.user_id = AsyncMock()
    client.storage.is_bot = AsyncMock()
    return client


class _Dummy(TelegramQrLoginMixin):
    """剥离真实会话迁移/持久化副作用，只保留被测解析逻辑。"""

    def _log_qr_state(self, login_id, state, data=None):
        pass

    async def _apply_migrate_auth(self, client, data):
        pass

    async def _persist_client_session(self, client, account_name, proxy):
        pass

    async def _finalize_qr_login_success(self, login_id, data, me):
        return {"status": "success", "user_id": getattr(me, "id", None)}


@pytest.mark.asyncio
async def test_store_qr_authorized_user_awaits_user_parse():
    """扫码确认后的授权用户必须是已解析的 User，而不是 coroutine。"""
    client = _mock_client()
    login_result = MagicMock()
    login_result.authorization.user = _raw_user(777)
    data = {}

    user = await _Dummy()._store_qr_authorized_user(client, data, login_result)

    assert isinstance(user, types.User)
    assert user.id == 777
    client.storage.user_id.assert_awaited_once_with(777)
    assert data["authorized"] is True
    assert data["authorized_user"] is user


@pytest.mark.asyncio
async def test_finalize_qr_password_login_awaits_user_parse_on_migrate_branch(
    monkeypatch,
):
    """DC 迁移分支：2FA 密码校验成功后必须拿到已解析的 User 才能写入会话。"""
    from tg_signer import compat as compat_module

    session = MagicMock()
    auth_result = MagicMock()
    auth_result.user = _raw_user(888)
    session.invoke = AsyncMock(side_effect=[MagicMock(), auth_result])

    async def _fake_get_session(client, dc_id, **kwargs):
        return session

    monkeypatch.setattr(compat_module, "get_dc_session", _fake_get_session)
    # SRP 计算与真实算法无关，隔离为恒等映射
    monkeypatch.setattr(
        "pyrogram.utils.compute_password_check", lambda state, password: b"hash"
    )

    client = _mock_client()
    data = {"migrate_dc_id": 2, "account_name": "acc"}

    result = await _Dummy()._finalize_qr_password_login(
        client, data, "login1", "correct-password"
    )

    assert data["authorized"] is True
    assert isinstance(data["authorized_user"], types.User)
    assert data["authorized_user"].id == 888
    client.storage.user_id.assert_awaited_once_with(888)
    assert result == {"status": "success", "user_id": 888}

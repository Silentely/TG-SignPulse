"""JWT Token 生命周期安全测试"""

from __future__ import annotations

from datetime import timedelta

import jwt as pyjwt
import pytest

from backend.core.auth import create_access_token
from backend.core.config import get_settings
from backend.models.user import User
from backend.utils.time import utc_now

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"


def _login(client) -> str:
    resp = client.post(
        "/api/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    assert resp.status_code == 200, f"登录失败: {resp.status_code} {resp.text}"
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_password_env(monkeypatch: pytest.MonkeyPatch):
    """固定 admin 初始密码，供登录路径用例使用。"""
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASSWORD)
    yield ADMIN_PASSWORD


@pytest.fixture
def admin_client(admin_password_env, client):
    """带已知 admin 密码的测试客户端。"""
    return client


class TestTokenExpiry:
    def test_expired_token_is_rejected(self, client, db_session):
        """过期 token 应返回 401"""
        expired_token = create_access_token(
            {"sub": "admin"},
            expires_delta=timedelta(seconds=-1),
        )
        response = client.get(
            "/api/accounts",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert response.status_code == 401

    def test_valid_token_is_accepted(self, client, db_session):
        """未过期 token 应返回 200"""
        token = create_access_token(
            {"sub": "admin"},
            expires_delta=timedelta(hours=1),
        )
        response = client.get(
            "/api/accounts",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200


class TestTokenTampering:
    def test_tampered_signature_is_rejected(self, client, db_session):
        """篡改签名的 token 应返回 401"""
        token = create_access_token({"sub": "admin"})
        tampered = token[:-5] + "XXXXX"
        response = client.get(
            "/api/accounts",
            headers={"Authorization": f"Bearer {tampered}"},
        )
        assert response.status_code == 401

    def test_tampered_payload_is_rejected(self, client, db_session):
        """篡改 payload 的 token 应返回 401"""
        import base64
        import json

        token = create_access_token({"sub": "admin"})
        parts = token.split(".")
        # 篡改 payload 中的 sub
        padding = "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + padding))
        payload["sub"] = "attacker"
        new_payload = (
            base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        )
        tampered = f"{parts[0]}.{new_payload}.{parts[2]}"
        response = client.get(
            "/api/accounts",
            headers={"Authorization": f"Bearer {tampered}"},
        )
        assert response.status_code == 401


class TestTokenCrossKey:
    def test_different_secret_invalidates_token(self, client, db_session):
        """不同密钥签发的 token 应返回 401"""
        _ = create_access_token({"sub": "admin"})  # 默认密钥签发，仅作对照基线
        # 手动构造一个用不同密钥签发的 token
        import jwt

        different_token = jwt.encode(
            {"sub": "admin", "exp": utc_now() + timedelta(hours=1)},
            "completely-different-secret-key-0123456789",
            algorithm="HS256",
        )
        response = client.get(
            "/api/accounts",
            headers={"Authorization": f"Bearer {different_token}"},
        )
        assert response.status_code == 401

    def test_missing_sub_claim_is_rejected(self, client, db_session):
        """缺少 sub 声明的 token 应返回 401"""
        token = create_access_token({"role": "admin"})  # 没有 sub
        response = client.get(
            "/api/accounts",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401

    def test_empty_token_is_rejected(self, client, db_session):
        """空 token 应返回 401"""
        response = client.get(
            "/api/accounts",
            headers={"Authorization": "Bearer "},
        )
        assert response.status_code == 401


class TestTokenDecodeLogging:
    """JWT 解码失败分类日志：行为不变（返回 None），但留可观测线索。"""

    def test_expired_token_logs_decode_failure(self, db_session, caplog):
        # 直接构造一个已过期的 token（exp 设为过去）
        import datetime

        import jwt as pyjwt

        from backend.core.auth import _resolve_user_from_token
        from backend.core.config import get_settings

        settings = get_settings()
        payload = {
            "sub": "admin",
            "exp": datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(hours=1),
        }
        expired = pyjwt.encode(payload, settings.secret_key, algorithm="HS256")

        import logging

        with caplog.at_level(logging.DEBUG, logger="backend.auth"):
            result = _resolve_user_from_token(expired, db_session)
        assert result is None
        # 过期 token 触发任一解码失败日志（版本差异可能走 ExpiredSignatureError 或签名校验分支）
        assert any("JWT" in r.message for r in caplog.records)

    def test_tampered_token_logs_decode_failure(self, db_session, caplog):
        import logging

        from backend.core.auth import _resolve_user_from_token

        with caplog.at_level(logging.DEBUG, logger="backend.auth"):
            result = _resolve_user_from_token("not-a-jwt", db_session)
        assert result is None
        assert any("JWT 解码失败" in r.message for r in caplog.records)


class TestTokenRevocation:
    """令牌世代号（token_epoch）吊销：改密/登出后旧令牌必须失效。"""

    def test_token_without_epoch_claim_is_rejected(self, admin_client, db_session):
        """缺少 tep 世代声明的令牌（早期签发）按已吊销处理，返回 401。"""
        settings = get_settings()
        legacy = pyjwt.encode(
            {"sub": ADMIN_USERNAME, "exp": utc_now() + timedelta(hours=1)},
            settings.secret_key,
            algorithm="HS256",
        )
        response = admin_client.get("/api/accounts", headers=_auth(legacy))
        assert response.status_code == 401

    def test_password_change_revokes_previous_token(self, admin_client, db_session):
        """修改密码后，此前签发的令牌立即失效，新令牌可正常使用。"""
        old_token = _login(admin_client)

        resp = admin_client.put(
            "/api/user/password",
            json={"old_password": ADMIN_PASSWORD, "new_password": "newpass123"},
            headers=_auth(old_token),
        )
        assert resp.status_code == 200, resp.text

        # 旧令牌被吊销
        after = admin_client.get("/api/accounts", headers=_auth(old_token))
        assert after.status_code == 401

        # 用新密码重新登录得到的令牌可用
        resp = admin_client.post(
            "/api/auth/login",
            json={"username": ADMIN_USERNAME, "password": "newpass123"},
        )
        assert resp.status_code == 200
        new_token = resp.json()["access_token"]
        assert (
            admin_client.get("/api/accounts", headers=_auth(new_token)).status_code
            == 200
        )

    def test_logout_revokes_current_token(self, admin_client, db_session):
        """主动登出自增世代号，当前令牌与其他已签发令牌同时失效。"""
        token = _login(admin_client)
        assert (
            admin_client.get("/api/accounts", headers=_auth(token)).status_code == 200
        )

        resp = admin_client.post("/api/user/logout", headers=_auth(token))
        assert resp.status_code == 200, resp.text
        assert (
            admin_client.get("/api/accounts", headers=_auth(token)).status_code == 401
        )

    def test_logout_increments_token_epoch(self, admin_client, db_session):
        """登出后用户 token_epoch 自增，后续签发的令牌嵌入新世代号。"""
        token = _login(admin_client)
        user = db_session.query(User).filter(User.username == ADMIN_USERNAME).first()
        epoch_before = int(user.token_epoch or 1)

        admin_client.post("/api/user/logout", headers=_auth(token))
        db_session.refresh(user)
        assert int(user.token_epoch or 1) == epoch_before + 1

    def test_change_username_token_stays_valid_after_rotation(
        self, admin_client, db_session
    ):
        """用户名轮换后签发的令牌必须嵌入当前世代号，否则会立即失效。"""
        # 先改密制造世代号 > 1 的场景
        token = _login(admin_client)
        admin_client.put(
            "/api/user/password",
            json={"old_password": ADMIN_PASSWORD, "new_password": "rotated1234"},
            headers=_auth(token),
        )

        resp = admin_client.post(
            "/api/auth/login",
            json={"username": ADMIN_USERNAME, "password": "rotated1234"},
        )
        assert resp.status_code == 200
        token = resp.json()["access_token"]

        resp = admin_client.put(
            "/api/user/username",
            json={"new_username": "admin_renamed", "password": "rotated1234"},
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.text
        rotated_token = resp.json()["access_token"]
        assert rotated_token

        # 轮换后的令牌仍可用（嵌入当前 epoch）
        me = admin_client.get("/api/auth/me", headers=_auth(rotated_token))
        assert me.status_code == 200
        assert me.json()["username"] == "admin_renamed"

    def test_login_token_lifetime_follows_settings(
        self, admin_client, db_session, monkeypatch
    ):
        """登录令牌寿命应取 APP_ACCESS_TOKEN_EXPIRE_HOURS，而非硬编码 12 小时。"""
        from backend.core import auth as auth_core
        from backend.core import config as config_module

        monkeypatch.setenv("APP_ACCESS_TOKEN_EXPIRE_HOURS", "1")
        config_module.get_settings.cache_clear()
        try:
            token = _login(admin_client)
            # 签发用的密钥取自 auth 模块加载时的 settings 快照
            payload = pyjwt.decode(
                token, auth_core.settings.secret_key, algorithms=["HS256"]
            )
            lifetime = payload["exp"] - utc_now().timestamp()
            assert 3500 <= lifetime <= 3600
        finally:
            monkeypatch.delenv("APP_ACCESS_TOKEN_EXPIRE_HOURS", raising=False)
            config_module.get_settings.cache_clear()


def test_resolve_user_from_token_non_numeric_tep_claim():
    """非数字或异常格式的 tep claim 返回 None，不抛出 500 异常。"""
    from unittest.mock import MagicMock

    import jwt

    from backend.core.auth import _resolve_user_from_token
    from backend.core.config import get_settings

    settings = get_settings()
    mock_db = MagicMock()
    token_invalid_tep = jwt.encode(
        {"sub": "admin", "tep": "invalid_string_not_number"},
        settings.secret_key,
        algorithm="HS256",
    )
    result = _resolve_user_from_token(token_invalid_tep, mock_db)
    assert result is None

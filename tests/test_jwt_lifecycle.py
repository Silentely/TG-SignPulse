"""JWT Token 生命周期安全测试"""
from __future__ import annotations

from datetime import timedelta

from backend.core.auth import create_access_token
from backend.utils.time import utc_now


class TestTokenExpiry:
    def test_expired_token_is_rejected(self, client, db_session):
        """过期 token 应返回 401"""
        expired_token = create_access_token(
            {"sub": "admin"},
            expires_delta=timedelta(seconds=-1),
        )
        response = client.get(
            "/api/tasks",
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
            "/api/tasks",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200


class TestTokenTampering:
    def test_tampered_signature_is_rejected(self, client, db_session):
        """篡改签名的 token 应返回 401"""
        token = create_access_token({"sub": "admin"})
        tampered = token[:-5] + "XXXXX"
        response = client.get(
            "/api/tasks",
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
            base64.urlsafe_b64encode(json.dumps(payload).encode())
            .rstrip(b"=")
            .decode()
        )
        tampered = f"{parts[0]}.{new_payload}.{parts[2]}"
        response = client.get(
            "/api/tasks",
            headers={"Authorization": f"Bearer {tampered}"},
        )
        assert response.status_code == 401


class TestTokenCrossKey:
    def test_different_secret_invalidates_token(self, client, db_session):
        """不同密钥签发的 token 应返回 401"""
        token = create_access_token({"sub": "admin"})
        # 手动构造一个用不同密钥签发的 token
        import jwt

        different_token = jwt.encode(
            {"sub": "admin", "exp": utc_now() + timedelta(hours=1)},
            "completely-different-secret-key",
            algorithm="HS256",
        )
        response = client.get(
            "/api/tasks",
            headers={"Authorization": f"Bearer {different_token}"},
        )
        assert response.status_code == 401

    def test_missing_sub_claim_is_rejected(self, client, db_session):
        """缺少 sub 声明的 token 应返回 401"""
        token = create_access_token({"role": "admin"})  # 没有 sub
        response = client.get(
            "/api/tasks",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401

    def test_empty_token_is_rejected(self, client, db_session):
        """空 token 应返回 401"""
        response = client.get(
            "/api/tasks",
            headers={"Authorization": "Bearer "},
        )
        assert response.status_code == 401

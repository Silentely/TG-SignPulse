"""Tests verifying security audit fixes and hardening measures.

Covers:
1. Rate limit IP resolution & spoofing prevention (trusted vs untrusted proxies, right-to-left traversal)
2. TOTP QR code query token removal (requires Authorization header)
3. TOTP reset endpoint blocking password-only resets when 2FA is active
4. Offline admin CLI script for resetting TOTP
5. Push notification SSRF / cloud metadata endpoint protections
6. Sensitive file permission convergence (0600 on disk)
7. Plugin AST security static analyzer (sandbox escape attribute & reflection checks)
8. User endpoint TOTP reset blocking when 2FA is active
"""
from __future__ import annotations

import ast
import os
import stat

import pytest
from starlette.requests import Request

from backend.core.auth import create_access_token
from backend.core.config import get_settings
from backend.core.rate_limit import get_client_identifier, is_trusted_proxy
from backend.core.security import hash_password
from backend.models.user import User
from backend.services.push_notifications import _validate_push_target_url
from backend.utils.atomic_io import write_json_atomic
from backend.utils.tg_session import save_session_string_file
from tg_signer.core.plugins import _SecurityVisitor


def _make_request(
    client_host: str = "1.2.3.4",
    headers: dict[str, str] | None = None,
) -> Request:
    """Helper to mock a Starlette Request with client and headers."""
    raw_headers = []
    if headers:
        for k, v in headers.items():
            raw_headers.append((k.lower().encode("latin-1"), v.encode("latin-1")))

    scope = {
        "type": "http",
        "client": (client_host, 12345) if client_host else None,
        "headers": raw_headers,
    }
    return Request(scope)


class TestSecurityAuditFixes:
    def test_rate_limit_trusted_proxy_logic(self):
        # Localhost and CIDR checks
        assert is_trusted_proxy("127.0.0.1", ["127.0.0.1", "::1"])
        assert is_trusted_proxy("::1", ["127.0.0.1", "::1"])
        assert not is_trusted_proxy("203.0.113.195", ["127.0.0.1", "::1"])

        # Subnet matching
        assert is_trusted_proxy("10.0.1.50", ["10.0.0.0/16"])
        assert not is_trusted_proxy("10.1.0.1", ["10.0.0.0/16"])

        # Wildcard
        assert is_trusted_proxy("8.8.8.8", ["*"])

        # IPv4-mapped IPv6 normalization
        assert is_trusted_proxy("::ffff:127.0.0.1", ["127.0.0.1"])

    def test_rate_limit_untrusted_cannot_spoof_ip(self, monkeypatch):
        monkeypatch.setenv("APP_TRUSTED_PROXIES", "127.0.0.1")
        get_settings.cache_clear()

        # Untrusted client host 203.0.113.50 sends spoofed X-Forwarded-For
        req = _make_request(
            client_host="203.0.113.50",
            headers={"x-forwarded-for": "1.1.1.1, 2.2.2.2", "x-real-ip": "1.1.1.1"},
        )
        resolved = get_client_identifier(req)
        # Must resolve to the direct client socket host, NOT the spoofed header
        assert resolved == "203.0.113.50"

    def test_rate_limit_trusted_proxy_forwards_real_ip(self, monkeypatch):
        monkeypatch.setenv("APP_TRUSTED_PROXIES", "127.0.0.1,10.0.0.1")
        get_settings.cache_clear()

        # Trusted proxy client host forwards end-user IP
        req = _make_request(
            client_host="127.0.0.1",
            headers={"x-forwarded-for": "198.51.100.22, 127.0.0.1"},
        )
        resolved = get_client_identifier(req)
        assert resolved == "198.51.100.22"

    def test_rate_limit_trusted_proxy_ignores_spoofed_leftmost_hops(self, monkeypatch):
        monkeypatch.setenv("APP_TRUSTED_PROXIES", "127.0.0.1,10.0.0.1")
        get_settings.cache_clear()

        # Attacker spoofs "9.9.9.9", actual client is "198.51.100.22", passed through proxy "10.0.0.1" and "127.0.0.1"
        req = _make_request(
            client_host="127.0.0.1",
            headers={"x-forwarded-for": "9.9.9.9, 198.51.100.22, 10.0.0.1"},
        )
        resolved = get_client_identifier(req)
        # Must skip 10.0.0.1 (trusted) and select 198.51.100.22 (first untrusted), ignoring 9.9.9.9
        assert resolved == "198.51.100.22"

    def test_push_notification_ssrf_blocks_cloud_metadata(self):
        # AWS / GCP / Alibaba cloud metadata IP and domains
        with pytest.raises(ValueError, match="禁止向敏感云元数据地址发送推送"):
            _validate_push_target_url("http://169.254.169.254/latest/meta-data/")

        with pytest.raises(ValueError, match="禁止向敏感云元数据地址发送推送"):
            _validate_push_target_url("http://metadata.google.internal/computeMetadata/v1/")

        with pytest.raises(ValueError, match="禁止向敏感云元数据地址发送推送"):
            _validate_push_target_url("http://100.100.100.200/latest/meta-data/")

    def test_push_notification_ssrf_blocks_link_local(self):
        with pytest.raises(ValueError, match="禁止向链路本地地址"):
            _validate_push_target_url("http://169.254.1.10/webhook")

    def test_push_notification_valid_url(self):
        # Normal public and local addresses without metadata flag pass
        _validate_push_target_url("https://api.telegram.org/bot123/send")
        _validate_push_target_url("https://oapi.dingtalk.com/robot/send")

    def test_atomic_io_sets_permissions_0600(self, tmp_path):
        target = tmp_path / "secret.json"
        write_json_atomic(target, {"secret": "super_sensitive_token"})
        assert target.exists()

        mode = stat.S_IMODE(os.stat(target).st_mode)
        # Should be read/write for owner only (0o600)
        assert mode == 0o600

    def test_tg_session_save_sets_permissions_0600(self, tmp_path):
        save_session_string_file(tmp_path, "acc1", "dummy_session_data")
        sess_file = tmp_path / "acc1.session_string"
        assert sess_file.exists()

        mode = stat.S_IMODE(os.stat(sess_file).st_mode)
        assert mode == 0o600

    def test_ast_security_visitor_detects_sandbox_escapes(self):
        code = """
def exploit():
    c = ().__class__.__bases__[0].__subclasses__()
    g = exploit.__globals__
    m = ().__class__.__mro__
    return c, g, m
"""
        tree = ast.parse(code)
        visitor = _SecurityVisitor()
        visitor.visit(tree)

        detected_rules = {w["rule"] for w in visitor.warnings}
        assert "sandbox-escape:__bases__" in detected_rules
        assert "sandbox-escape:__subclasses__" in detected_rules
        assert "sandbox-escape:__globals__" in detected_rules
        assert "sandbox-escape:__mro__" in detected_rules

    def test_ast_security_visitor_detects_reflection_escapes(self):
        code = """
def exploit(cls):
    return getattr(cls, "__subclasses__")()
"""
        tree = ast.parse(code)
        visitor = _SecurityVisitor()
        visitor.visit(tree)

        detected_rules = {w["rule"] for w in visitor.warnings}
        assert "reflection-call:getattr:__subclasses__" in detected_rules

    def test_totp_reset_blocks_password_only_by_default(self, client, db_session):
        user = User(username="testuser_totp", password_hash=hash_password("mypassword123"))
        user.totp_secret = "JBSWY3DPEHPK3PXP"
        db_session.add(user)
        db_session.commit()

        # Attempt to reset TOTP without env flag
        resp = client.post(
            "/api/auth/reset-totp",
            json={"username": "testuser_totp", "password": "mypassword123"},
        )
        assert resp.status_code == 403
        assert "ALLOW_PASSWORD_ONLY_TOTP_RESET" in resp.json()["detail"]

    def test_totp_reset_cli_script(self, db_session):
        from scripts.reset_user_totp import reset_totp_for_user

        user = User(username="cli_test_user", password_hash=hash_password("pwd"))
        user.totp_secret = "JBSWY3DPEHPK3PXP"
        db_session.add(user)
        db_session.commit()

        success = reset_totp_for_user("cli_test_user", db=db_session)
        assert success is True

        db_session.refresh(user)
        assert user.totp_secret is None

    def test_totp_qrcode_requires_auth(self, client):
        # Querying /api/user/totp/qrcode without Authorization header must return 401
        resp = client.get("/api/user/totp/qrcode")
        assert resp.status_code == 401

        # Even if passing ?token=xxx query param, it should not authenticate
        resp2 = client.get("/api/user/totp/qrcode?token=invalid_or_stolen")
        assert resp2.status_code == 401

    def test_user_totp_reset_blocks_when_active(self, client, db_session):
        user = User(username="user_with_totp", password_hash=hash_password("pwd123"))
        user.totp_secret = "JBSWY3DPEHPK3PXP"
        db_session.add(user)
        db_session.commit()

        token = create_access_token(data={"sub": "user_with_totp"})
        resp = client.post(
            "/api/user/totp/reset",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
        assert "已启用两步验证的用户无法直接重置" in resp.json()["detail"]

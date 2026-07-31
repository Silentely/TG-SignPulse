"""
tg_signer/security.py 单元测试

覆盖范围：
- 前缀/掩码判定：is_encrypted_secret、is_masked_secret、mask_secret
- 密钥来源：_read_app_secret_key 的环境变量、后端配置兜底、缺失报错
- Fernet 实例缓存：get_fernet 同密钥复用
- 加解密回环：encrypt_secret / decrypt_secret 的明文静态加密、有效密文直通、
  伪造前缀重加密、密钥错误时报 InvalidToken
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken

from tg_signer.security import (
    SecretKeyError,
    _read_app_secret_key,
    decrypt_secret,
    encrypt_secret,
    get_fernet,
    is_encrypted_secret,
    is_masked_secret,
    mask_secret,
)

TEST_SECRET = "unit-test-secret-key"


@pytest.fixture(autouse=True)
def app_secret_env(monkeypatch):
    """每个用例默认提供独立的 APP_SECRET_KEY，隔离真实配置"""
    monkeypatch.setenv("APP_SECRET_KEY", TEST_SECRET)
    return TEST_SECRET


class TestPredicates:
    """前缀/掩码判定函数"""

    def test_is_encrypted_secret(self):
        assert is_encrypted_secret("fernet:abc") is True
        assert is_encrypted_secret("plain") is False
        assert is_encrypted_secret("") is False
        assert is_encrypted_secret(None) is False
        assert is_encrypted_secret(123) is False

    def test_is_masked_secret(self):
        assert is_masked_secret("********") is True
        assert is_masked_secret("*******") is False
        assert is_masked_secret("") is False
        assert is_masked_secret(None) is False

    def test_mask_secret(self):
        assert mask_secret("api-key-123") == "********"
        assert mask_secret("   ") is None
        assert mask_secret("") is None
        assert mask_secret(None) is None
        assert mask_secret(123) is None  # type: ignore[arg-type]


class TestReadAppSecretKey:
    """_read_app_secret_key 的密钥来源优先级"""

    def test_env_secret_wins(self):
        assert _read_app_secret_key() == TEST_SECRET

    def test_env_secret_is_stripped(self, monkeypatch):
        monkeypatch.setenv("APP_SECRET_KEY", f"  {TEST_SECRET}  ")
        assert _read_app_secret_key() == TEST_SECRET

    def test_backend_config_fallback(self, monkeypatch):
        monkeypatch.delenv("APP_SECRET_KEY", raising=False)
        monkeypatch.setattr(
            "backend.core.config.get_default_secret_key",
            lambda: "  fallback-secret  ",
        )
        assert _read_app_secret_key() == "fallback-secret"

    def test_missing_everywhere_raises(self, monkeypatch):
        monkeypatch.delenv("APP_SECRET_KEY", raising=False)
        monkeypatch.setattr(
            "backend.core.config.get_default_secret_key", lambda: ""
        )
        with pytest.raises(SecretKeyError, match="APP_SECRET_KEY"):
            _read_app_secret_key()

    def test_backend_config_exception_raises(self, monkeypatch):
        def _boom():
            raise RuntimeError("config broken")

        monkeypatch.delenv("APP_SECRET_KEY", raising=False)
        monkeypatch.setattr("backend.core.config.get_default_secret_key", _boom)
        with pytest.raises(SecretKeyError, match="APP_SECRET_KEY"):
            _read_app_secret_key()


class TestGetFernet:
    """Fernet 实例缓存行为"""

    def test_returns_fernet_and_caches_by_secret(self, monkeypatch):
        f1 = get_fernet()
        f2 = get_fernet()
        assert isinstance(f1, Fernet)
        assert f1 is f2  # 同密钥命中 lru_cache

        monkeypatch.setenv("APP_SECRET_KEY", "another-secret-key")
        f3 = get_fernet()
        assert isinstance(f3, Fernet)
        assert f3 is not f1  # 换密钥得到新实例


class TestEncryptSecret:
    """encrypt_secret 各输入路径"""

    def test_none_and_empty_passthrough(self):
        assert encrypt_secret(None) is None
        assert encrypt_secret("") == ""

    def test_non_str_is_stringified_then_encrypted(self):
        out = encrypt_secret(123)  # type: ignore[arg-type]
        assert is_encrypted_secret(out)
        assert decrypt_secret(out) == "123"

    def test_plaintext_roundtrip(self):
        token = encrypt_secret("chatgpt-api-key")
        assert token is not None and token.startswith("fernet:")
        assert token != "chatgpt-api-key"
        assert decrypt_secret(token) == "chatgpt-api-key"

    def test_valid_ciphertext_returned_unchanged(self):
        token = encrypt_secret("secret-value")
        assert encrypt_secret(token) == token

    def test_forged_prefix_is_reencrypted(self):
        # 伪造前缀无法通过解密验证，应整体按明文重新加密
        forged = "fernet:bm90LWEtdmFsaWQtdG9rZW4"
        out = encrypt_secret(forged)
        assert out is not None and out != forged
        assert is_encrypted_secret(out)
        assert decrypt_secret(out) == forged


class TestDecryptSecret:
    """decrypt_secret 各输入路径与错误分支"""

    def test_none_and_plain_passthrough(self):
        assert decrypt_secret(None) is None
        assert decrypt_secret("plain-value") == "plain-value"

    def test_non_str_non_encrypted_passthrough(self):
        assert decrypt_secret(456) == "456"  # type: ignore[arg-type]

    def test_wrong_key_raises_invalid_token(self, monkeypatch):
        token = encrypt_secret("plain-text")
        monkeypatch.setenv("APP_SECRET_KEY", "different-secret-key")
        with pytest.raises(InvalidToken, match="wrong APP_SECRET_KEY"):
            decrypt_secret(token)

    def test_corrupted_payload_raises_invalid_token(self):
        with pytest.raises(InvalidToken, match="wrong APP_SECRET_KEY"):
            decrypt_secret("fernet:corrupted-payload")

from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

_ENCRYPTED_PREFIX = "fernet:"
_MASKED_VALUE = "********"


class SecretKeyError(RuntimeError):
    """敏感配置加密密钥不可用。"""


def is_encrypted_secret(value: object) -> bool:
    return isinstance(value, str) and value.startswith(_ENCRYPTED_PREFIX)


def is_masked_secret(value: object) -> bool:
    return isinstance(value, str) and value == _MASKED_VALUE


def mask_secret(value: Optional[str]) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return _MASKED_VALUE
    return None


def _read_app_secret_key() -> str:
    secret = os.getenv("APP_SECRET_KEY", "").strip()
    if secret:
        return secret

    try:
        from backend.core.config import get_default_secret_key

        secret = get_default_secret_key()
    except Exception:
        secret = ""

    if not isinstance(secret, str) or not secret.strip():
        raise SecretKeyError("APP_SECRET_KEY is required to encrypt sensitive local configuration.")
    return secret.strip()


@lru_cache(maxsize=8)
def _fernet_for_secret(secret: str) -> Fernet:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def get_fernet() -> Fernet:
    return _fernet_for_secret(_read_app_secret_key())


def encrypt_secret(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    if not value:
        return value
    if is_encrypted_secret(value):
        return value
    token = get_fernet().encrypt(value.encode("utf-8")).decode("ascii")
    return f"{_ENCRYPTED_PREFIX}{token}"


def decrypt_secret(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    if not is_encrypted_secret(value):
        return value
    try:
        token = value[len(_ENCRYPTED_PREFIX):]
        return get_fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return value

from __future__ import annotations

import bcrypt


def hash_password(password: str) -> str:
    """哈希密码"""
    if not isinstance(password, str):
        raise TypeError("password must be a string")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    if not isinstance(plain_password, str) or not isinstance(hashed_password, str):
        return False
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except ValueError:
        return False

from __future__ import annotations

import os
import threading
from datetime import timedelta
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt import PyJWTError
from sqlalchemy.orm import Session

import pyotp
from backend.core.config import get_settings
from backend.core.database import get_db
from backend.core.security import verify_password
from backend.models.user import User
from backend.utils.time import utc_now

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

settings = get_settings()

# TOTP 重放保护：记录已使用的 code（hash → 首次使用时间）
_used_totp_codes: dict[str, float] = {}
_totp_lock = threading.Lock()
_TOTP_CODE_REUSE_WINDOW = 120  # 2 分钟（覆盖当前 + 上一个窗口）


def _cleanup_used_totp_codes() -> None:
    """清理过期的已使用 code 记录"""
    import time
    now = time.monotonic()
    expired = [
        k for k, v in _used_totp_codes.items()
        if now - v > _TOTP_CODE_REUSE_WINDOW
    ]
    for k in expired:
        _used_totp_codes.pop(k, None)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = utc_now() + (
        expires_delta or timedelta(hours=settings.access_token_expire_hours)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm="HS256")


def verify_totp(secret: str, code: str) -> bool:
    """验证 TOTP code，同一 code 在窗口期内不可重复使用"""
    try:
        if not isinstance(code, str):
            return False
        code = code.strip().replace(" ", "")
        if not code:
            return False
        totp = pyotp.TOTP(secret)
        raw_window = os.getenv("APP_TOTP_VALID_WINDOW")
        raw_window = raw_window.strip() if isinstance(raw_window, str) else ""
        try:
            valid_window = int(raw_window) if raw_window else 1
        except ValueError:
            valid_window = 1
        if valid_window < 0:
            valid_window = 0
        if not totp.verify(code, valid_window=valid_window):
            return False

        # 重放保护：使用 secret+code 的哈希作为 key（线程安全）
        import hashlib
        import time
        code_hash = hashlib.sha256(f"{secret}:{code}".encode()).hexdigest()[:16]
        now = time.monotonic()
        with _totp_lock:
            if code_hash in _used_totp_codes:
                return False  # 该 code 已被使用过
            _used_totp_codes[code_hash] = now
        # 清理过期条目（锁外执行，避免增加锁持有时间）
        _cleanup_used_totp_codes()
        return True
    except Exception:
        return False


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    user = db.query(User).filter(User.username == username).first()
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        username: str = payload.get("sub")  # type: ignore[assignment]
        if username is None:
            raise credentials_exception
    except PyJWTError:
        raise credentials_exception
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user


# OAuth2 scheme that doesn't auto-error on missing token
oauth2_scheme_optional = OAuth2PasswordBearer(
    tokenUrl="/api/auth/login", auto_error=False
)


def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_scheme_optional),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """获取当前用户，如果无法认证则返回 None（不抛出异常）"""
    if not token:
        return None
    return verify_token(token, db)


def verify_token(token: str, db: Session) -> Optional[User]:
    """验证 Token 并返回用户对象"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        username: str = payload.get("sub")  # type: ignore[assignment]
        if username is None:
            return None
    except PyJWTError:
        return None
    user = db.query(User).filter(User.username == username).first()
    return user

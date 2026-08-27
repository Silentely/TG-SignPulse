from __future__ import annotations

import logging
import os
import threading
from datetime import timedelta
from typing import Optional

import jwt
import pyotp
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt import PyJWTError
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.database import get_db
from backend.core.security import verify_password
from backend.models.user import User
from backend.utils.time import utc_now

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

settings = get_settings()

logger = logging.getLogger("backend.auth")

# TOTP 重放保护：记录已使用的 code（hash → 首次使用时间）
_used_totp_codes: dict[str, float] = {}
_totp_lock = threading.Lock()
_TOTP_CODE_REUSE_WINDOW = 120  # 2 分钟（覆盖当前 + 上一个窗口）


def _cleanup_used_totp_codes() -> None:
    """清理过期的已使用 code 记录（必须在 _totp_lock 内调用）"""
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
            # 清理与读写同锁：锁外遍历+pop 共享字典会与其他线程的插入并发，
            # 偶发 RuntimeError 被兜底吞掉后合法 TOTP 被误拒；
            # 字典极小（窗口期内每用户个位数），锁内清理成本可忽略
            _cleanup_used_totp_codes()
        return True
    except (ValueError, TypeError, OSError) as exc:
        # pyotp/hashlib/系统调用相关异常视为验证失败，不向上抛出
        logging.getLogger("backend.auth").warning(
            "TOTP 验证过程异常，按失败处理: %s", exc
        )
        return False
    except Exception:
        # 兜底：未知异常不能让认证接口崩溃
        logging.getLogger("backend.auth").exception(
            "TOTP 验证发生未知异常，按失败处理"
        )
        return False


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    """按用户名查询用户（统一入口，避免各处内联重复查询）。"""
    return db.query(User).filter(User.username == username).first()


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    user = get_user_by_username(db, username)
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def _resolve_user_from_token(token: str, db: Session) -> Optional[User]:
    """解码 JWT 并按 sub 查询用户；解码失败或用户不存在时返回 None。

    解码失败统一返回 None（与调用方 401 语义一致），但按失败类型留
    debug 日志便于排障区分 token 过期 / 篡改 / 格式错误。
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        username: Optional[str] = payload.get("sub")
        if username is None:
            logger.debug("JWT 解码成功但缺少 sub，按未认证处理")
            return None
    except jwt.ExpiredSignatureError:
        logger.debug("JWT 已过期，按未认证处理")
        return None
    except PyJWTError as exc:
        logger.debug("JWT 解码失败（无效/篡改/格式错误）: %s", exc)
        return None
    return get_user_by_username(db, username)


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    user = _resolve_user_from_token(token, db)
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
    return _resolve_user_from_token(token, db)

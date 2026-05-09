from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.core import auth as auth_core
from backend.core.auth import authenticate_user, create_access_token, verify_totp
from backend.core.database import get_db
from backend.core.rate_limit import compose_rate_limit_key, get_rate_limiter
from backend.core.security import verify_password
from backend.models.user import User
from backend.schemas.auth import LoginRequest, TokenResponse, UserOut

router = APIRouter()
logger = logging.getLogger("backend.auth")
rate_limiter = get_rate_limiter()

LOGIN_RATE_LIMIT_DETAIL = "Too many login attempts. Please try again later."
RESET_TOTP_RATE_LIMIT_DETAIL = (
    "Too many TOTP reset attempts. Please try again later."
)


class ResetTOTPRequest(BaseModel):
    """重置 TOTP 请求（通过密码验证）"""

    username: str
    password: str


class ResetTOTPResponse(BaseModel):
    """重置 TOTP 响应"""

    success: bool
    message: str


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    login_key = compose_rate_limit_key(request, payload.username)
    rate_limiter.hit(
        scope="auth.login",
        key=login_key,
        max_attempts=5,
        window_seconds=300,
        block_seconds=900,
        detail=LOGIN_RATE_LIMIT_DETAIL,
    )
    user = authenticate_user(db, payload.username, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    if user.totp_secret:
        if not payload.totp_code or not verify_totp(
            user.totp_secret, payload.totp_code
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="TOTP_REQUIRED_OR_INVALID",
            )
    rate_limiter.reset("auth.login", login_key)
    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(hours=12),
    )
    try:
        from backend.services.config import get_config_service
        from backend.services.push_notifications import send_login_notification

        forwarded_for = request.headers.get("x-forwarded-for", "")
        ip_address = (
            forwarded_for.split(",", 1)[0].strip()
            or request.headers.get("x-real-ip", "").strip()
            or (request.client.host if request.client else "")
        )
        settings = get_config_service().get_global_settings()
        background_tasks.add_task(
            send_login_notification,
            settings,
            username=user.username,
            ip_address=ip_address,
        )
    except Exception as exc:
        logger.warning("Failed to queue login notification: %s", exc)
    return TokenResponse(access_token=access_token)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(auth_core.get_current_user)):
    return current_user


@router.post("/reset-totp", response_model=ResetTOTPResponse)
def reset_totp(
    request: ResetTOTPRequest,
    http_request: Request,
    db: Session = Depends(get_db),
):
    """
    强制重置 TOTP（不需要 TOTP 验证码，只需要密码）

    用于解决用户启用了 TOTP 但无法登录的问题。
    需要提供正确的用户名和密码。
    """
    # 验证用户名和密码
    reset_key = compose_rate_limit_key(http_request, request.username)
    rate_limiter.hit(
        scope="auth.reset_totp",
        key=reset_key,
        max_attempts=5,
        window_seconds=600,
        block_seconds=1800,
        detail=RESET_TOTP_RATE_LIMIT_DETAIL,
    )

    user = db.query(User).filter(User.username == request.username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误"
        )

    if not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误"
        )

    had_totp_enabled = bool(user.totp_secret)
    user.totp_secret = None
    db.commit()
    try:
        from backend.api.routes.user import clear_pending_totp_secret

        clear_pending_totp_secret(user.id)
    except Exception:
        pass
    rate_limiter.reset("auth.reset_totp", reset_key)

    if not had_totp_enabled:
        return ResetTOTPResponse(
            success=True,
            message="该用户未启用两步验证，待确认设置已清理",
        )

    return ResetTOTPResponse(success=True, message="两步验证已重置，现在可以正常登录")

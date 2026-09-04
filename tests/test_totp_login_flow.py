"""两步验证登录流程测试：未提供 TOTP 码时的第一步挑战不应产生失败日志，仅在 TOTP 错误时记为失败。"""

from __future__ import annotations

import pyotp
import pytest
from fastapi.testclient import TestClient

from backend.core.auth import get_user_by_username
from backend.models.login_log import LoginLog
from tests.test_api import ADMIN_PASSWORD, ADMIN_USERNAME, api_client, db  # noqa: F401


def test_totp_challenge_flow_no_false_failure_log(api_client: TestClient, db):
    """
    1. 账号密码正确，但首次请求不带 totp_code（前端尚未弹出输入框）：
       - 返回 401 TOTP_REQUIRED_OR_INVALID
       - 不记录任何登录失败日志
    2. 带错误的 totp_code：
       - 返回 401 TOTP_REQUIRED_OR_INVALID
       - 记录一条失败日志
    3. 带正确的 totp_code：
       - 返回 200 并返回 access_token
       - 记录一条成功日志
    """
    user = get_user_by_username(db, ADMIN_USERNAME)
    assert user is not None

    secret = pyotp.random_base32()
    user.totp_secret = secret
    db.commit()

    try:
        # 清理历史登录日志以便准确断言
        db.query(LoginLog).filter(LoginLog.username == ADMIN_USERNAME).delete()
        db.commit()

        # Step 1: 仅提交账号密码，不带 totp_code
        resp1 = api_client.post(
            "/api/auth/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        assert resp1.status_code == 401
        assert resp1.json()["detail"] == "TOTP_REQUIRED_OR_INVALID"

        logs_step1 = (
            db.query(LoginLog).filter(LoginLog.username == ADMIN_USERNAME).all()
        )
        assert len(logs_step1) == 0, "用户初次提交密码等待二步验证码时，绝不应记录失败日志"

        # Step 2: 提交错误的 totp_code
        resp2 = api_client.post(
            "/api/auth/login",
            json={
                "username": ADMIN_USERNAME,
                "password": ADMIN_PASSWORD,
                "totp_code": "000000",
            },
        )
        assert resp2.status_code == 401
        assert resp2.json()["detail"] == "TOTP_REQUIRED_OR_INVALID"

        logs_step2 = (
            db.query(LoginLog).filter(LoginLog.username == ADMIN_USERNAME).all()
        )
        assert len(logs_step2) == 1, "输入错误验证码应记录 1 条失败日志"
        assert logs_step2[0].success is False
        assert logs_step2[0].detail == "TOTP_REQUIRED_OR_INVALID"

        # Step 3: 提交正确的 totp_code
        correct_code = pyotp.TOTP(secret).now()
        resp3 = api_client.post(
            "/api/auth/login",
            json={
                "username": ADMIN_USERNAME,
                "password": ADMIN_PASSWORD,
                "totp_code": correct_code,
            },
        )
        assert resp3.status_code == 200
        assert "access_token" in resp3.json()

        logs_step3 = (
            db.query(LoginLog)
            .filter(LoginLog.username == ADMIN_USERNAME, LoginLog.success.is_(True))
            .all()
        )
        assert len(logs_step3) == 1, "正确验证码登录应记录 1 条成功日志"
    finally:
        user.totp_secret = None
        db.commit()

"""TOTP 重放攻击防护测试"""
from __future__ import annotations

import pyotp


class TestTOTPReplayProtection:
    def test_totp_code_cannot_be_reused(self):
        """同一 TOTP code 在窗口期内不可重复使用"""
        from backend.core.auth import verify_totp

        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        code = totp.now()

        # 第一次验证成功
        assert verify_totp(secret, code) is True

        # 第二次使用同一 code 应失败（重放保护）
        assert verify_totp(secret, code) is False

    def test_different_code_succeeds(self):
        """不同的 TOTP code 应正常验证"""
        from backend.core.auth import verify_totp
        import time

        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        code1 = totp.at(int(time.time()))
        code2 = totp.at(int(time.time()) - 30)  # 上一个窗口的 code

        if code1 != code2:
            assert verify_totp(secret, code1) is True
            assert verify_totp(secret, code2) is True

    def test_invalid_code_still_rejected(self):
        """无效 code 仍然被拒绝（不触发重放保护）"""
        from backend.core.auth import verify_totp

        secret = pyotp.random_base32()
        assert verify_totp(secret, "000000") is False

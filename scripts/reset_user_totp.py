#!/usr/bin/env python3
"""命令行工具：重置指定用户的两步验证 (TOTP)

使用方法:
    python -m scripts.reset_user_totp <username>
"""

from __future__ import annotations

import sys
from typing import Optional

from sqlalchemy.orm import Session

from backend.core.auth import get_user_by_username
from backend.core.database import get_session_local


def reset_totp_for_user(username: str, db: Optional[Session] = None) -> bool:
    """重置指定用户的 TOTP 状态，返回是否成功。"""
    close_db = False
    if db is None:
        session_factory = get_session_local()
        db = session_factory()
        close_db = True

    try:
        user = get_user_by_username(db, username)
        if not user:
            return False

        user.totp_secret = None
        db.commit()

        try:
            from backend.api.routes.user import clear_pending_totp_secret

            clear_pending_totp_secret(user.id)
        except Exception:
            pass
        return True
    finally:
        if close_db:
            db.close()


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python -m scripts.reset_user_totp <username>")
        return 1

    username = sys.argv[1].strip()
    if not username:
        print("错误: 用户名不能为空")
        return 1

    success = reset_totp_for_user(username)
    if not success:
        print(f"错误: 未找到用户 '{username}' 或重置失败")
        return 1

    print(f"成功: 用户 '{username}' 的两步验证已重置为禁用状态")
    return 0


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import contextlib
import logging
import os
import secrets
from pathlib import Path

from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.security import hash_password
from backend.models.user import User

logger = logging.getLogger("backend.users")


def _bootstrap_password_file() -> Path:
    settings = get_settings()
    base_dir = settings.resolve_base_dir()
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / ".admin_bootstrap_password"


def _get_or_create_bootstrap_password() -> tuple[str, Path]:
    password_file = _bootstrap_password_file()
    try:
        existing = password_file.read_text(encoding="utf-8").strip()
        if existing:
            with contextlib.suppress(OSError):
                os.chmod(password_file, 0o600)
            return existing, password_file
    except OSError:
        pass

    password = secrets.token_urlsafe(12)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    try:
        fd = os.open(str(password_file), flags, 0o600)
        with open(fd, "w", encoding="utf-8") as f:
            f.write(password)
        with contextlib.suppress(OSError):
            os.chmod(password_file, 0o600)
    except OSError:
        password_file.write_text(password, encoding="utf-8")
        with contextlib.suppress(OSError):
            os.chmod(password_file, 0o600)
    return password, password_file


def ensure_admin(db: Session, username: str = "admin", password: str = None):
    """
    仅在用户表为空时创建一个默认管理员。
    防止用户修改用户名后，系统又自动创建一个默认的 admin 账号。
    """
    # 检查是否已有任何用户存在
    first_user = db.query(User).first()
    if first_user:
        return first_user

    auto_password = False
    bootstrap_file: Path | None = None
    if not password:
        env_pwd = os.getenv("ADMIN_PASSWORD")
        if env_pwd:
            password = env_pwd
        else:
            password, bootstrap_file = _get_or_create_bootstrap_password()
            auto_password = True

    admin = User(
        username=username,
        password_hash=hash_password(password),
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)

    if auto_password and bootstrap_file:
        logger.warning(
            "SECURITY WARNING: Admin account created with a generated bootstrap password. "
            "Read it from %s and change it immediately, or set ADMIN_PASSWORD before startup.",
            bootstrap_file,
        )

    return admin

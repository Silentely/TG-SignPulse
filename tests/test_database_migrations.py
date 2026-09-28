import sqlite3

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from backend.core.database import run_migrations
from backend.models.user import User


def test_migrations_reproduce_and_fix_missing_token_epoch(tmp_path):
    """精确复现并修复用户现场问题：旧版数据库已有 users 表与 totp_secret，但缺少 token_epoch。"""
    db_file = tmp_path / "user_scene.db"

    # 1. 模拟用户线上环境：包含 totp_secret，但缺少 token_epoch
    raw_conn = sqlite3.connect(db_file)
    raw_conn.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(50) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            totp_secret VARCHAR(64),
            created_at DATETIME NOT NULL
        )
        """
    )
    raw_conn.execute(
        """
        INSERT INTO users (username, password_hash, totp_secret, created_at)
        VALUES ('admin', 'hashed_pw', NULL, '2026-01-01 00:00:00')
        """
    )
    raw_conn.commit()
    raw_conn.close()

    engine = create_engine(f"sqlite:///{db_file}")
    SessionLocal = sessionmaker(bind=engine)

    # 2. 未迁移前，查询 User 会精确抛出与用户日志一致的 OperationalError: no such column: users.token_epoch
    with SessionLocal() as session:
        with pytest.raises(Exception) as exc_info:
            session.query(User).first()
        assert "no such column: users.token_epoch" in str(exc_info.value).lower()

    # 3. 执行轻量自动迁移
    run_migrations(engine)

    # 4. 验证列已成功增加
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("users")}
    assert "token_epoch" in columns

    # 5. 迁移后查询 User 成功，旧用户的 token_epoch 默认填充为 1
    with SessionLocal() as session:
        user = session.query(User).filter_by(username="admin").first()
        assert user is not None
        assert user.username == "admin"
        assert int(user.token_epoch) == 1

    # 6. 测试幂等性：再次执行迁移不会报错
    run_migrations(engine)


def test_migrations_missing_both_totp_and_epoch(tmp_path):
    """测试更早版本的数据库（同时缺少 totp_secret 与 token_epoch）也能一次性补齐。"""
    db_file = tmp_path / "legacy.db"

    raw_conn = sqlite3.connect(db_file)
    raw_conn.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(50) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            created_at DATETIME NOT NULL
        )
        """
    )
    raw_conn.execute(
        """
        INSERT INTO users (username, password_hash, created_at)
        VALUES ('legacy_user', 'hashed_pw', '2026-01-01 00:00:00')
        """
    )
    raw_conn.commit()
    raw_conn.close()

    engine = create_engine(f"sqlite:///{db_file}")
    SessionLocal = sessionmaker(bind=engine)

    # 执行迁移
    run_migrations(engine)

    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("users")}
    assert "token_epoch" in columns
    assert "totp_secret" in columns

    with SessionLocal() as session:
        user = session.query(User).filter_by(username="legacy_user").first()
        assert user is not None
        assert int(user.token_epoch) == 1
        assert user.totp_secret is None


def test_migrations_on_fresh_database(tmp_path):
    """验证全新库（由 Base.metadata.create_all 初始化）调用 run_migrations 安全通过。"""
    from backend.core.database import Base

    db_file = tmp_path / "fresh.db"
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(bind=engine)

    # 不抛出任何异常
    run_migrations(engine)

    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("users")}
    assert "token_epoch" in columns
    assert "totp_secret" in columns

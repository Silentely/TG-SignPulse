"""数据库 schema 版本账本测试。

覆盖:
- 全新库/旧库都能升级到当前版本并写入 schema_version
- 重复执行幂等，不重复登记版本
- 缺失迁移函数、数据库版本超前时明确报错
- 迁移按版本号升序执行
"""

import sqlite3

import pytest
from sqlalchemy import create_engine, inspect, text

import backend.core.database as database


def _fresh_engine(tmp_path, name="fresh.db"):
    db_file = tmp_path / name
    engine = create_engine(f"sqlite:///{db_file}")
    database.Base.metadata.create_all(bind=engine)
    return engine


def _legacy_users_engine(tmp_path, name="legacy.db"):
    """构造缺 totp_secret / token_epoch 的旧库，并写入一条用户数据。"""
    db_file = tmp_path / name
    raw = sqlite3.connect(db_file)
    raw.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(50) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            created_at DATETIME NOT NULL
        )
        """
    )
    raw.execute(
        """
        INSERT INTO users (username, password_hash, created_at)
        VALUES ('legacy_user', 'hashed_pw', '2026-01-01 00:00:00')
        """
    )
    raw.commit()
    raw.close()
    return create_engine(f"sqlite:///{db_file}")


def _schema_rows(engine):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT version FROM schema_version ORDER BY version")
        ).fetchall()


def test_fresh_database_records_current_version_and_is_idempotent(tmp_path):
    engine = _fresh_engine(tmp_path)

    database.run_migrations(engine)
    database.run_migrations(engine)  # 幂等：重复执行不报错、不重复登记

    inspector = inspect(engine)
    assert "schema_version" in inspector.get_table_names()
    rows = _schema_rows(engine)
    assert [int(row[0]) for row in rows] == [database.SCHEMA_VERSION]

    columns = {col["name"] for col in inspector.get_columns("users")}
    assert {"totp_secret", "token_epoch"} <= columns


def test_legacy_database_upgrades_without_data_loss(tmp_path):
    engine = _legacy_users_engine(tmp_path)

    database.run_migrations(engine)

    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("users")}
    assert {"totp_secret", "token_epoch"} <= columns
    assert [int(row[0]) for row in _schema_rows(engine)] == [database.SCHEMA_VERSION]

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT username, token_epoch FROM users WHERE username='legacy_user'")
        ).one()
    assert row[0] == "legacy_user"
    assert int(row[1]) == 1

    # 升级后再次执行不产生变化
    database.run_migrations(engine)
    assert len(_schema_rows(engine)) == database.SCHEMA_VERSION


def test_missing_migration_function_raises(tmp_path, monkeypatch):
    engine = _fresh_engine(tmp_path, "missing.db")
    monkeypatch.setattr(database, "SCHEMA_VERSION", 3)
    monkeypatch.setattr(database, "MIGRATIONS", {1: database._migrate_to_v1})

    with pytest.raises(RuntimeError, match="Missing schema migration for v2"):
        database.run_migrations(engine)


def test_database_newer_than_program_is_rejected(tmp_path):
    engine = _fresh_engine(tmp_path, "future.db")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE schema_version ("
                "version INTEGER PRIMARY KEY, applied_at VARCHAR(64) NOT NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO schema_version (version, applied_at) "
                "VALUES (99, '2026-01-01T00:00:00Z')"
            )
        )

    with pytest.raises(RuntimeError, match="高于当前程序支持"):
        database.run_migrations(engine)


def test_migrations_run_in_version_order(tmp_path, monkeypatch):
    engine = _fresh_engine(tmp_path, "ordered.db")
    order = []

    def step_one(conn):
        order.append(1)

    def step_two(conn):
        order.append(2)

    monkeypatch.setattr(database, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(database, "MIGRATIONS", {1: step_one, 2: step_two})

    database.run_migrations(engine)

    assert order == [1, 2]
    assert [int(row[0]) for row in _schema_rows(engine)] == [1, 2]

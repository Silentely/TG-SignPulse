from __future__ import annotations

import logging
from typing import Callable, Optional

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import declarative_base, sessionmaker

from backend.core.config import get_settings
from backend.utils.time import utc_now_iso_z_seconds

logger = logging.getLogger("backend.database")

Base = declarative_base()

# 当前代码期望的数据库 schema 版本。新增结构变更时递增版本号并追加迁移函数。
SCHEMA_VERSION = 1

_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def init_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None and _SessionLocal is not None:
        return

    settings = get_settings()
    url = settings.database_url
    connect_args = {}
    if settings.is_sqlite:
        connect_args = {"check_same_thread": False, "timeout": 30}
    elif url.startswith("postgresql") or url.startswith("postgres"):
        # 常见遗漏：只改了 APP_DATABASE_URL 却未安装驱动
        try:
            import importlib

            if "+psycopg2" in url or url.startswith("postgresql://"):
                importlib.import_module("psycopg2")
            elif "+asyncpg" in url:
                importlib.import_module("asyncpg")
        except ImportError as exc:
            raise RuntimeError(
                "APP_DATABASE_URL 指向 PostgreSQL，但当前环境未安装对应驱动。"
                "请安装 psycopg2-binary（同步）或调整 URL/驱动，"
                "或清空 APP_DATABASE_URL 回退 SQLite。"
            ) from exc

    engine = create_engine(
        url,
        echo=False,
        connect_args=connect_args,
        pool_pre_ping=True,
    )

    if settings.is_sqlite:

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=15000")
            cursor.close()

    _engine = engine
    _SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _migrate_to_v1(conn: Connection) -> None:
    """v1：收编历史上基于列存在性判断的 users 列补齐。

    全新库在 Base.metadata.create_all 后已包含这些列，本步骤为空操作；
    旧库则就地补列，已有数据保持不变。
    """
    inspector = inspect(conn)
    if "users" not in set(inspector.get_table_names()):
        return
    columns = {col["name"] for col in inspector.get_columns("users")}
    if "totp_secret" not in columns:
        logger.info("数据库迁移 v1：补齐 users.totp_secret 列")
        conn.execute(text("ALTER TABLE users ADD COLUMN totp_secret VARCHAR(64)"))
    if "token_epoch" not in columns:
        logger.info("数据库迁移 v1：补齐 users.token_epoch 列")
        conn.execute(
            text("ALTER TABLE users ADD COLUMN token_epoch INTEGER NOT NULL DEFAULT 1")
        )


# 版本号 -> 迁移函数。必须连续覆盖 1..SCHEMA_VERSION，缺失时启动报错。
MIGRATIONS: dict[int, Callable[[Connection], None]] = {
    1: _migrate_to_v1,
}

_SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at VARCHAR(64) NOT NULL
)
"""


def _applied_schema_versions(conn: Connection) -> set[int]:
    rows = conn.execute(text("SELECT version FROM schema_version")).fetchall()
    return {int(row[0]) for row in rows}


def run_migrations(engine: Optional[Engine] = None) -> None:
    """按版本号账本执行未完成的数据库迁移。

    旧库无需人工干预即可从 v0 升级到当前版本；同一库重复执行为空操作。
    缺失迁移函数或数据库版本高于程序时直接抛错，避免静默跳过。
    """
    if engine is None:
        engine = get_engine()

    try:
        with engine.begin() as conn:
            conn.execute(text(_SCHEMA_VERSION_DDL))
            applied = _applied_schema_versions(conn)
            current_version = max(applied, default=0)
            if current_version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"数据库 schema 版本 v{current_version} 高于当前程序支持的 "
                    f"v{SCHEMA_VERSION}，请升级程序版本后再启动"
                )

            for version in range(1, SCHEMA_VERSION + 1):
                if version in applied:
                    continue
                migrate = MIGRATIONS.get(version)
                if migrate is None:
                    raise RuntimeError(f"Missing schema migration for v{version}")
                migrate(conn)
                conn.execute(
                    text(
                        "INSERT INTO schema_version (version, applied_at) "
                        "VALUES (:version, :applied_at)"
                    ),
                    {"version": version, "applied_at": utc_now_iso_z_seconds()},
                )
                logger.info("数据库迁移：已应用 v%s", version)
    except Exception as exc:
        logger.error("数据库迁移失败: %s", exc, exc_info=True)
        raise


def get_engine() -> Engine:
    if _engine is None:
        init_engine()
    return _engine  # type: ignore[return-value]


def get_session_local() -> sessionmaker:
    if _SessionLocal is None:
        init_engine()
    return _SessionLocal  # type: ignore[return-value]


def get_db():
    session_local = get_session_local()
    db = session_local()
    try:
        yield db
    finally:
        db.close()

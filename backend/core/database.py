from __future__ import annotations

from typing import Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

from backend.core.config import get_settings

Base = declarative_base()

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
        pool_pre_ping=not settings.is_sqlite,
    )

    if settings.is_sqlite:

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    _engine = engine
    _SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


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

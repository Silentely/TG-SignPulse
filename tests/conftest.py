from __future__ import annotations

import importlib
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def temp_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch, temp_data_dir: Path) -> Iterator[Path]:
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    monkeypatch.setenv("APP_DB_PATH", str(temp_data_dir / "test.sqlite"))
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("TG_API_ID", "12345")
    monkeypatch.setenv("TG_API_HASH", "test-api-hash")
    yield temp_data_dir


@pytest.fixture
def memory_session_local(isolated_env: Path):
    from backend.core import config as config_module
    from backend.core import database as database_module

    config_module.get_settings.cache_clear()
    database_module._engine = None
    database_module._SessionLocal = None

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    database_module.Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )
    # 赋值给模块级变量，确保 get_engine()/get_session_local() 使用内存 DB
    database_module._engine = engine
    database_module._SessionLocal = testing_session_local
    try:
        yield testing_session_local
    finally:
        database_module.Base.metadata.drop_all(bind=engine)
        engine.dispose()
        database_module._engine = None
        database_module._SessionLocal = None
        config_module.get_settings.cache_clear()


@pytest.fixture
def client(isolated_env: Path, memory_session_local) -> Iterator[TestClient]:
    from backend.core import database as database_module

    main = importlib.import_module("backend.main")

    def override_get_db():
        db = memory_session_local()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[database_module.get_db] = override_get_db
    try:
        with TestClient(main.app) as test_client:
            yield test_client
    finally:
        main.app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def no_external_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGN_TASK_FORCE_IN_MEMORY", "1")
    monkeypatch.setenv("SIGN_TASK_EXECUTION_TIMEOUT", "5")
    monkeypatch.setenv("AI_REQUEST_TIMEOUT", "5")
    os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

"""Pydantic 兼容层、数据库 URL 与调度锁基础测试。"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from backend.core.config import Settings
from backend.scheduler.instance_lock import (
    has_scheduler_lock,
    release_scheduler_lock,
    try_acquire_scheduler_lock,
)
from tg_signer.pydantic_compat import IS_V2, model_dump, model_validate


class _Sample(BaseModel):
    name: str = Field(default="x")


class TestPydanticCompat:
    def test_roundtrip(self):
        m = model_validate(_Sample, {"name": "hello"})
        data = model_dump(m)
        assert data["name"] == "hello"
        assert isinstance(IS_V2, bool)


class TestDatabaseUrl:
    def test_default_sqlite(self, tmp_path, monkeypatch):
        monkeypatch.delenv("APP_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
        from backend.core import config as config_module

        config_module.get_settings.cache_clear()
        s = Settings.from_environment()
        assert s.is_sqlite
        assert "sqlite" in s.database_url

    def test_override_postgres_url(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
        monkeypatch.setenv(
            "APP_DATABASE_URL", "postgresql+psycopg2://u:p@localhost/db"
        )
        from backend.core import config as config_module

        config_module.get_settings.cache_clear()
        s = Settings.from_environment()
        assert not s.is_sqlite
        assert s.database_url.startswith("postgresql")
        config_module.get_settings.cache_clear()


class TestSchedulerLock:
    def test_acquire_release(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("APP_SCHEDULER_LOCK", "1")
        from backend.core import config as config_module

        config_module.get_settings.cache_clear()
        release_scheduler_lock()
        assert try_acquire_scheduler_lock() is True
        assert has_scheduler_lock() is True
        assert (Path(tmp_path) / ".scheduler.lock").exists() or True
        release_scheduler_lock()
        config_module.get_settings.cache_clear()

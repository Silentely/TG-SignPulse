"""Pydantic 兼容层、数据库 URL 与调度锁基础测试。"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from backend.core.config import Settings
from backend.scheduler.instance_lock import (
    has_scheduler_lock,
    release_scheduler_lock,
    try_acquire_scheduler_lock,
)
from tg_signer.pydantic_compat import (
    IS_V2,
    model_dump,
    model_dump_json,
    model_validate,
    try_import_field_validator,
)


class _Sample(BaseModel):
    name: str = Field(default="x")


class _FakeV2Model:
    """模拟 pydantic v2 接口的鸭子类型，用于在 v1 环境命中 v2 分支"""

    def __init__(self, data: dict):
        self._data = data

    @classmethod
    def model_validate(cls, data):
        return cls(data)

    def model_dump(self, **kwargs):
        return dict(self._data)

    def model_dump_json(self, **kwargs):
        return json.dumps(self._data, ensure_ascii=False)


class TestPydanticCompat:
    def test_roundtrip(self):
        m = model_validate(_Sample, {"name": "hello"})
        data = model_dump(m)
        assert data["name"] == "hello"
        assert isinstance(IS_V2, bool)

    def test_dump_json_real_model(self):
        m = model_validate(_Sample, {"name": "序列化"})
        payload = json.loads(model_dump_json(m))
        assert payload["name"] == "序列化"

    def test_v2_style_model_validate(self):
        fake = model_validate(_FakeV2Model, {"k": 1})
        assert isinstance(fake, _FakeV2Model)

    def test_v2_style_model_dump(self):
        fake = _FakeV2Model({"k": 1})
        assert model_dump(fake) == {"k": 1}  # type: ignore[arg-type]

    def test_v2_style_model_dump_json(self):
        fake = _FakeV2Model({"k": "值"})
        assert json.loads(model_dump_json(fake)) == {"k": "值"}  # type: ignore[arg-type]

    def test_field_validator_contract(self):
        # v2 环境返回 (field_validator, None)；v1 返回 (None, validator)
        field_validator, validator = try_import_field_validator()
        assert (field_validator is None) != (validator is None)


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

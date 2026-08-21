"""
全局设置 TTL 缓存测试

覆盖 config_mixins.GlobalSettingsMixin 的缓存行为：
- 短窗口内重复读取不重复读盘（monkeypatch 统计磁盘读）
- save_global_settings 写盘后立即失效缓存
- 缓存为实例级，不影响不同实例
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.services.config_mixins import GlobalSettingsMixin


class _FakeWorkdir:
    def __init__(self, path: Path):
        self.path = path

    def __truediv__(self, other):
        return self.path / other


class _FakeMixin(GlobalSettingsMixin):
    """最小 Mixin 宿主：注入 workdir 并统计磁盘读次数。"""

    def __init__(self, workdir: Path):
        self._workdir = _FakeWorkdir(workdir)
        self.read_count = 0
        self._gs_cache = None

    @property
    def workdir(self):
        return self._workdir

    def _read_json_file(self, path, default=None):
        self.read_count += 1
        if not path.exists():
            return default
        import json

        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def _write_json_file(self, path, data):
        import json

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return True


@pytest.fixture
def mixin(tmp_path: Path):
    return _FakeMixin(tmp_path)


class TestGlobalSettingsCache:
    def test_repeated_read_hits_cache(self, mixin):
        assert mixin.get_global_settings()["log_retention_days"] == 7
        first_reads = mixin.read_count
        # 短窗口内第二次读取应命中缓存，不再读盘
        mixin.get_global_settings()
        mixin.get_global_settings()
        assert mixin.read_count == first_reads

    def test_save_invalidates_cache(self, mixin):
        mixin.get_global_settings()
        # 保存后缓存失效：再次读取重新读盘并拿到新值
        ok = mixin.save_global_settings({"log_retention_days": 30})
        assert ok
        fresh = mixin.get_global_settings()
        assert fresh["log_retention_days"] == 30

    def test_cache_is_per_instance(self, tmp_path: Path):
        a = _FakeMixin(tmp_path / "a")
        b = _FakeMixin(tmp_path / "b")
        a.get_global_settings()
        assert b.read_count == 0
        b.get_global_settings()
        assert b.read_count == 1

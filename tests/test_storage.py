"""backend.utils.storage 数据目录发现 / override 文件 / 可写探测测试"""

from __future__ import annotations

import os
from pathlib import Path

from backend.utils import storage


class TestProbeWritableDir:
    def test_writable_dir_probe_success(self, tmp_path):
        assert storage._probe_writable_dir(tmp_path) is True
        # 探测痕迹应被清理
        assert not (tmp_path / ".probe").exists()

    def test_writable_dir_probe_failure(self, tmp_path, monkeypatch):
        # mkdir 失败 → 回退 False
        def _boom_mkdir(*args, **kwargs):
            raise OSError("permission denied")

        monkeypatch.setattr("pathlib.Path.mkdir", _boom_mkdir)
        assert storage._probe_writable_dir(tmp_path) is False

    def test_unlink_failure_cleans_in_finally(self, tmp_path, monkeypatch):
        # 探测目录内 unlink 失败：try 内回退 False，finally 仍尝试清理
        calls = {"n": 0}

        def _flaky_unlink(self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("busy")
            return None

        monkeypatch.setattr("pathlib.Path.unlink", _flaky_unlink)
        assert storage._probe_writable_dir(tmp_path) is False
        assert calls["n"] >= 2

    def test_is_writable_dir(self, tmp_path):
        assert storage.is_writable_dir(tmp_path) is True


class TestDataDirOverride:
    def test_override_file_default_location(self, monkeypatch, tmp_path):
        monkeypatch.delenv("APP_DATA_DIR_OVERRIDE_FILE", raising=False)
        assert storage.get_data_dir_override_file() == storage._DEFAULT_DATA_DIR_OVERRIDE_FILE

    def test_override_file_from_env(self, monkeypatch, tmp_path):
        target = tmp_path / "custom" / "override.txt"
        monkeypatch.setenv("APP_DATA_DIR_OVERRIDE_FILE", str(target))
        assert storage.get_data_dir_override_file() == target

    def test_load_override_missing_file_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            storage, "get_data_dir_override_file", lambda: tmp_path / "nope.txt"
        )
        assert storage.load_data_dir_override() is None

    def test_load_override_read_error_returns_none(self, monkeypatch, tmp_path):
        path = tmp_path / "override.txt"
        path.write_text("/tmp/whatever", encoding="utf-8")
        monkeypatch.setattr(storage, "get_data_dir_override_file", lambda: path)

        def _boom_read_text(*args, **kwargs):
            raise OSError("io error")

        monkeypatch.setattr("pathlib.Path.read_text", _boom_read_text)
        assert storage.load_data_dir_override() is None

    def test_load_override_empty_value_returns_none(self, monkeypatch, tmp_path):
        path = tmp_path / "override.txt"
        path.write_text("   ", encoding="utf-8")
        monkeypatch.setattr(storage, "get_data_dir_override_file", lambda: path)
        assert storage.load_data_dir_override() is None

    def test_load_override_expands_user(self, monkeypatch, tmp_path):
        path = tmp_path / "override.txt"
        path.write_text("~/my-data", encoding="utf-8")
        monkeypatch.setattr(storage, "get_data_dir_override_file", lambda: path)
        assert storage.load_data_dir_override() == Path(os.path.expanduser("~/my-data"))

    def test_save_and_clear_override(self, monkeypatch, tmp_path):
        target = tmp_path / "saved" / "data"
        path = tmp_path / "nested" / "dirs" / "override.txt"
        monkeypatch.setattr(storage, "get_data_dir_override_file", lambda: path)

        assert storage.save_data_dir_override(target) == target
        assert path.read_text(encoding="utf-8").strip() == str(target)
        assert storage.load_data_dir_override() == target

        storage.clear_data_dir_override()
        assert not path.exists()

    def test_clear_override_missing_file_noop(self, monkeypatch, tmp_path):
        path = tmp_path / "nope.txt"
        monkeypatch.setattr(storage, "get_data_dir_override_file", lambda: path)
        storage.clear_data_dir_override()  # 不抛异常


class TestInitialDataDir:
    def test_env_data_dir_wins(self, monkeypatch, tmp_path):
        target = tmp_path / "env-data"
        monkeypatch.setenv("APP_DATA_DIR", str(target))
        assert storage.get_initial_data_dir() == target

    def test_override_file_second_priority(self, monkeypatch, tmp_path):
        monkeypatch.delenv("APP_DATA_DIR", raising=False)
        override_path = tmp_path / "override.txt"
        target = tmp_path / "override-data"
        override_path.write_text(str(target), encoding="utf-8")
        monkeypatch.setattr(storage, "get_data_dir_override_file", lambda: override_path)
        assert storage.get_initial_data_dir() == target

    def test_default_data_dir(self, monkeypatch, tmp_path):
        monkeypatch.delenv("APP_DATA_DIR", raising=False)
        monkeypatch.setattr(
            storage, "load_data_dir_override", lambda: None
        )
        assert storage.get_initial_data_dir() == Path("/data")


class TestWritableBaseDir:
    def test_cached_result(self, monkeypatch, tmp_path):
        monkeypatch.setattr(storage, "_BASE_DIR", tmp_path)
        assert storage.get_writable_base_dir() == tmp_path

    def test_preferred_data_writable(self, monkeypatch):
        monkeypatch.setattr(storage, "_BASE_DIR", None)
        monkeypatch.setattr(storage, "_probe_writable_dir", lambda p: True)
        assert storage.get_writable_base_dir() == Path("/data")

    def test_fallback_to_tempdir(self, monkeypatch):
        monkeypatch.setattr(storage, "_BASE_DIR", None)
        monkeypatch.setattr(storage, "_probe_writable_dir", lambda p: False)
        base = storage.get_writable_base_dir()
        import tempfile

        assert base == Path(tempfile.gettempdir()) / "tg-signpulse"
        assert base.exists()

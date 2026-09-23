import tarfile
from pathlib import Path

import pytest

from backend.services.backup_archive import (
    DEFAULT_BACKUP_PATHS,
    auto_backup_interval_hours,
    auto_backup_keep,
    create_backup_tarball,
    prune_backups,
    should_run_auto_backup,
)


def test_default_backup_paths_includes_plugins():
    assert "plugins" in DEFAULT_BACKUP_PATHS
    assert "plugin_storage.db" in DEFAULT_BACKUP_PATHS


def test_create_backup_tarball_with_plugins(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "db.sqlite").write_text("sqlite-data")
    (data_dir / "plugin_storage.db").write_text("plugin-kv-data")
    plugins_dir = data_dir / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / "my_plugin.py").write_text("print('hello')")

    dest = tmp_path / "backups" / "backup.tar.gz"
    res = create_backup_tarball(data_dir, dest)
    assert res.exists()

    with tarfile.open(dest, "r:gz") as tar:
        names = tar.getnames()
        assert "db.sqlite" in names
        assert "plugin_storage.db" in names
        assert "plugins/my_plugin.py" in names


def test_create_backup_tarball_empty_raises(tmp_path: Path):
    data_dir = tmp_path / "empty_data"
    data_dir.mkdir()
    dest = tmp_path / "backup.tar.gz"
    with pytest.raises(ValueError, match="没有可备份的文件"):
        create_backup_tarball(data_dir, dest)


def test_prune_backups(tmp_path: Path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    for i in range(5):
        (backup_dir / f"auto-2026010{i}-120000.tar.gz").write_text("test")

    removed = prune_backups(backup_dir, keep=2)
    assert removed == 3
    remaining = list(backup_dir.glob("auto-*.tar.gz"))
    assert len(remaining) == 2


def test_auto_backup_helpers():
    assert should_run_auto_backup({"auto_backup_enabled": True}) is True
    assert should_run_auto_backup({"auto_backup_enabled": False}) is False
    assert should_run_auto_backup(None) is False

    assert auto_backup_interval_hours({"auto_backup_interval_hours": 12}) == 12
    assert auto_backup_interval_hours({"auto_backup_interval_hours": 0}) == 1  # clamped
    assert auto_backup_interval_hours({"auto_backup_interval_hours": 200}) == 168  # clamped
    assert auto_backup_interval_hours(None) == 24

    # 调度器依赖该函数读取保留份数，范围须与设置层钳制一致（1–30）
    assert auto_backup_keep({"auto_backup_keep": 7}) == 7
    assert auto_backup_keep({"auto_backup_keep": 0}) == 1
    assert auto_backup_keep({"auto_backup_keep": 99}) == 30
    assert auto_backup_keep({}) == 3
    assert auto_backup_keep(None) == 3
    assert auto_backup_keep({"auto_backup_keep": "bad"}) == 3

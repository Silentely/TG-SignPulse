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


def test_create_backup_tarball_cleans_temp_on_failure(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "db.sqlite").write_text("sqlite-data")

    dest = tmp_path / "backups" / "backup.tar.gz"

    def flaky_add(*args, **kwargs):
        raise OSError("disk full simulated")

    monkeypatch.setattr(tarfile.TarFile, "add", flaky_add)

    with pytest.raises(OSError, match="disk full simulated"):
        create_backup_tarball(data_dir, dest)

    assert not dest.exists()
    # 确认没有遗留 .tmp 临时文件
    assert list((tmp_path / "backups").glob("*.tmp*")) == []


def test_backup_target_normalization():
    from backend.services.config_mixins import normalize_global_settings

    assert normalize_global_settings({"backup_target": "s3"})["backup_target"] == "s3"
    assert normalize_global_settings({"backup_target": "webdav"})["backup_target"] == "webdav"
    assert normalize_global_settings({"backup_target": "both"})["backup_target"] == "both"
    assert normalize_global_settings({"backup_target": "auto"})["backup_target"] == "auto"
    assert normalize_global_settings({"backup_target": "INVALID"})["backup_target"] == "auto"
    assert normalize_global_settings({"backup_target": ""})["backup_target"] == "auto"
    assert normalize_global_settings({}).get("backup_target", "auto") == "auto"


def test_run_auto_backup_target_selection(tmp_path: Path, monkeypatch):
    from backend.services.backup_archive import run_auto_backup

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "db.sqlite").write_text("sqlite")

    webdav_called = []
    s3_called = []

    def mock_webdav(**kwargs):
        webdav_called.append(kwargs)
        return {"success": True, "remote_url": "http://example.com/backup.tar.gz"}

    async def mock_s3(cfg, path):
        s3_called.append((cfg, path))
        return {"success": True, "url": "https://s3.example.com/backup.tar.gz"}

    monkeypatch.setattr("backend.services.backup_archive._s3_ready", lambda cfg: True)
    monkeypatch.setattr("backend.services.backup_archive._upload_backup_to_s3", mock_s3)
    monkeypatch.setattr("backend.services.backup_archive.prune_backups", lambda d, k: 0)

    import backend.services.webdav_client
    monkeypatch.setattr(backend.services.webdav_client, "upload_file_to_webdav", mock_webdav)
    monkeypatch.setattr(backend.services.webdav_client, "prune_webdav_backups", lambda **kw: {"removed": 0})
    monkeypatch.setattr("backend.services.s3_backup.prune_s3_backups", lambda cfg, keep: {"removed": 0})

    wd_cfg = {"webdav_url": "https://dav.test", "webdav_username": "u", "webdav_password": "p"}
    s3_cfg = {"s3_enabled": True, "s3_endpoint_url": "https://s3.test", "s3_bucket": "b", "s3_access_key": "ak", "s3_secret_key": "sk"}

    # 1. 显式指定 s3，即使配置了 webdav 也仅上传 s3
    webdav_called.clear()
    s3_called.clear()
    res = run_auto_backup(data_dir, webdav_settings=wd_cfg, s3_settings=s3_cfg, backup_target="s3")
    assert res["success"] is True
    assert len(webdav_called) == 0
    assert len(s3_called) == 1

    # 2. 显式指定 both，两者都上传且均成功时清理本地副本
    webdav_called.clear()
    s3_called.clear()
    res = run_auto_backup(data_dir, webdav_settings=wd_cfg, s3_settings=s3_cfg, backup_target="both")
    assert res["success"] is True
    assert len(webdav_called) == 1
    assert len(s3_called) == 1
    assert res["local_removed"] is True

    # 3. 显式指定 both，若某一端失败，则保留本地副本以便容灾
    async def mock_s3_fail(cfg, path):
        raise RuntimeError("S3 upload simulated failure")

    monkeypatch.setattr("backend.services.backup_archive._upload_backup_to_s3", mock_s3_fail)
    webdav_called.clear()
    res_partial = run_auto_backup(data_dir, webdav_settings=wd_cfg, s3_settings=s3_cfg, backup_target="both")
    assert res_partial["success"] is True
    assert res_partial["webdav"]["success"] is True
    assert res_partial["s3"]["success"] is False
    assert res_partial["local_removed"] is False


@pytest.mark.asyncio
async def test_export_backup_archive_both_and_defensive_validation(tmp_path: Path, monkeypatch):
    from fastapi import HTTPException
    from backend.api.routes.ops import export_backup_archive

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "db.sqlite").write_text("sqlite test content")

    cfg_mock = {
        "backup_target": "both",
        "webdav_url": "https://dav.test",
        "webdav_username": "user",
        "webdav_password": "pwd",
        "webdav_remote_dir": "backups",
        "s3_enabled": True,
        "s3_endpoint_url": "https://s3.test",
        "s3_bucket": "my-bucket",
        "s3_access_key": "my-ak",
        "s3_secret_key": "my-sk",
    }

    class MockConfigService:
        def get_global_settings(self):
            return dict(cfg_mock)

    monkeypatch.setattr("backend.services.config.get_config_service", lambda: MockConfigService())
    check_s3 = lambda cfg: bool(cfg.get("s3_enabled") and cfg.get("s3_bucket") and cfg.get("s3_access_key"))
    monkeypatch.setattr("backend.services.s3_backup.s3_enabled", check_s3)
    monkeypatch.setattr("backend.api.routes.ops.s3_enabled", check_s3)

    import backend.services.webdav_client
    monkeypatch.setattr("backend.services.webdav_client.upload_file_to_webdav", lambda **kw: {"success": True, "remote_url": "https://dav.test/b.tar.gz"})

    async def mock_upload_s3(cfg, path):
        return {"success": True, "url": "https://s3.test/b.tar.gz", "size": 2048}

    monkeypatch.setattr("backend.services.s3_backup.upload_backup_to_s3", mock_upload_s3)
    monkeypatch.setattr("backend.api.routes.ops.get_settings", lambda: type("MockSettings", (), {"resolve_base_dir": lambda self: str(data_dir)})())

    class MockUser:
        id = 1
        username = "admin"

    # 1. 成功导出 both 模式，断言 size_bytes > 0
    res = await export_backup_archive(current_user=MockUser())
    assert res["success"] is True
    assert res["mode"] == "both"
    assert res["size_bytes"] > 0
    assert res["webdav_url"] == "https://dav.test/b.tar.gz"
    assert res["s3_url"] == "https://s3.test/b.tar.gz"

    # 2. 当显式指定 both 但 S3 凭据未就绪时，强校验抛出 400
    cfg_mock["s3_enabled"] = False
    with pytest.raises(HTTPException) as exc_info:
        await export_backup_archive(current_user=MockUser())
    assert exc_info.value.status_code == 400
    assert "对象存储未启用" in exc_info.value.detail

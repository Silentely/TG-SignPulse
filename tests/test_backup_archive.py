import os
import stat
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
    assert (
        auto_backup_interval_hours({"auto_backup_interval_hours": 200}) == 168
    )  # clamped
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

    assert normalize_global_settings({"backup_target": "s3"})["backup_target"] == "auto"
    assert (
        normalize_global_settings({"backup_target": "webdav"})["backup_target"]
        == "webdav"
    )
    assert (
        normalize_global_settings({"backup_target": "both"})["backup_target"] == "auto"
    )
    assert (
        normalize_global_settings({"backup_target": "auto"})["backup_target"] == "auto"
    )
    assert (
        normalize_global_settings({"backup_target": "INVALID"})["backup_target"]
        == "auto"
    )
    assert normalize_global_settings({"backup_target": ""})["backup_target"] == "auto"
    assert normalize_global_settings({}).get("backup_target", "auto") == "auto"


def test_run_auto_backup_webdav_selection(tmp_path: Path, monkeypatch):
    from backend.services.backup_archive import run_auto_backup

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "db.sqlite").write_text("sqlite")

    webdav_called = []

    def mock_webdav(**kwargs):
        webdav_called.append(kwargs)
        return {"success": True, "remote_url": "http://example.com/backup.tar.gz"}

    monkeypatch.setattr("backend.services.backup_archive.prune_backups", lambda d, k: 0)

    import backend.services.webdav_client

    monkeypatch.setattr(
        backend.services.webdav_client, "upload_file_to_webdav", mock_webdav
    )
    monkeypatch.setattr(
        backend.services.webdav_client,
        "prune_webdav_backups",
        lambda **kw: {"removed": 0},
    )

    wd_cfg = {
        "webdav_url": "https://dav.test",
        "webdav_username": "u",
        "webdav_password": "p",
    }

    # 1. 显式指定 webdav，上传成功后清理本地副本
    webdav_called.clear()
    res = run_auto_backup(data_dir, webdav_settings=wd_cfg, backup_target="webdav")
    assert res["success"] is True
    assert len(webdav_called) == 1
    assert res["local_removed"] is True

    # 2. 未配置 WebDAV 时，auto 模式保留本地副本
    webdav_called.clear()
    res_local = run_auto_backup(data_dir, webdav_settings={}, backup_target="auto")
    assert res_local["success"] is True
    assert len(webdav_called) == 0
    assert res_local["local_removed"] is False
    assert Path(res_local["path"]).exists()

    # 3. 显式指定 webdav 但 WebDAV 抛错，保留本地副本作为容灾兜底
    def mock_webdav_fail(**kwargs):
        raise RuntimeError("WebDAV connection failed")

    monkeypatch.setattr(
        backend.services.webdav_client, "upload_file_to_webdav", mock_webdav_fail
    )
    res_fail = run_auto_backup(data_dir, webdav_settings=wd_cfg, backup_target="webdav")
    assert res_fail["success"] is True
    assert res_fail["webdav"]["success"] is False
    assert res_fail["local_removed"] is False
    assert Path(res_fail["path"]).exists()


@pytest.mark.asyncio
async def test_export_backup_archive_target_and_validation(tmp_path: Path, monkeypatch):
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    from backend.api.routes.ops import export_backup_archive

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "db.sqlite").write_text("sqlite test content")

    cfg_mock = {
        "backup_target": "auto",
        "webdav_url": "https://dav.test",
        "webdav_username": "user",
        "webdav_password": "pwd",
        "webdav_remote_dir": "backups",
    }

    class MockConfigService:
        def get_global_settings(self):
            return dict(cfg_mock)

    monkeypatch.setattr(
        "backend.services.config.get_config_service", lambda: MockConfigService()
    )

    monkeypatch.setattr(
        "backend.services.webdav_client.upload_file_to_webdav",
        lambda **kw: {
            "success": True,
            "remote_url": "https://dav.test/b.tar.gz",
            "size_bytes": 1024,
        },
    )

    monkeypatch.setattr(
        "backend.api.routes.ops.get_settings",
        lambda: type(
            "MockSettings", (), {"resolve_base_dir": lambda self: str(data_dir)}
        )(),
    )

    class MockUser:
        id = 1
        username = "admin"

    # 1. WebDAV 模式成功上传
    res = await export_backup_archive(target="webdav", current_user=MockUser())
    assert res["success"] is True
    assert res["mode"] == "webdav"
    assert res["size_bytes"] > 0
    assert res["remote_url"] == "https://dav.test/b.tar.gz"

    # 2. 显式指定 download 模式返回 FileResponse
    res_dl = await export_backup_archive(target="download", current_user=MockUser())
    assert isinstance(res_dl, FileResponse)
    assert res_dl.filename.endswith(".tar.gz")

    # 3. 显式指定 webdav 但 URL 未配置，强校验抛出 400
    cfg_mock["webdav_url"] = ""
    with pytest.raises(HTTPException) as exc_info:
        await export_backup_archive(target="webdav", current_user=MockUser())
    assert exc_info.value.status_code == 400
    assert "WebDAV 服务地址未配置" in exc_info.value.detail

    # 4. 显式非法 target 抛出 400，严禁静默回退 auto 触发远端上传
    cfg_mock["webdav_url"] = "https://dav.test"
    with pytest.raises(HTTPException) as exc_info:
        await export_backup_archive(target="invalid", current_user=MockUser())
    assert exc_info.value.status_code == 400
    assert "无效的备份目标" in exc_info.value.detail

    # 5. backup_status 归一化历史 backup_target
    from backend.api.routes.ops import backup_status

    cfg_mock["backup_target"] = "s3"
    status_res = backup_status(current_user=MockUser())
    assert status_res.backup_target == "auto"

    cfg_mock["backup_target"] = "webdav"
    status_res_wd = backup_status(current_user=MockUser())
    assert status_res_wd.backup_target == "webdav"


class TestBackupArchivePermissions:
    """备份归档含 session/凭据/数据库，权限必须收敛，不受进程 umask 影响。"""

    def test_archive_and_dir_are_0600_0700_under_permissive_umask(self, tmp_path: Path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "db.sqlite").write_text("sqlite-data")
        sessions_dir = data_dir / "sessions"
        sessions_dir.mkdir()
        (sessions_dir / "acc.session").write_text("session-payload")

        backup_dir = tmp_path / "backups"
        dest = backup_dir / "backup.tar.gz"

        old_umask = os.umask(0o022)
        try:
            create_backup_tarball(data_dir, dest)
        finally:
            os.umask(old_umask)

        assert stat.S_IMODE(os.stat(dest).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(backup_dir).st_mode) == 0o700

    def test_members_are_normalized_to_0600_0700(self, tmp_path: Path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        db = data_dir / "db.sqlite"
        db.write_text("sqlite-data")
        os.chmod(db, 0o644)  # 源文件宽松权限，归档内必须被收敛

        sessions_dir = data_dir / "sessions"
        sessions_dir.mkdir()
        os.chmod(sessions_dir, 0o755)
        sess = sessions_dir / "acc.session"
        sess.write_text("session-payload")
        os.chmod(sess, 0o644)

        dest = tmp_path / "backup.tar.gz"
        create_backup_tarball(data_dir, dest)

        with tarfile.open(dest, "r:gz") as tar:
            modes = {m.name: stat.S_IMODE(m.mode) for m in tar.getmembers()}
        assert modes["db.sqlite"] == 0o600
        assert modes["sessions"] == 0o700
        assert modes["sessions/acc.session"] == 0o600

    def test_extracted_archive_keeps_restricted_permissions(self, tmp_path: Path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "db.sqlite").write_text("sqlite-data")

        dest = tmp_path / "backup.tar.gz"
        create_backup_tarball(data_dir, dest)

        extract_dir = tmp_path / "restored"
        extract_dir.mkdir()
        with tarfile.open(dest, "r:gz") as tar:
            tar.extractall(extract_dir)

        restored = extract_dir / "db.sqlite"
        assert restored.read_text() == "sqlite-data"
        assert stat.S_IMODE(os.stat(restored).st_mode) == 0o600

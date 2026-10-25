import json
import sqlite3
import tarfile
import threading

import pytest

from backend.services.backup_archive import (
    create_backup_tarball,
    extract_backup_archive,
)


def test_manifest_covers_all_subsystems_and_excludes_wal(tmp_path):
    from backend.services.backup_manifest import build_backup_manifest

    entries = build_backup_manifest(tmp_path)
    paths = {entry.relative_path for entry in entries}
    assert {
        "plugins",
        "plugin_storage.db",
        "notification_outbox.db",
        "run_artifacts",
        "signs",
        "monitors",
        "semantic",
        ".jev_config.json",
        "data_dicts",
        "sessions",
        "history",
    } <= paths
    assert not any(path.endswith(("-wal", "-shm")) for path in paths)


def test_manifest_includes_custom_paths_and_reports_external_paths(
    tmp_path, monkeypatch
):
    from backend.services.backup_manifest import (
        build_backup_manifest,
        external_backup_paths,
    )

    data = tmp_path / "data"
    data.mkdir()
    custom_db = data / "custom.sqlite"
    external_sessions = tmp_path / "sessions-outside"
    monkeypatch.setenv("APP_DB_PATH", str(custom_db))
    monkeypatch.setenv("APP_SESSION_DIR", str(external_sessions))

    paths = {entry.relative_path for entry in build_backup_manifest(data)}

    assert "custom.sqlite" in paths
    assert "APP_SESSION_DIR" in external_backup_paths(data)


def test_archive_snapshots_live_sqlite_and_validates_hashes(tmp_path):
    from backend.services.backup_manifest import validate_backup_manifest

    data = tmp_path / "data"
    data.mkdir()
    db = data / "db.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE values_table(value INTEGER)")
    stop = threading.Event()

    def writer():
        with sqlite3.connect(db) as conn:
            while not stop.is_set():
                conn.execute("INSERT INTO values_table VALUES (1)")
                conn.commit()

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        archive = create_backup_tarball(data, tmp_path / "backup.tar.gz")
    finally:
        stop.set()
        thread.join()
    restored = tmp_path / "restored"
    extract_backup_archive(archive, restored)
    report = validate_backup_manifest(archive, restored)
    assert report["version"] == 1
    with sqlite3.connect(restored / "db.sqlite") as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with tarfile.open(archive) as tar:
        assert not any(n.endswith(("-wal", "-shm")) for n in tar.getnames())
    (restored / "db.sqlite").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="hash|integrity"):
        validate_backup_manifest(archive, restored)


def test_manifest_rejects_invalid_version_and_missing_required_file(tmp_path):
    from backend.services.backup_manifest import validate_backup_manifest

    manifest = tmp_path / "backup-manifest.json"
    manifest.write_text(json.dumps({"version": 99, "files": []}))
    with pytest.raises(ValueError, match="version"):
        validate_backup_manifest(tmp_path / "unused", tmp_path)
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "files": [{"path": "missing", "sha256": "x", "required": True}],
            }
        )
    )
    with pytest.raises(ValueError, match="missing"):
        validate_backup_manifest(tmp_path / "unused", tmp_path)


def test_manual_and_auto_share_manifest():
    from backend.api.routes.ops import BACKUP_ARCHIVE_PATHS
    from backend.services.backup_archive import DEFAULT_BACKUP_PATHS

    assert BACKUP_ARCHIVE_PATHS == DEFAULT_BACKUP_PATHS


def test_manual_and_automatic_backups_include_same_persistent_files(tmp_path):
    from backend.services.backup_archive import run_auto_backup

    data = tmp_path / "data"
    data.mkdir()
    expected = {
        "sessions/account.session_string",
        "plugins/example.py",
        "signs/account/task/config.json",
        "monitors/account/rule.json",
        "history/account/run.jsonl",
        "semantic/records.json",
        ".jev_config.json",
        "data_dicts/words.json",
        ".signer/run_artifacts/run.json",
    }
    for name in expected:
        path = data / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
    with sqlite3.connect(data / "plugin_storage.db") as conn:
        conn.execute("CREATE TABLE kv(value TEXT)")
    expected.add("plugin_storage.db")
    for name in ("notification_outbox.db", ".signer/notification_outbox.db"):
        with sqlite3.connect(data / name) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE outbox(value TEXT)")
        expected.add(name)
    manual = create_backup_tarball(data, tmp_path / "manual.tar.gz")
    automatic = run_auto_backup(data)
    assert automatic["success"]
    with tarfile.open(manual) as first, tarfile.open(automatic["path"]) as second:
        assert expected <= set(first.getnames())
        assert set(first.getnames()) == set(second.getnames())


def test_hash_works_without_python311_file_digest(tmp_path, monkeypatch):
    import hashlib

    from backend.services.backup_manifest import file_hash

    payload = b"backup data" * 200000
    path = tmp_path / "large-file"
    path.write_bytes(payload)
    monkeypatch.delattr(hashlib, "file_digest", raising=False)
    assert file_hash(path) == hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize("variable", ["WEB_CONCURRENCY", "UVICORN_WORKERS"])
def test_restore_rejects_multiple_workers(variable, monkeypatch):
    from fastapi import HTTPException

    from backend.api.routes.ops import _ensure_single_process_restore

    monkeypatch.setenv(variable, "2")
    with pytest.raises(HTTPException) as error:
        _ensure_single_process_restore()
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_restore_health_failure_rolls_back_and_reopens_old_data(
    tmp_path, monkeypatch
):
    from backend.api.routes import ops

    data = tmp_path / "data"
    data.mkdir()
    (data / "marker").write_text("old")
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "marker").write_text("new")
    started = []

    async def stop():
        assert ops.restore_in_progress()

    async def start():
        marker = (data / "marker").read_text()
        started.append(marker)
        if marker == "new":
            old = next(tmp_path.glob(".data.restore-old-*"))
            assert (old / "marker").read_text() == "old"
            raise RuntimeError("health failed")

    monkeypatch.setattr(ops, "_stop_restore_services", stop)
    monkeypatch.setattr(ops, "_start_restore_services", start)
    with pytest.raises(RuntimeError, match="health failed"):
        await ops._activate_staged_restore(data, stage)
    assert (data / "marker").read_text() == "old"
    assert started == ["new", "old"]
    assert not ops.restore_in_progress()


@pytest.mark.asyncio
async def test_restore_retains_maintenance_when_rollback_health_also_fails(
    tmp_path, monkeypatch
):
    from backend.api.routes import ops

    data = tmp_path / "data"
    data.mkdir()
    (data / "marker").write_text("old")
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "marker").write_text("new")

    async def stop():
        pass

    async def start():
        raise RuntimeError("unhealthy")

    monkeypatch.setattr(ops, "_stop_restore_services", stop)
    monkeypatch.setattr(ops, "_start_restore_services", start)
    try:
        with pytest.raises(RuntimeError, match="unhealthy"):
            await ops._activate_staged_restore(data, stage)
        assert (data / "marker").read_text() == "old"
        assert ops.restore_in_progress()
    finally:
        ops._restore_maintenance = False


def test_backup_rejects_nested_symlink_escape(tmp_path):
    data = tmp_path / "data"
    (data / "plugins").mkdir(parents=True)
    (data / "plugins" / "safe.py").write_text("safe")
    secret = tmp_path / "secret"
    secret.write_text("secret")
    (data / "plugins" / "escape.py").symlink_to(secret)
    archive = create_backup_tarball(data, tmp_path / "backup.tar.gz")
    with tarfile.open(archive) as tar:
        assert "plugins/safe.py" in tar.getnames()
        assert "plugins/escape.py" not in tar.getnames()


def test_restore_validates_session_encryption_key(tmp_path, monkeypatch):
    from backend.services.backup_manifest import validate_backup_manifest
    from tg_signer.security import encrypt_secret

    monkeypatch.setenv("APP_SECRET_KEY", "original-key")
    (tmp_path / "account.session_string").write_text(encrypt_secret("session"))
    monkeypatch.setenv("APP_SECRET_KEY", "different-key")
    with pytest.raises(ValueError, match="decrypt|APP_SECRET_KEY"):
        validate_backup_manifest(tmp_path / "unused", tmp_path)

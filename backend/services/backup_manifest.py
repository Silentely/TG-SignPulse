"""Single registry and integrity contract for manual and scheduled backups."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

MANIFEST_NAME = "backup-manifest.json"
MANIFEST_VERSION = 1

_CONFIGURED_PATH_VARS = (
    "APP_DB_PATH",
    "APP_SIGNER_WORKDIR",
    "APP_SESSION_DIR",
    "APP_LOGS_DIR",
    "PLUGIN_STORAGE_PATH",
)


def _configured_path(value: str, *, variable: str) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if variable in {"APP_DATABASE_URL", "DATABASE_URL"}:
        if not raw.startswith("sqlite:///"):
            return None
        raw = raw.removeprefix("sqlite:///").split("?", 1)[0]
    return Path(raw).resolve()


def _configured_paths(data_dir: Path) -> list[tuple[str, Path]]:
    values = [(name, os.getenv(name, "")) for name in _CONFIGURED_PATH_VARS]
    values.extend(
        (name, os.getenv(name, "")) for name in ("APP_DATABASE_URL", "DATABASE_URL")
    )
    paths: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for variable, raw in values:
        path = _configured_path(raw, variable=variable)
        if path is not None and path not in seen:
            seen.add(path)
            paths.append((variable, path))
    return paths


@dataclass(frozen=True)
class BackupEntry:
    relative_path: str
    kind: Literal["file", "directory", "sqlite"]
    sensitive: bool = True
    required: bool = False
    exporter: str | None = None


def build_backup_manifest(
    data_dir: Path, *, include_history: bool = True
) -> list[BackupEntry]:
    entries = [
        BackupEntry(name, "sqlite", exporter="sqlite_online_backup")
        for name in ("db.sqlite", "plugin_storage.db", "notification_outbox.db")
    ]
    entries += [
        BackupEntry(name, "directory")
        for name in (
            "plugins",
            "sessions",
            "signs",
            "monitors",
            ".signer",
            "data_dicts",
            "semantic",
            "run_artifacts",
        )
    ]
    entries += [
        BackupEntry(name, "file")
        for name in (
            ".global_settings.json",
            ".openai_config.json",
            ".telegram_api.json",
            ".jev_config.json",
        )
    ]
    if include_history:
        entries += [
            BackupEntry(name, "directory") for name in ("history", "signs_history")
        ]
    existing = {entry.relative_path for entry in entries}
    root = data_dir.resolve()
    for variable, path in _configured_paths(data_dir):
        if path.is_relative_to(root):
            relative = path.relative_to(root).as_posix()
            if relative in existing:
                continue
            is_sqlite = variable in {
                "APP_DB_PATH",
                "PLUGIN_STORAGE_PATH",
                "APP_DATABASE_URL",
                "DATABASE_URL",
            } or path.suffix in {".db", ".sqlite", ".sqlite3"}
            is_directory = variable in {
                "APP_SIGNER_WORKDIR",
                "APP_SESSION_DIR",
                "APP_LOGS_DIR",
            } or (path.exists() and path.is_dir())
            kind = "sqlite" if is_sqlite else ("directory" if is_directory else "file")
            entries.append(
                BackupEntry(
                    relative,
                    kind,
                    exporter="sqlite_online_backup" if is_sqlite else None,
                )
            )
            existing.add(relative)
    return entries


def external_backup_paths(data_dir: Path) -> list[str]:
    """Explicitly report persistent storage that cannot fit a portable data archive."""
    outside = []
    root = data_dir.resolve()
    for name in _CONFIGURED_PATH_VARS + ("APP_DATABASE_URL", "DATABASE_URL"):
        raw = os.getenv(name, "").strip()
        if not raw:
            continue
        path = _configured_path(raw, variable=name)
        if path is None or not path.is_relative_to(root):
            outside.append(name)
    return outside


def snapshot_sqlite_database(db_path: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(
        db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30
    ) as source:
        with sqlite3.connect(destination) as target:
            source.backup(target, pages=256, sleep=0.01)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError(f"SQLite integrity failure: {db_path.name}")
    os.chmod(destination, 0o600)
    return destination


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_backup_manifest(archive_path: Path, data_dir: Path) -> dict[str, Any]:
    """Validate an extracted staging tree before any running data is changed.

    Legacy archives are accepted after SQLite/JSON validation. Versioned archives
    must describe every extracted regular file and match its SHA256 digest.
    """
    root = data_dir.resolve()
    manifest_path = root / MANIFEST_NAME
    report: dict[str, Any] = {"version": 0, "legacy": True, "external_paths": []}
    if manifest_path.exists():
        report = json.loads(manifest_path.read_text())
        if report.get("version") != MANIFEST_VERSION:
            raise ValueError("Unsupported backup manifest version")
        described = set()
        for entry in report.get("files", []):
            name = entry.get("path", "")
            path = (root / name).resolve()
            if not name or not path.is_relative_to(root) or path == root:
                raise ValueError("Invalid backup manifest path")
            if not path.is_file():
                raise ValueError(f"Required backup file missing: {name}")
            if file_hash(path) != entry.get("sha256"):
                raise ValueError(f"Backup hash mismatch: {name}")
            described.add(name)
        actual = {
            p.relative_to(root).as_posix()
            for p in root.rglob("*")
            if p.is_file() and p != manifest_path
        }
        if described != actual:
            raise ValueError("Backup manifest contains unlisted files")
        if not any(
            entry.get("kind") == "sqlite" or entry.get("path") == "db.sqlite"
            for entry in report.get("files", [])
            if isinstance(entry, dict)
        ):
            raise ValueError("Backup manifest is missing a required SQLite database")
    elif not (root / "db.sqlite").is_file():
        # A legacy archive is accepted for compatibility, but it must still be
        # recognizably a TG-SignPulse backup.  Accepting an arbitrary tarball
        # would allow restore to replace the live data directory with an empty
        # freshly-initialized database.
        raise ValueError("Legacy backup is missing db.sqlite")
    for path in root.rglob("*"):
        if not path.is_file() or path == manifest_path:
            continue
        with path.open("rb") as source:
            is_sqlite = source.read(16) == b"SQLite format 3\x00"
        if is_sqlite or path.name in {"db.sqlite", "plugin_storage.db"}:
            try:
                with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as conn:
                    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise ValueError(f"SQLite integrity failure: {path.name}")
            except sqlite3.DatabaseError as exc:
                raise ValueError(f"SQLite integrity failure: {path.name}") from exc
        if path.name in {
            ".global_settings.json",
            ".openai_config.json",
            ".telegram_api.json",
            ".jev_config.json",
            "config.json",
            "records.json",
        }:
            payload = json.loads(path.read_text())
            if not isinstance(payload, dict):
                raise ValueError(f"Invalid configuration: {path.name}")
            _validate_secret_keys(payload)
        elif path.suffix == ".json":
            _validate_secret_keys(json.loads(path.read_text()))
        elif path.suffix == ".session_string":
            _validate_secret_keys(path.read_text().strip())
    return report


def _validate_secret_keys(value: Any) -> None:
    from tg_signer.security import decrypt_secret

    if isinstance(value, dict):
        for child in value.values():
            _validate_secret_keys(child)
    elif isinstance(value, list):
        for child in value:
            _validate_secret_keys(child)
    elif isinstance(value, str) and value.startswith("fernet:"):
        from cryptography.fernet import InvalidToken

        try:
            decrypt_secret(value)
        except (InvalidToken, RuntimeError) as exc:
            raise ValueError(
                "Cannot decrypt backup secrets with the current APP_SECRET_KEY"
            ) from exc

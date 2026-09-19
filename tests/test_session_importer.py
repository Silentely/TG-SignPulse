"""Unit and integration tests for Telethon / Pyrogram session importer."""

from __future__ import annotations

import base64
import socket
import sqlite3
import struct
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pyrogram.errors import AuthKeyUnregistered

from backend.services.telegram.session_importer import (
    detect_session_payload,
    import_session,
    import_telethon_sqlite_session,
    verify_imported_session,
)
from tests.test_api import _auth, _login, api_client, db  # noqa: F401


def _sample_auth_key() -> bytes:
    return b"K" * 256


def _make_telethon_sqlite_bytes(dc_id: int = 2, auth_key: bytes | None = None) -> bytes:
    key = auth_key or _sample_auth_key()
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE sessions ("
        "dc_id INTEGER PRIMARY KEY, "
        "server_address TEXT, "
        "port INTEGER, "
        "auth_key BLOB, "
        "takeout_id INTEGER)"
    )
    conn.execute(
        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
        (dc_id, "149.154.167.50", 443, key, None),
    )
    conn.commit()
    data = conn.serialize()
    conn.close()
    return data


def _make_pyrogram_sqlite_bytes(
    dc_id: int = 2, auth_key: bytes | None = None, user_id: int = 123456
) -> bytes:
    key = auth_key or _sample_auth_key()
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE version (number INTEGER)")
    conn.execute("INSERT INTO version VALUES (3)")
    conn.execute(
        "CREATE TABLE sessions ("
        "dc_id INTEGER PRIMARY KEY, "
        "test_mode INTEGER, "
        "auth_key BLOB, "
        "date INTEGER, "
        "user_id INTEGER, "
        "is_bot INTEGER)"
    )
    conn.execute(
        "INSERT INTO sessions VALUES (?, 0, ?, 0, ?, 0)",
        (dc_id, key, user_id),
    )
    conn.commit()
    data = conn.serialize()
    conn.close()
    return data


def _make_telethon_string_session(
    dc_id: int = 2,
    ip: str = "149.154.167.50",
    port: int = 443,
    auth_key: bytes | None = None,
) -> str:
    key = auth_key or _sample_auth_key()
    ip_bytes = socket.inet_aton(ip)
    packed = struct.pack(">B4sH256s", dc_id, ip_bytes, port, key)
    return "1" + base64.urlsafe_b64encode(packed).decode("ascii")


def _make_pyrogram_string_session(
    dc_id: int = 2,
    api_id: int = 12345,
    auth_key: bytes | None = None,
    user_id: int = 123456,
) -> str:
    key = auth_key or _sample_auth_key()
    packed = struct.pack(">BI?256sQ?", dc_id, api_id, False, key, user_id, False)
    return base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")


class TestSessionImporterDetection:
    def test_detect_pyrogram_string_session(self):
        pyrogram_str = _make_pyrogram_string_session()
        assert detect_session_payload(pyrogram_str) == "pyrogram_string"
        assert detect_session_payload(pyrogram_str.encode("utf-8")) == "pyrogram_string"

    def test_detect_sqlite_by_column_set_distinguishes_telethon_and_pyrogram(self, tmp_path: Path):
        telethon_bytes = _make_telethon_sqlite_bytes()
        assert detect_session_payload(telethon_bytes) == "telethon_sqlite"

        pyrogram_bytes = _make_pyrogram_sqlite_bytes()
        assert detect_session_payload(pyrogram_bytes) == "pyrogram_sqlite"

        # Arbitrary SQLite database without telegram schema
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE foo (id INTEGER PRIMARY KEY, name TEXT)")
        unknown_bytes = conn.serialize()
        conn.close()
        assert detect_session_payload(unknown_bytes) == "unknown"

        # Test from file path
        t_file = tmp_path / "telethon.session"
        t_file.write_bytes(telethon_bytes)
        assert detect_session_payload(str(t_file)) == "telethon_sqlite"

    @pytest.mark.asyncio
    async def test_reject_telethon_string_session_with_clear_error(self, tmp_path: Path):
        telethon_str = _make_telethon_string_session()
        assert detect_session_payload(telethon_str) == "telethon_string"

        with pytest.raises(ValueError, match="Telethon StringSession.*not supported"):
            await import_session(
                account_name="test_telethon_str",
                payload=telethon_str,
                target_dir=tmp_path,
            )


class TestSessionImporterConversionAndVerification:
    def test_import_telethon_sqlite_session_writes_pyrogram_schema(self, tmp_path: Path):
        key = _sample_auth_key()
        source_bytes = _make_telethon_sqlite_bytes(dc_id=4, auth_key=key)

        temp_path = import_telethon_sqlite_session(
            account_name="acc_converted",
            source_bytes=source_bytes,
            target_dir=tmp_path,
        )

        assert temp_path.exists()
        conn = sqlite3.connect(str(temp_path))
        version_row = conn.execute("SELECT number FROM version").fetchone()
        assert version_row[0] in (3, 6)

        session_row = conn.execute(
            "SELECT dc_id, test_mode, auth_key, date, user_id, is_bot FROM sessions"
        ).fetchone()
        assert session_row[0] == 4
        assert session_row[1] == 0
        assert session_row[2] == key
        assert session_row[3] >= 0
        assert session_row[4] == 0
        assert session_row[5] == 0
        conn.close()

    @pytest.mark.asyncio
    async def test_import_rejects_unauthorized_session_after_first_connect_check(self, tmp_path: Path):
        source_bytes = _make_telethon_sqlite_bytes()
        temp_path = import_telethon_sqlite_session(
            account_name="acc_unauth",
            source_bytes=source_bytes,
            target_dir=tmp_path,
        )

        mock_client = MagicMock()
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.get_me = AsyncMock(side_effect=AuthKeyUnregistered())
        mock_client.is_connected = True

        with patch("backend.services.telegram.session_importer.Client", return_value=mock_client):
            with pytest.raises(ValueError, match="IMPORTED_SESSION_UNAUTHORIZED"):
                await verify_imported_session(
                    account_name="acc_unauth",
                    temp_session_path=temp_path,
                    target_dir=tmp_path,
                )

        # Ensure temp file was cleaned up on failure
        assert not temp_path.exists()

    @pytest.mark.asyncio
    async def test_import_does_not_overwrite_existing_account_without_force(self, tmp_path: Path):
        # Create existing session file
        existing_file = tmp_path / "acc_existing.session"
        existing_file.write_bytes(b"existing-session-data")

        pyrogram_str = _make_pyrogram_string_session()
        with pytest.raises(ValueError, match="Account already exists"):
            await import_session(
                account_name="acc_existing",
                payload=pyrogram_str,
                force=False,
                target_dir=tmp_path,
            )

        # Content should remain unchanged
        assert existing_file.read_bytes() == b"existing-session-data"


class TestSessionImporterRoute:
    def test_import_session_route_success(self, api_client, db):  # noqa: F811
        token = _login(api_client)
        svc = MagicMock()
        svc.import_session = AsyncMock(
            return_value={
                "account_name": "acc_import_ok",
                "user_id": 999888,
                "first_name": "ImportedUser",
                "username": "imported_user",
            }
        )

        with patch("backend.api.routes.accounts.get_telegram_service", return_value=svc):
            # Test string session JSON import
            resp = api_client.post(
                "/api/accounts/import-session",
                json={
                    "account_name": "acc_import_ok",
                    "session_type": "string",
                    "session_content": "dummy_content",
                    "force": False,
                },
                headers=_auth(token),
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["user_id"] == 999888
            assert data["first_name"] == "ImportedUser"

            # Test conflict when account exists without force
            svc.import_session.side_effect = ValueError("Account already exists")
            conflict_resp = api_client.post(
                "/api/accounts/import-session",
                json={
                    "account_name": "acc_import_ok",
                    "session_type": "string",
                    "session_content": "dummy_content",
                    "force": False,
                },
                headers=_auth(token),
            )
            assert conflict_resp.status_code == 409

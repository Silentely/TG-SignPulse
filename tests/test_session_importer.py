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
    import_pyrogram_string_session,
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
    conn.execute("CREATE TABLE version (number INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO version VALUES (3)")
    conn.execute(
        "CREATE TABLE sessions ("
        "dc_id INTEGER PRIMARY KEY, "
        "api_id INTEGER, "
        "test_mode INTEGER, "
        "auth_key BLOB, "
        "date INTEGER, "
        "user_id INTEGER, "
        "is_bot INTEGER)"
    )
    conn.execute("CREATE TABLE peers (id INTEGER PRIMARY KEY, access_hash INTEGER, type INTEGER, username TEXT, phone_number TEXT)")
    conn.execute("CREATE TABLE update_state (id INTEGER PRIMARY KEY, pts INTEGER, qts INTEGER, date INTEGER, seq INTEGER)")
    conn.execute(
        "INSERT INTO sessions VALUES (?, 2040, 0, ?, 1700000000, ?, 0)",
        (dc_id, key, user_id),
    )
    conn.commit()
    data = conn.serialize()
    conn.close()
    return data


def _make_pyrogram_v7_sqlite_bytes(
    dc_id: int = 2, auth_key: bytes | None = None, user_id: int = 123456
) -> bytes:
    key = auth_key or _sample_auth_key()
    conn = sqlite3.connect(":memory:")
    from pyrogram.storage.sqlite_storage import SCHEMA
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO version VALUES (7)")
    conn.execute(
        "INSERT INTO sessions VALUES (?, '149.154.167.51', 443, 2040, 0, ?, 1700000000, ?, 0)",
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


def _make_pyrogram_legacy_string_session(
    dc_id: int = 2,
    auth_key: bytes | None = None,
    user_id: int = 123456,
    is_64: bool = False,
) -> str:
    key = auth_key or _sample_auth_key()
    if is_64:
        packed = struct.pack(">B?256sQ?", dc_id, False, key, user_id, False)
    else:
        packed = struct.pack(">B?256sI?", dc_id, False, key, user_id, False)
    return base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")


def _make_telethon_full_schema_sqlite_bytes() -> bytes:
    key = _sample_auth_key()
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE version (version INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO version VALUES (7)")
    conn.execute(
        "CREATE TABLE sessions ("
        "dc_id INTEGER PRIMARY KEY, "
        "server_address TEXT, "
        "port INTEGER, "
        "auth_key BLOB, "
        "takeout_id INTEGER)"
    )
    conn.execute("CREATE TABLE entities (id INTEGER PRIMARY KEY, hash INTEGER, username TEXT, phone INTEGER, name TEXT)")
    conn.execute("CREATE TABLE sent_files (md5_digest BLOB, file_size INTEGER, type INTEGER, id INTEGER, hash INTEGER)")
    conn.execute("CREATE TABLE update_state (id INTEGER PRIMARY KEY, pts INTEGER, qts INTEGER, date INTEGER, seq INTEGER)")
    conn.execute("INSERT INTO sessions VALUES (2, '149.154.167.51', 443, ?, NULL)", (key,))
    conn.commit()
    data = conn.serialize()
    conn.close()
    return data

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

    def test_detect_real_schema_v7_and_v6_pyrogram_sqlite(self):
        v7_bytes = _make_pyrogram_v7_sqlite_bytes()
        v6_bytes = _make_pyrogram_sqlite_bytes()
        # 即使含 update_state 表，也必须准确识别为 pyrogram_sqlite，绝不误判为 telethon_sqlite
        assert detect_session_payload(v7_bytes) == "pyrogram_sqlite"
        assert detect_session_payload(v6_bytes) == "pyrogram_sqlite"

    def test_detect_full_schema_telethon_sqlite(self):
        full_telethon = _make_telethon_full_schema_sqlite_bytes()
        assert detect_session_payload(full_telethon) == "telethon_sqlite"

    def test_detect_legacy_pyrogram_string_sessions(self):
        s32 = _make_pyrogram_legacy_string_session(is_64=False)
        s64 = _make_pyrogram_legacy_string_session(is_64=True)
        assert detect_session_payload(s32) == "pyrogram_string"
        assert detect_session_payload(s64) == "pyrogram_string"

    def test_detect_v7_pyrogram_sqlite_not_misclassified_as_telethon(self):
        v7_bytes = _make_pyrogram_v7_sqlite_bytes()
        assert detect_session_payload(v7_bytes) == "pyrogram_sqlite"

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
        assert version_row[0] in (3, 6, 7)

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
    async def test_import_session_supports_path_string(self, tmp_path: Path):
        from pyrogram.errors import AuthKeyUnregistered

        from backend.services.telegram.session_importer import import_session

        v7_file = tmp_path / "source_acc.session"
        v7_file.write_bytes(_make_pyrogram_v7_sqlite_bytes())

        mock_client = MagicMock()
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.get_me = AsyncMock(side_effect=AuthKeyUnregistered())
        mock_client.is_connected = True

        with patch("backend.services.telegram.session_importer.Client", return_value=mock_client):
            with pytest.raises(ValueError, match="IMPORTED_SESSION_UNAUTHORIZED"):
                await import_session("test_from_path", str(v7_file), target_dir=tmp_path)

    def test_import_pyrogram_legacy_string_sessions_preserves_auth_key_and_ids(self, tmp_path: Path):
        key = _sample_auth_key()
        # Test 1: legacy 32-bit format (263 bytes raw, 351/352 chars)
        s32 = _make_pyrogram_legacy_string_session(dc_id=2, auth_key=key, user_id=123456, is_64=False)
        dest32 = import_pyrogram_string_session("acc_legacy_32", s32, tmp_path)
        conn = sqlite3.connect(dest32)
        row32 = conn.execute("SELECT dc_id, api_id, auth_key, user_id FROM sessions").fetchone()
        conn.close()
        assert row32[0] == 2
        assert row32[1] == 0
        assert row32[2] == key
        assert row32[3] == 123456

        # Test 2: legacy 64-bit format (267 bytes raw, 356 chars, large 64-bit user id)
        large_uid = 9876543210123
        s64 = _make_pyrogram_legacy_string_session(dc_id=4, auth_key=key, user_id=large_uid, is_64=True)
        dest64 = import_pyrogram_string_session("acc_legacy_64", s64, tmp_path)
        conn64 = sqlite3.connect(dest64)
        row64 = conn64.execute("SELECT dc_id, api_id, auth_key, user_id FROM sessions").fetchone()
        conn64.close()
        assert row64[0] == 4
        assert row64[1] == 0
        assert row64[2] == key
        assert row64[3] == large_uid

    def test_insert_session_record_validates_auth_key_length(self):
        from backend.services.telegram.session_importer import insert_session_record
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE sessions (dc_id INTEGER PRIMARY KEY, api_id INTEGER, test_mode INTEGER, auth_key BLOB, date INTEGER, user_id INTEGER, is_bot INTEGER)")
        with pytest.raises(ValueError, match="Invalid auth_key length"):
            insert_session_record(conn.cursor(), dc_id=2, auth_key=b"too_short", date=1700000000, user_id=100)

    def test_import_pyrogram_string_session_preserves_auth_key_and_ids(self, tmp_path: Path):
        key = _sample_auth_key()
        str_session = _make_pyrogram_string_session(dc_id=2, api_id=2040, auth_key=key, user_id=999888)
        dest = import_pyrogram_string_session("test_str_acc", str_session, tmp_path)
        assert dest.exists()
        conn = sqlite3.connect(dest)
        row = conn.execute("SELECT dc_id, server_address, port, api_id, auth_key, user_id FROM sessions").fetchone()
        conn.close()
        assert row[0] == 2
        assert row[1] == "149.154.167.51"
        assert row[2] == 443
        assert row[3] == 2040
        assert row[4] == key
        assert row[5] == 999888

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

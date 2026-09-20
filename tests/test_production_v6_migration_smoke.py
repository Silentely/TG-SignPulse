"""Smoke tests for production V6 session migration to V7 with Kurigram 2.2.26."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest
from pyrogram.storage.sqlite_storage import SQLiteStorage


def _create_v6_session_file(db_path: Path, dc_id: int = 2, user_id: int = 123456789) -> bytes:
    """Create a realistic Pyrogram / Kurigram V6 SQLite session file (7 columns)."""
    fake_auth_key = b"V6_AUTH_KEY_EXACT_256_BYTES" + b"X" * (256 - 28)
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE version (number INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO version VALUES (6)")
    conn.execute(
        """CREATE TABLE sessions (
            dc_id INTEGER PRIMARY KEY,
            api_id INTEGER,
            test_mode INTEGER,
            auth_key BLOB,
            date INTEGER,
            user_id INTEGER,
            is_bot INTEGER
        )"""
    )
    conn.execute(
        """CREATE TABLE peers (
            id INTEGER PRIMARY KEY,
            access_hash INTEGER,
            type TEXT,
            username TEXT,
            phone_number TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO sessions VALUES (?, ?, 0, ?, ?, ?, 0)",
        (dc_id, 2040, fake_auth_key, int(time.time()), user_id),
    )
    conn.commit()
    conn.close()
    return fake_auth_key


@pytest.mark.asyncio
async def test_v6_session_automatically_migrates_to_v7_without_data_loss(tmp_path: Path):
    """Test that Kurigram 2.2.26 SQLiteStorage loads a legacy V6 session and migrates cleanly."""
    session_file = tmp_path / "prod_legacy_account.session"
    expected_auth_key = _create_v6_session_file(session_file, dc_id=2, user_id=987654321)

    # 1. Verify pre-migration state is V6 (7 columns)
    pre_conn = sqlite3.connect(str(session_file))
    pre_ver = pre_conn.execute("SELECT number FROM version").fetchone()[0]
    pre_cols = [r[1] for r in pre_conn.execute("PRAGMA table_info(sessions)").fetchall()]
    pre_conn.close()

    assert pre_ver == 6
    assert len(pre_cols) == 7
    assert "server_address" not in pre_cols
    assert "port" not in pre_cols

    # 2. Simulate Kurigram 2.2.26 opening the session
    storage = SQLiteStorage(name=str(session_file.with_suffix("")), workdir=tmp_path)
    await storage.open()

    # Read through Kurigram API
    dc_id = await storage.dc_id()
    user_id = await storage.user_id()
    auth_key = await storage.auth_key()
    test_mode = await storage.test_mode()

    assert dc_id == 2
    assert user_id == 987654321
    assert auth_key == expected_auth_key
    assert not test_mode

    await storage.close()

    # 3. Verify post-migration SQLite database on disk has been migrated to V7 (9 columns)
    post_conn = sqlite3.connect(str(session_file))
    post_ver = post_conn.execute("SELECT number FROM version").fetchone()[0]
    post_cols = [r[1] for r in post_conn.execute("PRAGMA table_info(sessions)").fetchall()]
    row = post_conn.execute(
        "SELECT dc_id, server_address, port, api_id, auth_key, user_id FROM sessions"
    ).fetchone()
    post_conn.close()

    assert post_ver == 7
    assert "server_address" in post_cols
    assert "port" in post_cols
    assert len(post_cols) == 9
    assert row[0] == 2
    assert row[1] == "149.154.167.51"  # DC 2 official IP
    assert row[2] == 443
    assert row[3] == 2040
    assert row[4] == expected_auth_key
    assert row[5] == 987654321

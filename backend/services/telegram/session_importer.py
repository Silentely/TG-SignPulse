"""Telegram Session Importer: handles Telethon / Pyrogram SQLite and string sessions."""

from __future__ import annotations

import base64
import os
import sqlite3
import struct
import time
from pathlib import Path
from typing import Any, Dict, Optional

from pyrogram import Client
from pyrogram.storage.sqlite_storage import SCHEMA, SQLiteStorage
from pyrogram.storage.storage import Storage

try:
    from pyrogram.storage.sqlite_storage import PROD as _PROD_DCS
    from pyrogram.storage.sqlite_storage import TEST as _TEST_DCS
except ImportError:
    _PROD_DCS = {
        1: "149.154.175.53",
        2: "149.154.167.51",
        3: "149.154.175.100",
        4: "149.154.167.91",
        5: "91.108.56.130",
        203: "91.105.192.100",
    }
    _TEST_DCS = {
        1: "149.154.175.10",
        2: "149.154.167.40",
        3: "149.154.175.117",
    }

from backend.core.config import get_settings
from backend.services.telegram.accounts import mark_account_connected
from backend.utils.account_locks import acquire_account_lock_with_timeout
from backend.utils.names import validate_storage_name
from backend.utils.proxy import build_proxy_dict
from backend.utils.tg_session import (
    get_global_semaphore,
    list_account_names,
    set_account_profile,
)

# Pyrogram session string magic prefix length
# Telethon SQLite schemas:
# version table: version (integer)
# sessions table: dc_id, server_address, port, auth_key (bytes)
# entities table: id, hash, username, phone, name


def get_default_dc_endpoint(dc_id: int, test_mode: bool = False) -> tuple[str, int]:
    """根据 DC ID 获取官方默认服务器 IP 与端口。"""
    dcs = _TEST_DCS if test_mode else _PROD_DCS
    if dc_id not in dcs:
        raise ValueError(f"未知的 Telegram 数据中心 DC {dc_id} (test_mode={test_mode})")
    addr = dcs[dc_id]
    port = 80 if test_mode else 443
    return addr, port


def insert_session_record(
    cursor: sqlite3.Cursor,
    dc_id: int,
    auth_key: bytes,
    date: int,
    user_id: int,
    is_bot: int = 0,
    api_id: int = 0,
    test_mode: int = 0,
    server_address: str | None = None,
    port: int | None = None,
) -> None:
    """统一向 sessions 表插入记录，自适应 V7 (9列) 与旧版 (7列)。"""
    if not isinstance(auth_key, (bytes, bytearray)) or len(auth_key) != 256:
        raise ValueError(
            f"Invalid auth_key length: {len(auth_key) if hasattr(auth_key, '__len__') else type(auth_key)} bytes (expected exactly 256 bytes)"
        )
    columns = [row[1] for row in cursor.execute("PRAGMA table_info(sessions)").fetchall()]
    if "server_address" in columns and "port" in columns:
        if not server_address or not port:
            addr, p = get_default_dc_endpoint(dc_id, bool(test_mode))
            server_address = server_address or addr
            port = port or p
        cursor.execute(
            """INSERT INTO sessions (dc_id, server_address, port, api_id, test_mode, auth_key, date, user_id, is_bot)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                int(dc_id),
                server_address,
                int(port),
                int(api_id),
                int(test_mode),
                auth_key,
                int(date),
                int(user_id),
                int(is_bot),
            ),
        )
    else:
        cursor.execute(
            """INSERT INTO sessions (dc_id, api_id, test_mode, auth_key, date, user_id, is_bot)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (int(dc_id), int(api_id), int(test_mode), auth_key, int(date), int(user_id), int(is_bot)),
        )


def detect_session_payload(payload: bytes | str) -> str:
    """Detect format of session payload: 'telethon_sqlite', 'pyrogram_sqlite', 'pyrogram_string', 'telethon_string'."""
    if isinstance(payload, (str, Path)):
        if isinstance(payload, Path):
            if payload.is_file():
                return detect_session_payload(payload.read_bytes())
            return "unknown"
        payload_stripped = payload.strip()
        try:
            path_cand = Path(payload_stripped)
            if path_cand.is_file():
                return detect_session_payload(path_cand.read_bytes())
        except Exception:
            pass

        # Maybe hex or base64 encoded SQLite (checked before string length fallbacks)
        try:
            raw_bytes = base64.b64decode(payload_stripped)
            if raw_bytes.startswith(b"SQLite format 3"):
                return _inspect_sqlite_bytes(raw_bytes)
        except Exception:
            pass

        # Telethon StringSession: starts with "1" and unpadded base64 decodes to 263 (IPv4) or 275 (IPv6) bytes
        if payload_stripped.startswith("1") and len(payload_stripped) > 1:
            try:
                t_raw = base64.urlsafe_b64decode(payload_stripped[1:] + "=" * (-len(payload_stripped[1:]) % 4))
                if len(t_raw) in (263, 275):
                    return "telethon_string"
            except Exception:
                pass

        # Pyrogram StringSession starts with '1' or 'B' (v2) and contains struct
        try:
            raw = base64.urlsafe_b64decode(payload_stripped + "=" * (-len(payload_stripped) % 4))
            if len(raw) in (271, 267, 263) or len(payload_stripped) in (
                getattr(Storage, "SESSION_STRING_SIZE", 351),
                getattr(Storage, "SESSION_STRING_SIZE_64", 356),
            ):
                return "pyrogram_string"
        except Exception:
            pass

        return "unknown"

    if isinstance(payload, bytes):
        if payload.startswith(b"SQLite format 3"):
            return _inspect_sqlite_bytes(payload)
        # Maybe raw string in bytes
        try:
            text = payload.decode("utf-8").strip()
            return detect_session_payload(text)
        except Exception:
            pass

    return "unknown"


def _inspect_sqlite_bytes(data: bytes) -> str:
    """Inspect SQLite tables in-memory or via temp file to determine schema."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.deserialize(data)
    except AttributeError:
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(data)
            f.flush()
            temp_path = f.name
        try:
            disk_conn = sqlite3.connect(temp_path)
            res = _classify_sqlite_conn(disk_conn)
            disk_conn.close()
            return res
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    else:
        try:
            return _classify_sqlite_conn(conn)
        finally:
            conn.close()


def _classify_sqlite_conn(conn: sqlite3.Connection) -> str:
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "sessions" not in tables:
        return "unknown"

    cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
    }

    # 1. 优先判定 Pyrogram 专属特征（Telethon 绝不包含 peers / usernames 表，而 Pyrogram 无论 V6 还是 V7 必含 peers）
    # 注：Kurigram 原生 SCHEMA 自身包含 update_state 表，绝不可将 update_state 视作 Telethon 独有特征！
    if "peers" in tables or "usernames" in tables:
        return "pyrogram_sqlite"
    if "test_mode" in cols or "is_bot" in cols or "api_id" in cols:
        return "pyrogram_sqlite"
    pyrogram_v7_cols = {
        "dc_id", "server_address", "port", "api_id",
        "test_mode", "auth_key", "date", "user_id", "is_bot"
    }
    if pyrogram_v7_cols.issubset(cols):
        return "pyrogram_sqlite"

    # 2. 判定 Telethon 独有特征（排除共有表 update_state）
    # Telethon 专属标志为 takeout_id 列，或 entities / sent_files 表
    if (
        "takeout_id" in cols
        or "entities" in tables
        or "sent_files" in tables
    ):
        return "telethon_sqlite"

    # 3. 兼容没有额外实体表的极简 Telethon sessions 表 (dc_id, server_address, port, auth_key)
    if "server_address" in cols and "port" in cols and "auth_key" in cols:
        return "telethon_sqlite"

    return "unknown"


def _cleanup_file_and_aux(base_file: Path | str) -> None:
    """Helper to remove session file and auxiliary sqlite journal/wal/shm files."""
    base_file = Path(base_file)
    for path in (
        base_file,
        base_file.with_suffix(base_file.suffix + "-journal"),
        base_file.with_suffix(base_file.suffix + "-wal"),
        base_file.with_suffix(base_file.suffix + "-shm"),
    ):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


def convert_telethon_to_pyrogram_sqlite(
    telethon_db_path: Path, pyrogram_dest_path: Path
) -> None:
    """Convert a Telethon .session SQLite file into Pyrogram-compatible SQLite schema."""
    src_conn = sqlite3.connect(str(telethon_db_path))
    try:
        # Read telethon sessions table: dc_id, server_address, port, auth_key, takeout_id
        cursor = src_conn.cursor()
        cursor.execute("SELECT dc_id, server_address, port, auth_key FROM sessions")
        row = cursor.fetchone()
        if not row:
            raise ValueError("No session record found in Telethon database.")
        dc_id, server_address, port, auth_key = row
        if not auth_key:
            raise ValueError("Telethon session does not contain an auth_key.")

        # Read entities table to guess user_id or phone if present
        user_id = 0
        is_bot = 0
        try:
            cursor.execute("SELECT id FROM entities WHERE id > 0 LIMIT 1")
            ent = cursor.fetchone()
            if ent and ent[0]:
                user_id = int(ent[0])
        except Exception:
            pass
    finally:
        src_conn.close()

    # Create pyrogram sqlite session
    _cleanup_file_and_aux(pyrogram_dest_path)

    dst_conn = sqlite3.connect(str(pyrogram_dest_path))
    try:
        dst_cursor = dst_conn.cursor()
        dst_cursor.executescript(SCHEMA)
        dst_cursor.execute("INSERT INTO version VALUES (?)", (SQLiteStorage.VERSION,))
        insert_session_record(
            dst_cursor,
            dc_id=int(dc_id),
            auth_key=auth_key,
            date=int(time.time()),
            user_id=user_id,
            is_bot=is_bot,
            server_address=server_address,
            port=int(port) if port else None,
        )
        dst_conn.commit()
    finally:
        dst_conn.close()


def import_telethon_sqlite_session(
    account_name: str,
    payload_bytes: Optional[bytes] = None,
    target_dir: Optional[Path] = None,
    *,
    source_bytes: Optional[bytes] = None,
) -> Path:
    raw = payload_bytes if payload_bytes is not None else source_bytes
    if raw is None:
        raise ValueError("Missing payload_bytes")
    if target_dir is None:
        target_dir = get_settings().resolve_session_dir()
    """Import telethon sqlite bytes and write pyrogram temp session."""
    temp_telethon = target_dir / f"{account_name}.telethon.tmp"
    temp_pyrogram = target_dir / f"{account_name}.pyrogram.tmp.session"

    _cleanup_file_and_aux(temp_telethon)
    _cleanup_file_and_aux(temp_pyrogram)

    temp_telethon.write_bytes(raw)
    try:
        convert_telethon_to_pyrogram_sqlite(temp_telethon, temp_pyrogram)
    finally:
        _cleanup_file_and_aux(temp_telethon)

    return temp_pyrogram


def import_pyrogram_sqlite_session(
    account_name: str,
    payload_bytes: Optional[bytes] = None,
    target_dir: Optional[Path] = None,
    *,
    source_bytes: Optional[bytes] = None,
) -> Path:
    raw = payload_bytes if payload_bytes is not None else source_bytes
    if raw is None:
        raise ValueError("Missing payload_bytes")
    if target_dir is None:
        target_dir = get_settings().resolve_session_dir()
    """Validate and write pyrogram sqlite session directly."""
    temp_dest = target_dir / f"{account_name}.pyrogram.tmp.session"
    _cleanup_file_and_aux(temp_dest)
    temp_dest.write_bytes(raw)

    # Validate schema
    conn = sqlite3.connect(str(temp_dest))
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT dc_id, auth_key FROM sessions")
        row = cursor.fetchone()
        if not row or not row[1] or len(row[1]) != 256:
            raise ValueError("Invalid Pyrogram SQLite session: missing or invalid auth_key (must be 256 bytes).")
    finally:
        conn.close()

    return temp_dest


def import_pyrogram_string_session(
    account_name: str, session_string: str, target_dir: Path
) -> Path:
    """Convert Pyrogram SessionString into temporary SQLite session file."""
    session_string = session_string.strip()
    raw = base64.urlsafe_b64decode(session_string + "=" * (-len(session_string) % 4))

    # 严格按照原始解码字节长度精确分支解包：
    # 1. 新版 6 字段格式 (Kurigram 2.2.26+): >BI?256sQ? (271 bytes, base64 长度通常为 362)
    new_v2_len = struct.calcsize(Storage.SESSION_STRING_FORMAT)
    if len(raw) == new_v2_len:
        dc_id, api_id, test_mode, auth_key, user_id, is_bot = struct.unpack(
            Storage.SESSION_STRING_FORMAT, raw
        )
    # 2. 旧版 64 位 user_id 5 字段格式 (Pyrogram v2 / Kurigram <2.2.26): >B?256sQ? (267 bytes, 字符长度 356)
    elif len(raw) == 267:
        dc_id, test_mode, auth_key, user_id, is_bot = struct.unpack(
            ">B?256sQ?", raw
        )
        api_id = 0
    # 3. 旧版 32 位 user_id 5 字段格式 (Pyrogram v1): >B?256sI? (263 bytes, 字符长度 351)
    elif len(raw) == 263:
        dc_id, test_mode, auth_key, user_id, is_bot = struct.unpack(
            ">B?256sI?", raw
        )
        api_id = 0
    else:
        raise ValueError(
            f"Cannot unpack Pyrogram session string: unexpected raw length {len(raw)} bytes"
        )

    temp_dest = target_dir / f"{account_name}.pyrogram.tmp.session"
    _cleanup_file_and_aux(temp_dest)

    conn = sqlite3.connect(str(temp_dest))
    try:
        cursor = conn.cursor()
        cursor.executescript(SCHEMA)
        cursor.execute("INSERT INTO version VALUES (?)", (SQLiteStorage.VERSION,))
        insert_session_record(
            cursor,
            dc_id=dc_id,
            auth_key=auth_key,
            date=int(time.time()),
            user_id=user_id,
            is_bot=int(is_bot),
            api_id=api_id,
            test_mode=int(test_mode),
        )
        conn.commit()
    finally:
        conn.close()

    return temp_dest


async def verify_imported_session(
    account_name: str,
    temp_session_path: Path,
    target_dir: Path,
    proxy: Optional[str] = None,
    api_id: Optional[int] = None,
    api_hash: Optional[str] = None,
) -> Dict[str, Any]:
    """Perform first-connect check with get_me(), update user_id, and atomically persist session."""
    from backend.services.config import get_config_service

    config_service = get_config_service()

    if api_id is None or api_hash is None:
        try:
            from backend.services.telegram.credentials import (
                resolve_telegram_api_credentials,
            )

            tg_config = config_service.get_telegram_config()
            api_id, api_hash = resolve_telegram_api_credentials(
                tg_config,
                env_api_id=os.getenv("TG_API_ID"),
                env_api_hash=os.getenv("TG_API_HASH"),
            )
        except Exception as exc:
            _cleanup_file_and_aux(temp_session_path)
            raise RuntimeError(
                "CREDENTIALS_RESOLUTION_FAILED: Telegram API credentials not configured"
            ) from exc

    # Fail-closed Proxy Gate
    require_proxy = config_service.require_proxy_for_telegram()
    if not proxy or not proxy.strip():
        proxy = config_service.get_global_proxy()

    proxy_dict = None
    if proxy and proxy.strip():
        proxy_dict = build_proxy_dict(proxy)
        if not proxy_dict:
            _cleanup_file_and_aux(temp_session_path)
            raise ValueError("PROXY_INVALID_BLOCKED: Configured proxy string is invalid")
    elif require_proxy:
        _cleanup_file_and_aux(temp_session_path)
        raise ValueError("PROXY_REQUIRED_BLOCKED: Global policy requires a proxy for Telegram connections")

    if proxy_dict:
        from backend.services.telegram.accounts import get_telegram_account_service

        account_svc = get_telegram_account_service()
        try:
            await account_svc.verify_account_proxy(account_name, proxy_dict)
        except Exception:
            _cleanup_file_and_aux(temp_session_path)
            raise

    client_name = str(temp_session_path.with_suffix(""))

    client = Client(
        name=client_name,
        api_id=api_id,
        api_hash=api_hash,
        proxy=proxy_dict,
        no_updates=True,
    )

    try:
        async with get_global_semaphore():
            await client.connect()
            me = await client.get_me()
    except Exception as exc:
        _cleanup_file_and_aux(temp_session_path)
        raise ValueError("IMPORTED_SESSION_UNAUTHORIZED") from exc
    finally:
        try:
            if getattr(client, "is_connected", False):
                await client.disconnect()
        except Exception:
            pass

    if not me or not getattr(me, "id", None):
        _cleanup_file_and_aux(temp_session_path)
        raise ValueError("IMPORTED_SESSION_UNAUTHORIZED")

    user_id = int(me.id)

    # Update user_id and is_bot in temp session SQLite
    is_bot = 1 if getattr(me, "is_bot", False) else 0
    conn = sqlite3.connect(str(temp_session_path))
    try:
        conn.execute("UPDATE sessions SET user_id = ?, is_bot = ?", (user_id, is_bot))
        conn.commit()
    finally:
        conn.close()

    target_file = target_dir / f"{account_name}.session"
    _cleanup_file_and_aux(target_file)
    temp_session_path.replace(target_file)

    # Set account profile and mark connected
    set_account_profile(account_name, proxy=proxy)
    mark_account_connected(account_name)

    # Cache session string
    try:
        from backend.utils.tg_session import _export_session_string_from_file

        _export_session_string_from_file(target_dir, account_name)
    except Exception:
        pass

    return {
        "account_name": account_name,
        "user_id": user_id,
        "first_name": getattr(me, "first_name", None),
        "username": getattr(me, "username", None),
    }


async def import_session(
    account_name: str,
    payload: bytes | str,
    *,
    session_type: str = "auto",
    force: bool = False,
    proxy: Optional[str] = None,
    target_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Validate, convert, and import an external Telegram session."""
    account_name = validate_storage_name(account_name, field_name="account_name")
    if target_dir is None:
        target_dir = get_settings().resolve_session_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    target_file = target_dir / f"{account_name}.session"
    if (target_file.exists() or account_name in list_account_names()) and not force:
        raise ValueError(f"Account already exists: {account_name}")

    payload_type = detect_session_payload(payload)

    if payload_type == "telethon_string":
        raise ValueError(
            "Telethon StringSession is not supported. Please use Telethon .session file or Pyrogram session string."
        )

    if payload_type == "unknown":
        raise ValueError("Unknown or unsupported session payload format.")

    # 统一提取 raw_bytes / str_payload，兼容直接传入本地文件路径 Path 或路径字符串
    if isinstance(payload, Path):
        file_bytes = payload.read_bytes()
        raw_bytes = file_bytes
        str_payload = file_bytes.decode("utf-8", errors="ignore")
    elif isinstance(payload, str):
        path_cand = Path(payload.strip())
        if path_cand.is_file():
            file_bytes = path_cand.read_bytes()
            raw_bytes = file_bytes
            str_payload = file_bytes.decode("utf-8", errors="ignore")
        else:
            try:
                raw_bytes = base64.b64decode(payload)
            except Exception:
                raw_bytes = payload.encode("utf-8")
            str_payload = payload
    else:
        raw_bytes = payload
        str_payload = payload.decode("utf-8", errors="ignore")

    async with acquire_account_lock_with_timeout(account_name, timeout=15.0):
        if payload_type == "telethon_sqlite":
            temp_path = import_telethon_sqlite_session(account_name, raw_bytes, target_dir)
        elif payload_type == "pyrogram_sqlite":
            temp_path = import_pyrogram_sqlite_session(account_name, raw_bytes, target_dir)
        elif payload_type == "pyrogram_string":
            temp_path = import_pyrogram_string_session(account_name, str_payload, target_dir)
        else:
            raise ValueError(f"Unsupported session payload type: {payload_type}")

        return await verify_imported_session(
            account_name=account_name,
            temp_session_path=temp_path,
            target_dir=target_dir,
            proxy=proxy,
        )

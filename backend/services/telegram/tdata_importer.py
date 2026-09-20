"""Telegram Desktop (TData) importer, extractor, and session converter."""

from __future__ import annotations

import contextlib
import logging
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional

from pyrogram.storage.sqlite_storage import SCHEMA, SQLiteStorage

from backend.services.telegram.session_importer import insert_session_record

logger = logging.getLogger(__name__)

HEX_FOLDER_PATTERN = re.compile(r"^[0-9A-Fa-f]{16}$")


def is_valid_tdata_path(path: Path) -> bool:
    """Check if the given directory contains a valid Telegram Desktop tdata structure.

    Checks if path / 'key_datas' exists or if there is a 16-character hexadecimal subfolder.
    """
    if not isinstance(path, Path):
        path = Path(path)

    if not path.is_dir():
        return False

    if (path / "key_datas").is_file():
        return True

    try:
        for child in path.iterdir():
            if child.is_dir() and HEX_FOLDER_PATTERN.match(child.name):
                return True
    except OSError:
        return False

    return False


def extract_tdata_zip(zip_path: Path, target_dir: Path) -> Path:
    """Extract a ZIP archive containing Telegram Desktop tdata safely,

    defending against Zip Slip directory traversal.
    Returns the path to the tdata directory (flattened if nested inside tdata/).
    """
    target_dir = Path(target_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    MAX_TOTAL_UNCOMPRESSED_SIZE = 100 * 1024 * 1024  # 100 MB max uncompressed
    MAX_MEMBER_COUNT = 1000

    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.infolist()
        if len(members) > MAX_MEMBER_COUNT:
            raise ValueError(f"ZIP archive contains too many files ({len(members)} > {MAX_MEMBER_COUNT})")
        total_size = 0
        for member in members:
            total_size += member.file_size
            if total_size > MAX_TOTAL_UNCOMPRESSED_SIZE:
                raise ValueError("ZIP uncompressed size exceeds safe limit (decompression bomb protection)")
            member_name = member.filename
            dest_path = (target_dir / member_name).resolve()
            if target_dir not in dest_path.parents and dest_path != target_dir:
                raise ValueError(
                    f"Zip Slip vulnerability detected: '{member_name}' escapes target directory"
                )

        zf.extractall(target_dir)

    nested_tdata = target_dir / "tdata"
    if nested_tdata.is_dir():
        return nested_tdata

    return target_dir


def _check_opentele_available() -> tuple[Any, Any]:
    """Check if opentele is installed and can be loaded without importing issues."""
    if "opentele" in sys.modules and sys.modules["opentele"] is None:
        raise RuntimeError(
            "TDATA_CONVERTER_UNAVAILABLE: Optional dependency 'opentele' is not installed"
        )

    try:
        import opentele
        from opentele.td import TDesktop

        return opentele, TDesktop
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            "TDATA_CONVERTER_UNAVAILABLE: Optional dependency 'opentele' is not installed"
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            f"TDATA_CONVERTER_UNAVAILABLE: Optional dependency 'opentele' failed to initialize: {exc}"
        ) from exc


def convert_tdata_to_session(
    account_name: str,
    tdata_dir: Path,
    session_dir: Path,
    password: Optional[str] = None,
) -> Path:
    """Convert Telegram Desktop tdata directory to a Pyrogram SQLite session file.

    Requires the optional 'opentele' library.
    """
    opentele, tdesktop_cls = _check_opentele_available()

    tdata_dir = Path(tdata_dir).resolve()
    session_dir = Path(session_dir).resolve()
    session_dir.mkdir(parents=True, exist_ok=True)
    target_session_file = session_dir / f"{account_name}.session"

    td = None
    try:
        # Check if opentele.td.TData.Create exists (e.g. specialized wrappers)
        if hasattr(opentele, "td") and hasattr(opentele.td, "TData") and hasattr(opentele.td.TData, "Create"):
            if password:
                td = opentele.td.TData.Create(str(tdata_dir), password=password)
            else:
                td = opentele.td.TData.Create(str(tdata_dir))
        elif tdesktop_cls:
            td = tdesktop_cls(basePath=str(tdata_dir), passcode=password)
        else:
            raise RuntimeError(
                "TDATA_CONVERTER_UNAVAILABLE: No compatible TData parser found in opentele"
            )
    except Exception as exc:
        err_msg = str(exc).lower()
        err_type = type(exc).__name__.lower()
        if "wrong" in err_msg or "wrong" in err_type or "invalid" in err_msg:
            raise ValueError("TDATA_PASSWORD_INVALID") from None
        if (
            "passcode" in err_msg
            or "password" in err_msg
            or "needed" in err_msg
            or "required" in err_msg
            or "passcode" in err_type
        ):
            if not password:
                raise ValueError("TDATA_PASSWORD_REQUIRED") from None
            raise ValueError("TDATA_PASSWORD_INVALID") from None
        raise

    # Handle object inspection if loaded check is supported
    if hasattr(td, "isLoaded") and callable(td.isLoaded):
        if not td.isLoaded():
            if not password:
                raise ValueError("TDATA_PASSWORD_REQUIRED")
            raise ValueError("TDATA_PASSWORD_INVALID")

    if hasattr(td, "hasPasscode") and callable(td.hasPasscode) and td.hasPasscode() and not password:
        raise ValueError("TDATA_PASSWORD_REQUIRED")

    # If the converted result already created a file or is a path
    if isinstance(td, (str, Path)) and Path(td).is_file():
        shutil.copyfile(Path(td), target_session_file)
        return target_session_file

    if hasattr(td, "ToPyrogram") and callable(td.ToPyrogram):
        try:
            import inspect

            pyro_res = td.ToPyrogram(str(session_dir / account_name))
            if inspect.isawaitable(pyro_res):
                import asyncio

                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop and loop.is_running():
                    import concurrent.futures

                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        pool.submit(asyncio.run, pyro_res).result()
                else:
                    asyncio.run(pyro_res)
        except Exception as e:
            logger.debug("ToPyrogram direct call result: %s", e)

    elif hasattr(td, "ToTelethon") and callable(td.ToTelethon):
        td.ToTelethon(str(session_dir / account_name))

    elif hasattr(td, "mainAccount") or hasattr(td, "authKey"):
        account = getattr(td, "mainAccount", td)
        auth_key_obj = getattr(account, "authKey", None)
        if auth_key_obj:
            dc_id = getattr(auth_key_obj, "dcId", 2)
            key = getattr(auth_key_obj, "key", None)
            user_id = getattr(account, "UserId", getattr(account, "user_id", 0))
            if key:
                conn = sqlite3.connect(target_session_file)
                try:
                    conn.executescript(SCHEMA)
                    conn.execute("INSERT INTO version VALUES (?)", (SQLiteStorage.VERSION,))
                    insert_session_record(
                        conn.cursor(),
                        dc_id=int(dc_id),
                        auth_key=key,
                        date=int(time.time()),
                        user_id=int(user_id),
                    )
                    conn.commit()
                finally:
                    conn.close()

    if target_session_file.is_file():
        return target_session_file

    raise RuntimeError("TDATA_CONVERSION_FAILED: Failed to generate session file from tdata archive")


async def import_tdata_session(
    account_name: str,
    zip_payload: bytes | Path,
    *,
    password: Optional[str] = None,
    force: bool = False,
    proxy: Optional[str] = None,
    target_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Safely unpack TData zip, convert to session, and delegate to Task 9 import_session.

    Guarantees full temporary directory cleanup on both success and failure.
    """
    temp_dir_str = tempfile.mkdtemp(prefix="tdata_import_")
    temp_dir = Path(temp_dir_str)
    try:
        if isinstance(zip_payload, bytes):
            zip_file = temp_dir / "upload.zip"
            zip_file.write_bytes(zip_payload)
        else:
            zip_file = Path(zip_payload)

        extract_dir = temp_dir / "extracted"
        tdata_dir = extract_tdata_zip(zip_file, extract_dir)

        if not is_valid_tdata_path(tdata_dir):
            raise ValueError(
                "TDATA_INVALID_STRUCTURE: Extracted archive does not contain a valid tdata structure (missing key_datas)"
            )

        converted_dir = temp_dir / "converted"
        converted_dir.mkdir(parents=True, exist_ok=True)
        session_file = convert_tdata_to_session(
            account_name=account_name,
            tdata_dir=tdata_dir,
            session_dir=converted_dir,
            password=password,
        )

        from backend.services.telegram.session_importer import import_session

        return await import_session(
            account_name=account_name,
            payload=session_file.read_bytes(),
            session_type="file",
            force=force,
            proxy=proxy,
            target_dir=target_dir,
        )
    finally:
        with contextlib.suppress(Exception):
            shutil.rmtree(temp_dir, ignore_errors=True)

"""Unit and integration tests for Telegram Desktop (TData) importer."""

from __future__ import annotations

import base64
import io
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.telegram.tdata_importer import (
    convert_tdata_to_session,
    extract_tdata_zip,
    import_tdata_session,
    is_valid_tdata_path,
)
from tests.test_api import _auth, _login

pytest_plugins = ("tests.test_api",)


def _create_sample_tdata_zip(nested: bool = True) -> bytes:
    """Create in-memory zip archive with mock tdata structure."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        prefix = "tdata/" if nested else ""
        zf.writestr(f"{prefix}key_datas", b"MOCK_KEY_DATAS_CONTENT")
        zf.writestr(f"{prefix}D87FB34684DE168D/data", b"MOCK_DATA_CONTENT")
    return buf.getvalue()


class TestTDataDetectionAndExtraction:
    def test_is_valid_tdata_path_requires_key_datas(self, tmp_path: Path):
        # 1. Non-existent path
        non_existent = tmp_path / "does_not_exist"
        assert not is_valid_tdata_path(non_existent)

        # 2. Regular file
        reg_file = tmp_path / "file.txt"
        reg_file.write_text("hello")
        assert not is_valid_tdata_path(reg_file)

        # 3. Empty directory
        empty_dir = tmp_path / "empty_dir"
        empty_dir.mkdir()
        assert not is_valid_tdata_path(empty_dir)

        # 4. Directory with key_datas
        valid_dir = tmp_path / "valid_tdata"
        valid_dir.mkdir()
        (valid_dir / "key_datas").write_bytes(b"sample_key_datas")
        assert is_valid_tdata_path(valid_dir)

        # 5. Directory with 16-hex character subfolder
        hex_dir = tmp_path / "hex_tdata"
        hex_dir.mkdir()
        (hex_dir / "D87FB34684DE168D").mkdir()
        assert is_valid_tdata_path(hex_dir)

    def test_extract_tdata_zip_rejects_path_traversal(self, tmp_path: Path):
        # Malicious zip with relative directory escape
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../evil_escape.txt", b"malicious content")
        bad_zip_bytes = buf.getvalue()

        zip_path = tmp_path / "malicious.zip"
        zip_path.write_bytes(bad_zip_bytes)
        target_dir = tmp_path / "extracted_target"
        target_dir.mkdir()

        with pytest.raises(ValueError, match="Zip Slip"):
            extract_tdata_zip(zip_path, target_dir)

        # Ensure malicious file was not extracted outside
        assert not (tmp_path / "evil_escape.txt").exists()

    def test_extract_tdata_zip_handles_nested_tdata_folder(self, tmp_path: Path):
        # Nested zip (tdata/key_datas)
        nested_bytes = _create_sample_tdata_zip(nested=True)
        nested_zip = tmp_path / "nested.zip"
        nested_zip.write_bytes(nested_bytes)
        target_nested = tmp_path / "dest_nested"

        extracted_path_nested = extract_tdata_zip(nested_zip, target_nested)
        assert extracted_path_nested == target_nested / "tdata"
        assert (extracted_path_nested / "key_datas").is_file()

        # Flat zip (key_datas at root)
        flat_bytes = _create_sample_tdata_zip(nested=False)
        flat_zip = tmp_path / "flat.zip"
        flat_zip.write_bytes(flat_bytes)
        target_flat = tmp_path / "dest_flat"

        extracted_path_flat = extract_tdata_zip(flat_zip, target_flat)
        assert extracted_path_flat == target_flat
        assert (extracted_path_flat / "key_datas").is_file()


class TestTDataConversionAndCleanup:
    def test_convert_tdata_missing_optional_dependency_has_clear_error(self, tmp_path: Path):
        tdata_dir = tmp_path / "tdata"
        tdata_dir.mkdir()
        (tdata_dir / "key_datas").write_bytes(b"mock")
        session_dir = tmp_path / "sessions"
        session_dir.mkdir()

        with patch.dict(sys.modules, {"opentele": None, "opentele.td": None}):
            with pytest.raises(RuntimeError) as exc_info:
                convert_tdata_to_session("test_account", tdata_dir, session_dir)
            assert "TDATA_CONVERTER_UNAVAILABLE: Optional dependency 'opentele' is not installed" in str(
                exc_info.value
            )

    @pytest.mark.asyncio
    async def test_tdata_import_cleans_up_temp_dir_on_success_or_failure(self, tmp_path: Path):
        zip_bytes = _create_sample_tdata_zip(nested=True)
        created_temp_dirs: list[Path] = []

        real_mkdtemp = tempfile.mkdtemp

        def tracked_mkdtemp(*args, **kwargs):
            d = real_mkdtemp(*args, **kwargs)
            created_temp_dirs.append(Path(d))
            return d

        with patch("tempfile.mkdtemp", side_effect=tracked_mkdtemp):
            # Failure case (e.g. missing opentele dependency)
            with pytest.raises(RuntimeError, match="TDATA_CONVERTER_UNAVAILABLE"):
                await import_tdata_session(
                    account_name="test_acc",
                    zip_payload=zip_bytes,
                    target_dir=tmp_path / "sessions",
                )

        assert len(created_temp_dirs) == 1
        # The temporary directory must be thoroughly removed
        assert not created_temp_dirs[0].exists()

    def test_convert_tdata_password_handling(self, tmp_path: Path):
        tdata_dir = tmp_path / "tdata"
        tdata_dir.mkdir()
        (tdata_dir / "key_datas").write_bytes(b"mock")
        session_dir = tmp_path / "sessions"
        session_dir.mkdir()

        # Mock opentele with password required
        mock_opentele = MagicMock()
        mock_td_module = MagicMock()
        mock_opentele.td = mock_td_module

        # 1. Password required error
        class MockPasscodeNeeded(Exception):
            pass

        mock_td_module.TData.Create.side_effect = MockPasscodeNeeded("Passcode is needed to decrypt")

        with patch.dict(sys.modules, {"opentele": mock_opentele, "opentele.td": mock_td_module}):
            with pytest.raises(ValueError, match="TDATA_PASSWORD_REQUIRED"):
                convert_tdata_to_session("test_acc", tdata_dir, session_dir, password=None)

        # 2. Password invalid error
        class MockWrongPasscode(Exception):
            pass

        mock_td_module.TData.Create.side_effect = MockWrongPasscode("Wrong passcode provided")

        with patch.dict(sys.modules, {"opentele": mock_opentele, "opentele.td": mock_td_module}):
            with pytest.raises(ValueError, match="TDATA_PASSWORD_INVALID"):
                convert_tdata_to_session("test_acc", tdata_dir, session_dir, password="wrong_pass")


class TestTDataApiEndpoints:
    def test_api_import_tdata_converter_unavailable(self, api_client):
        headers = _auth(_login(api_client))
        zip_bytes = _create_sample_tdata_zip(nested=True)

        resp = api_client.post(
            "/api/accounts/import-session",
            headers=headers,
            files={"file": ("tdata.zip", zip_bytes, "application/zip")},
            data={"account_name": "tdata_test"},
        )
        assert resp.status_code == 400
        assert "TDATA_CONVERTER_UNAVAILABLE" in resp.text

    def test_api_import_tdata_password_required(self, api_client):
        headers = _auth(_login(api_client))
        zip_bytes = _create_sample_tdata_zip(nested=True)

        with patch(
            "backend.services.telegram.tdata_importer.convert_tdata_to_session",
            side_effect=ValueError("TDATA_PASSWORD_REQUIRED"),
        ):
            resp = api_client.post(
                "/api/accounts/import-session",
                headers=headers,
                files={"file": ("tdata.zip", zip_bytes, "application/zip")},
                data={"account_name": "tdata_pwd_test"},
            )
            assert resp.status_code == 400
            assert "TDATA_PASSWORD_REQUIRED" in resp.text

    def test_api_import_tdata_json_base64(self, api_client):
        headers = _auth(_login(api_client))
        zip_bytes = _create_sample_tdata_zip(nested=True)
        b64_zip = base64.b64encode(zip_bytes).decode("ascii")

        resp = api_client.post(
            "/api/accounts/import-session",
            headers=headers,
            json={
                "account_name": "tdata_json_test",
                "session_type": "file",
                "session_content": b64_zip,
            },
        )
        assert resp.status_code == 400
        assert "TDATA_CONVERTER_UNAVAILABLE" in resp.text


def _make_pyrogram_sqlite_bytes(dc_id: int = 2, auth_key: bytes | None = None, user_id: int = 123456) -> bytes:
    key = auth_key or (b"K" * 256)
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


class TestTDataSuccessFlow:
    @pytest.mark.asyncio
    async def test_import_tdata_session_success_mocked(self, tmp_path: Path):
        zip_bytes = _create_sample_tdata_zip(nested=True)
        pyro_sqlite = _make_pyrogram_sqlite_bytes(user_id=88888)

        def mock_convert(account_name, tdata_dir, session_dir, password=None):
            sess_file = session_dir / f"{account_name}.session"
            sess_file.write_bytes(pyro_sqlite)
            return sess_file

        with patch("backend.services.telegram.tdata_importer.convert_tdata_to_session", side_effect=mock_convert):
            with patch("backend.services.telegram.session_importer.verify_imported_session", new_callable=AsyncMock) as mock_verify:
                mock_verify.return_value = {
                    "user_id": 88888,
                    "first_name": "TDataUser",
                    "username": "tdata_user",
                }
                res = await import_tdata_session(
                    account_name="mock_acc",
                    zip_payload=zip_bytes,
                    target_dir=tmp_path / "sessions",
                )
                assert res["user_id"] == 88888
                assert res["first_name"] == "TDataUser"

    def test_api_import_tdata_success_mocked(self, api_client):
        headers = _auth(_login(api_client))
        zip_bytes = _create_sample_tdata_zip(nested=True)
        pyro_sqlite = _make_pyrogram_sqlite_bytes(user_id=77777)

        def mock_convert(account_name, tdata_dir, session_dir, password=None):
            sess_file = session_dir / f"{account_name}.session"
            sess_file.write_bytes(pyro_sqlite)
            return sess_file

        with patch("backend.services.telegram.tdata_importer.convert_tdata_to_session", side_effect=mock_convert):
            with patch("backend.services.telegram.session_importer.verify_imported_session", new_callable=AsyncMock) as mock_verify:
                mock_verify.return_value = {
                    "user_id": 77777,
                    "first_name": "ApiTDataUser",
                    "username": "apitdata",
                }
                resp = api_client.post(
                    "/api/accounts/import-session",
                    headers=headers,
                    files={"file": ("tdata.zip", zip_bytes, "application/zip")},
                    data={"account_name": "api_mock_acc"},
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is True
                assert data["user_id"] == 77777
                assert data["first_name"] == "ApiTDataUser"

"""WebDAV 客户端单元测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.services.webdav_client import (
    _join_url,
    upload_file_to_webdav,
    validate_webdav_url,
)


def test_validate_webdav_url_ok():
    assert validate_webdav_url("https://dav.example.com/path").startswith("https://")


def test_validate_webdav_url_rejects_bad():
    with pytest.raises(ValueError):
        validate_webdav_url("ftp://x")
    with pytest.raises(ValueError):
        validate_webdav_url("")


def test_join_url():
    u = _join_url("https://host/base/path", "backups", "a.tar.gz")
    assert u.endswith("/backups/a.tar.gz")
    assert "base/path" in u


def test_upload_file_to_webdav(tmp_path: Path):
    f = tmp_path / "b.tar.gz"
    f.write_bytes(b"gzip-data")

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.request.return_value = MagicMock(status_code=201, text="")
    mock_client.put.return_value = MagicMock(
        status_code=201, text="", reason_phrase="Created"
    )

    with patch("backend.services.webdav_client.httpx.Client", return_value=mock_client):
        result = upload_file_to_webdav(
            base_url="https://dav.example.com/remote.php/dav/files/u",
            username="u",
            password="p",
            remote_dir="tg-backups",
            local_path=f,
        )
    assert result["success"] is True
    assert result["filename"] == "b.tar.gz"
    mock_client.put.assert_called_once()

"""WebDAV 客户端单元测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.services.webdav_client import (
    _ensure_remote_dirs,
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


def test_ensure_remote_dirs_nested():
    """多级目录应逐段 MKCOL。"""
    client = MagicMock()
    client.request.return_value = MagicMock(status_code=201, text="")
    _ensure_remote_dirs(client, "https://dav.example.com/files/u", "a/b/c")
    assert client.request.call_count == 3
    urls = [c.args[1] for c in client.request.call_args_list]
    assert all(c.args[0] == "MKCOL" for c in client.request.call_args_list)
    assert urls[0].endswith("/a")
    assert urls[1].endswith("/a/b")
    assert urls[2].endswith("/a/b/c")


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
    # 流式：content 为可读文件对象
    put_kw = mock_client.put.call_args
    assert put_kw is not None
    content = put_kw.kwargs.get("content") or (
        put_kw.args[1] if len(put_kw.args) > 1 else None
    )
    assert content is not None
    assert hasattr(content, "read")


def test_upload_nested_remote_dir_mkcol(tmp_path: Path):
    f = tmp_path / "c.tar.gz"
    f.write_bytes(b"x")
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.request.return_value = MagicMock(status_code=405, text="")
    mock_client.put.return_value = MagicMock(
        status_code=201, text="", reason_phrase="Created"
    )
    with patch("backend.services.webdav_client.httpx.Client", return_value=mock_client):
        upload_file_to_webdav(
            base_url="https://dav.example.com/files/u",
            username="u",
            password="p",
            remote_dir="backups/tg/daily",
            local_path=f,
        )
    mkcols = [
        c for c in mock_client.request.call_args_list if c.args[0] == "MKCOL"
    ]
    assert len(mkcols) == 3


def test_upload_http_error_raises(tmp_path: Path):
    f = tmp_path / "d.tar.gz"
    f.write_bytes(b"x")
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.request.return_value = MagicMock(status_code=201, text="")
    mock_client.put.return_value = MagicMock(
        status_code=401, text="unauthorized", reason_phrase="Unauthorized"
    )
    with patch("backend.services.webdav_client.httpx.Client", return_value=mock_client):
        with pytest.raises(RuntimeError, match="401"):
            upload_file_to_webdav(
                base_url="https://dav.example.com/files/u",
                username="u",
                password="bad",
                remote_dir="bk",
                local_path=f,
            )

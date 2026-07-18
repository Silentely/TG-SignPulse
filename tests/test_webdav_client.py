"""WebDAV 客户端单元测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.services.webdav_client import (
    _backup_sort_key,
    _ensure_remote_dirs,
    _join_url,
    _parse_propfind_entries,
    delete_webdav_file,
    download_webdav_file,
    iter_webdav_file,
    list_webdav_files,
    prune_webdav_backups,
    check_webdav_connection,
    upload_file_to_webdav,
    validate_backup_filename,
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


_SAMPLE_PROPFIND = """<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>/remote.php/dav/files/u/bk/</d:href>
    <d:propstat>
      <d:prop>
        <d:resourcetype><d:collection/></d:resourcetype>
        <d:displayname>bk</d:displayname>
      </d:prop>
    </d:propstat>
  </d:response>
  <d:response>
    <d:href>/remote.php/dav/files/u/bk/auto-1.tar.gz</d:href>
    <d:propstat>
      <d:prop>
        <d:resourcetype/>
        <d:getcontentlength>1024</d:getcontentlength>
        <d:getlastmodified>Wed, 01 Jan 2025 12:00:00 GMT</d:getlastmodified>
        <d:displayname>auto-1.tar.gz</d:displayname>
      </d:prop>
    </d:propstat>
  </d:response>
  <d:response>
    <d:href>/remote.php/dav/files/u/bk/readme.txt</d:href>
    <d:propstat>
      <d:prop>
        <d:resourcetype/>
        <d:getcontentlength>10</d:getcontentlength>
        <d:displayname>readme.txt</d:displayname>
      </d:prop>
    </d:propstat>
  </d:response>
</d:multistatus>
"""


def test_parse_propfind_entries_skips_collections():
    entries = _parse_propfind_entries(
        _SAMPLE_PROPFIND, "https://dav.example.com/remote.php/dav/files/u/bk"
    )
    names = {e["name"] for e in entries}
    assert "auto-1.tar.gz" in names
    assert "readme.txt" in names
    assert "bk" not in names


def test_list_webdav_files_filters_tar_gz():
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.request.return_value = MagicMock(
        status_code=207, text=_SAMPLE_PROPFIND
    )
    with patch("backend.services.webdav_client.httpx.Client", return_value=mock_client):
        result = list_webdav_files(
            base_url="https://dav.example.com/remote.php/dav/files/u",
            username="u",
            password="p",
            remote_dir="bk",
            name_suffix=".tar.gz",
        )
    assert result["success"] is True
    assert len(result["files"]) == 1
    assert result["files"][0]["name"] == "auto-1.tar.gz"
    assert result["files"][0]["size_bytes"] == 1024


def test_validate_backup_filename():
    assert validate_backup_filename("auto-20260101-120000.tar.gz").endswith(".tar.gz")
    with pytest.raises(ValueError):
        validate_backup_filename("../etc/passwd.tar.gz")
    with pytest.raises(ValueError):
        validate_backup_filename("a/b.tar.gz")
    with pytest.raises(ValueError):
        validate_backup_filename("notes.txt")


def test_delete_webdav_file():
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.delete.return_value = MagicMock(status_code=204, text="")
    with patch("backend.services.webdav_client.httpx.Client", return_value=mock_client):
        r = delete_webdav_file(
            base_url="https://dav.example.com/files/u",
            username="u",
            password="p",
            remote_dir="bk",
            filename="auto-1.tar.gz",
        )
    assert r["success"] is True
    mock_client.delete.assert_called_once()


def test_download_webdav_file(tmp_path: Path):
    dest = tmp_path / "out.tar.gz"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_bytes = MagicMock(return_value=[b"abc", b"def"])
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.stream.return_value = mock_resp

    with patch("backend.services.webdav_client.httpx.Client", return_value=mock_client):
        path = download_webdav_file(
            base_url="https://dav.example.com/files/u",
            username="u",
            password="p",
            remote_dir="bk",
            filename="auto-1.tar.gz",
            dest_path=dest,
        )
    assert path.read_bytes() == b"abcdef"


def test_prune_webdav_backups_keeps_n():
    files = [
        {"name": f"auto-{i}.tar.gz", "mtime": f"Wed, 0{i} Jan 2025 12:00:00 GMT"}
        for i in range(5, 0, -1)
    ]
    with patch(
        "backend.services.webdav_client.list_webdav_files",
        return_value={"success": True, "files": files},
    ), patch(
        "backend.services.webdav_client.delete_webdav_file",
        return_value={"success": True},
    ) as del_m:
        r = prune_webdav_backups(
            base_url="https://dav.example.com/files/u",
            username="u",
            password="p",
            remote_dir="bk",
            keep=2,
        )
    assert r["removed"] == 3
    assert r["kept"] == 2
    assert del_m.call_count == 3


def test_backup_sort_key_prefers_http_date_and_filename_ts():
    newer = _backup_sort_key(
        {"name": "x.tar.gz", "mtime": "Thu, 02 Jan 2025 12:00:00 GMT"}
    )
    older = _backup_sort_key(
        {"name": "y.tar.gz", "mtime": "Wed, 01 Jan 2025 12:00:00 GMT"}
    )
    assert newer > older
    by_name = _backup_sort_key({"name": "auto-20260102-010203.tar.gz", "mtime": ""})
    by_name_old = _backup_sort_key(
        {"name": "auto-20260101-010203.tar.gz", "mtime": ""}
    )
    assert by_name > by_name_old


def test_iter_webdav_file_yields_chunks():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_bytes = MagicMock(return_value=[b"aa", b"bb"])
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.stream.return_value = mock_resp
    with patch("backend.services.webdav_client.httpx.Client", return_value=mock_client):
        data = b"".join(
            iter_webdav_file(
                base_url="https://dav.example.com/files/u",
                username="u",
                password="p",
                remote_dir="bk",
                filename="auto-1.tar.gz",
            )
        )
    assert data == b"aabb"


def _mock_httpx_client(request_side_effect=None, request_return=None, head_return=None):
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    if request_side_effect is not None:
        mock_client.request.side_effect = request_side_effect
    elif request_return is not None:
        mock_client.request.return_value = request_return
    if head_return is not None:
        mock_client.head.return_value = head_return
    return mock_client


def test_webdav_connection_ok_when_dir_exists():
    """远端目录已存在：PROPFIND 207 → 成功。"""
    mock_client = _mock_httpx_client(
        request_return=MagicMock(status_code=207, text="")
    )
    with patch("backend.services.webdav_client.httpx.Client", return_value=mock_client):
        r = check_webdav_connection(
            base_url="https://dav.example.com/files/u",
            username="u",
            password="p",
            remote_dir="tg-signpulse-backups",
        )
    assert r["success"] is True
    assert r["status_code"] == 207
    assert "成功" in r["message"]


def test_webdav_connection_ok_when_remote_dir_missing_returns_403():
    """
    回归：未备份过时远端目录不存在，部分 WebDAV 对 PROPFIND 返回 403。
    不得误判为鉴权失败；应回退探测 base 并判定连接成功。
    """
    target_403 = MagicMock(status_code=403, text="Forbidden")
    base_207 = MagicMock(status_code=207, text="")

    def _request(method, url, **kwargs):
        # 第一次打 remote_dir → 403；第二次打 base → 207
        if "tg-signpulse-backups" in str(url):
            return target_403
        return base_207

    mock_client = _mock_httpx_client(request_side_effect=_request)
    with patch("backend.services.webdav_client.httpx.Client", return_value=mock_client):
        r = check_webdav_connection(
            base_url="https://dav.example.com/files/u",
            username="u",
            password="p",
            remote_dir="tg-signpulse-backups",
        )
    assert r["success"] is True
    assert r["status_code"] == 207
    assert "首次上传" in r["message"] or "不存在" in r["message"]
    assert mock_client.request.call_count == 2


def test_webdav_connection_ok_when_remote_dir_missing_returns_404():
    """远端目录 404 时回退 base PROPFIND 成功。"""
    target_404 = MagicMock(status_code=404, text="")
    base_207 = MagicMock(status_code=207, text="")

    def _request(method, url, **kwargs):
        if "tg-signpulse-backups" in str(url):
            return target_404
        return base_207

    mock_client = _mock_httpx_client(request_side_effect=_request)
    with patch("backend.services.webdav_client.httpx.Client", return_value=mock_client):
        r = check_webdav_connection(
            base_url="https://dav.example.com/files/u",
            username="u",
            password="p",
            remote_dir="tg-signpulse-backups",
        )
    assert r["success"] is True
    assert "首次上传" in r["message"] or "不存在" in r["message"]


def test_webdav_connection_auth_fail_when_base_also_403():
    """base 与 remote_dir 均 403 → 真正鉴权失败。"""
    always_403 = MagicMock(status_code=403, text="Forbidden")
    mock_client = _mock_httpx_client(request_return=always_403)
    with patch("backend.services.webdav_client.httpx.Client", return_value=mock_client):
        r = check_webdav_connection(
            base_url="https://dav.example.com/files/u",
            username="u",
            password="bad",
            remote_dir="tg-signpulse-backups",
        )
    assert r["success"] is False
    assert "认证失败" in r["message"]
    assert r["status_code"] == 403


def test_webdav_connection_auth_fail_on_401():
    """401 仍按鉴权失败处理（不因 remote_dir 回退掩盖）。"""
    mock_client = _mock_httpx_client(
        request_return=MagicMock(status_code=401, text="Unauthorized")
    )
    with patch("backend.services.webdav_client.httpx.Client", return_value=mock_client):
        r = check_webdav_connection(
            base_url="https://dav.example.com/files/u",
            username="u",
            password="bad",
            remote_dir="tg-signpulse-backups",
        )
    assert r["success"] is False
    assert "401" in r["message"]


def test_webdav_connection_base_only_403_is_auth_fail():
    """未配置 remote_dir 时 base 403 直接鉴权失败。"""
    mock_client = _mock_httpx_client(
        request_return=MagicMock(status_code=403, text="")
    )
    with patch("backend.services.webdav_client.httpx.Client", return_value=mock_client):
        r = check_webdav_connection(
            base_url="https://dav.example.com/files/u",
            username="u",
            password="p",
            remote_dir="",
        )
    assert r["success"] is False
    assert "认证失败" in r["message"]

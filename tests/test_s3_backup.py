from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.s3_backup import (
    S3BackupClient,
    _client_from_cfg,
    _get_signature_key,
    _parse_list_objects,
    prune_s3_backups,
    s3_enabled,
    validate_s3_settings,
)

LIST_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <Name>bk</Name>
  <Contents>
    <Key>tg-signpulse-backups/auto-20260101-010101.tar.gz</Key>
    <Size>10</Size>
    <LastModified>2026-01-01T01:01:01.000Z</LastModified>
  </Contents>
  <Contents>
    <Key>tg-signpulse-backups/auto-20260103-030303.tar.gz</Key>
    <Size>30</Size>
    <LastModified>2026-01-03T03:03:03.000Z</LastModified>
  </Contents>
  <Contents>
    <Key>tg-signpulse-backups/readme.txt</Key>
    <Size>1</Size>
    <LastModified>2026-01-02T02:02:02.000Z</LastModified>
  </Contents>
</ListBucketResult>
"""


def _client(**kw) -> S3BackupClient:
    base = {
        "endpoint_url": "https://s3.example.com",
        "bucket": "bk",
        "access_key": "AK",
        "secret_key": "SK",
    }
    base.update(kw)
    return S3BackupClient(**base)


def test_s3_signature_key():
    key = _get_signature_key("secret", "20260911", "us-east-1", "s3")
    assert isinstance(key, bytes)
    assert len(key) == 32


@pytest.mark.asyncio
async def test_s3_upload_file(tmp_path: Path):
    test_file = tmp_path / "backup-test.tar.gz"
    test_file.write_bytes(b"hello backup archive content")

    client = S3BackupClient(
        endpoint_url="https://s3.us-east-1.amazonaws.com",
        bucket="my-backup-bucket",
        access_key="AKIAEXAMPLE",
        secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        region="us-east-1",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "OK"

    with patch("httpx.AsyncClient.put", new_callable=AsyncMock) as mock_put:
        mock_put.return_value = mock_resp
        result = await client.upload_file(test_file)

        assert result["success"] is True
        assert result["bucket"] == "my-backup-bucket"
        assert result["key"].endswith("backup-test.tar.gz")

        mock_put.assert_called_once()
        call_args = mock_put.call_args
        target_url = call_args[0][0]
        headers = call_args[1]["headers"]

        assert "https://s3.us-east-1.amazonaws.com/my-backup-bucket" in target_url
        assert "Authorization" in headers
        assert "AWS4-HMAC-SHA256" in headers["Authorization"]
        assert "x-amz-date" in headers
        assert "x-amz-content-sha256" in headers


@pytest.mark.asyncio
async def test_s3_upload_file_with_proxy(tmp_path: Path):
    test_file = tmp_path / "backup-proxy.tar.gz"
    test_file.write_bytes(b"content")

    client = S3BackupClient(
        endpoint_url="https://s3.us-east-1.amazonaws.com",
        bucket="my-bucket",
        access_key="AKIAEXAMPLE",
        secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        proxy="http://127.0.0.1:8080",
    )

    created_proxies = []

    class MockAsyncClient:
        def __init__(self, proxy=None, timeout=None):
            created_proxies.append(proxy)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def put(self, url, content=None, headers=None):
            resp = MagicMock()
            resp.status_code = 200
            resp.text = "OK"
            return resp

    with patch("httpx.AsyncClient", side_effect=MockAsyncClient):
        result = await client.upload_file(test_file)
        assert result["success"] is True
        assert created_proxies == ["http://127.0.0.1:8080"]


class TestSettingsValidation:
    def test_missing_fields_raise(self):
        with pytest.raises(ValueError, match="Endpoint"):
            validate_s3_settings(
                endpoint_url="", bucket="b", access_key="a", secret_key="s"
            )
        with pytest.raises(ValueError, match="存储桶"):
            validate_s3_settings(
                endpoint_url="https://x", bucket=" ", access_key="a", secret_key="s"
            )
        with pytest.raises(ValueError, match="Access Key"):
            validate_s3_settings(
                endpoint_url="https://x", bucket="b", access_key="", secret_key="s"
            )
        with pytest.raises(ValueError, match="Secret Key"):
            validate_s3_settings(
                endpoint_url="https://x", bucket="b", access_key="a", secret_key=""
            )

    def test_s3_enabled_requires_all_required_fields(self):
        assert s3_enabled({"s3_enabled": True, "s3_bucket": "b"}) is False
        assert (
            s3_enabled(
                {
                    "s3_enabled": True,
                    "s3_endpoint_url": "https://s3.example.com",
                    "s3_bucket": "b",
                    "s3_access_key": "a",
                    "s3_secret_key": "s",
                }
            )
            is True
        )
        # 未显式启用时不视为已配置
        assert (
            s3_enabled(
                {
                    "s3_endpoint_url": "https://s3.example.com",
                    "s3_bucket": "b",
                    "s3_access_key": "a",
                    "s3_secret_key": "s",
                }
            )
            is False
        )
        assert s3_enabled(None) is False


class TestClientFromCfg:
    def test_defaults_region_and_prefix(self):
        client = _client_from_cfg(
            {
                "s3_endpoint_url": "https://s3.example.com/",
                "s3_bucket": "bk",
                "s3_access_key": "AK",
                "s3_secret_key": "SK",
            }
        )
        assert client.region == "auto"
        assert client.prefix == "tg-signpulse-backups/"
        assert client.endpoint_url == "https://s3.example.com"
        assert client.proxy is None

    def test_uses_configured_values(self):
        client = _client_from_cfg(
            {
                "s3_endpoint_url": "https://minio.local:9000",
                "s3_bucket": "bk",
                "s3_access_key": "AK",
                "s3_secret_key": "SK",
                "s3_region": "us-west-2",
                "s3_prefix": "nested/prefix",
                "s3_proxy": "http://127.0.0.1:7890",
            }
        )
        assert client.region == "us-west-2"
        assert client.prefix == "nested/prefix/"
        assert client.proxy == "http://127.0.0.1:7890"

    def test_missing_required_raises_value_error(self):
        with pytest.raises(ValueError):
            _client_from_cfg({"s3_bucket": "bk"})


class TestParseListObjects:
    def test_filters_suffix_and_sorts_desc(self):
        entries = _parse_list_objects(LIST_XML, suffix=".tar.gz", limit=100)
        assert [e["name"] for e in entries] == [
            "auto-20260103-030303.tar.gz",
            "auto-20260101-010101.tar.gz",
        ]
        assert entries[0]["size_bytes"] == 30
        assert entries[0]["key"].startswith("tg-signpulse-backups/")

    def test_limit_truncates(self):
        entries = _parse_list_objects(LIST_XML, suffix=".tar.gz", limit=1)
        assert len(entries) == 1
        assert entries[0]["name"] == "auto-20260103-030303.tar.gz"

    def test_invalid_xml_raises(self):
        with pytest.raises(RuntimeError, match="解析失败"):
            _parse_list_objects("<not-xml", suffix=".tar.gz", limit=10)


class TestClientRequests:
    @pytest.mark.asyncio
    async def test_list_objects_signs_bucket_query(self):
        client = _client()
        captured = {}

        class _Resp:
            status_code = 200
            text = LIST_XML

        class _MockAsyncClient:
            def __init__(self, proxy=None, timeout=None):
                captured["timeout"] = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, headers=None):
                captured["url"] = url
                captured["headers"] = headers
                return _Resp()

        with patch("httpx.AsyncClient", side_effect=_MockAsyncClient):
            entries = await client.list_objects(limit=5)

        assert "list-type=2" in captured["url"]
        # prefix 经 quote 编码，尾部的 "/" 变成 %2F
        assert "prefix=tg-signpulse-backups%2F" in captured["url"]
        assert captured["url"].endswith("/bk?list-type=2&prefix=tg-signpulse-backups%2F")
        assert len(entries) == 2
        auth = captured["headers"]["Authorization"]
        assert "SignedHeaders=host;x-amz-content-sha256;x-amz-date" in auth
        # Host 由 httpx 自行设置，签名头字典不应重复携带
        assert "host" not in captured["headers"]

    @pytest.mark.asyncio
    async def test_get_object_returns_bytes(self):
        client = _client()
        captured = {}

        class _Resp:
            status_code = 200
            content = b"archive-bytes"

        class _MockAsyncClient:
            def __init__(self, proxy=None, timeout=None):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, headers=None):
                captured["url"] = url
                return _Resp()

        with patch("httpx.AsyncClient", side_effect=_MockAsyncClient):
            data = await client.get_object("auto-1.tar.gz")
        assert data == b"archive-bytes"
        assert captured["url"].endswith(
            "/bk/tg-signpulse-backups/auto-1.tar.gz"
        )

    @pytest.mark.asyncio
    async def test_get_object_error_raises(self):
        client = _client()

        class _Resp:
            status_code = 404
            text = "NoSuchKey"

        class _MockAsyncClient:
            def __init__(self, proxy=None, timeout=None):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, headers=None):
                return _Resp()

        with patch("httpx.AsyncClient", side_effect=_MockAsyncClient):
            with pytest.raises(RuntimeError, match="S3 下载失败"):
                await client.get_object("missing.tar.gz")

    @pytest.mark.asyncio
    async def test_iter_object_yields_response_chunks(self):
        client = _client()

        class _Resp:
            status_code = 200
            text = ""

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def aiter_bytes(self):
                yield b"first"
                yield b"second"

        class _MockAsyncClient:
            def __init__(self, proxy=None, timeout=None):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def stream(self, method, url, headers=None):
                return _Resp()

        with patch("httpx.AsyncClient", side_effect=_MockAsyncClient):
            chunks = [chunk async for chunk in client.iter_object("auto-1.tar.gz")]

        assert chunks == [b"first", b"second"]

    @pytest.mark.asyncio
    async def test_delete_object_accepts_204(self):
        client = _client()
        captured = {}

        class _Resp:
            status_code = 204
            text = ""

        class _MockAsyncClient:
            def __init__(self, proxy=None, timeout=None):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def delete(self, url, headers=None):
                captured["url"] = url
                captured["headers"] = headers
                return _Resp()

        with patch("httpx.AsyncClient", side_effect=_MockAsyncClient):
            await client.delete_object("auto-1.tar.gz")
        assert captured["url"].endswith("/bk/tg-signpulse-backups/auto-1.tar.gz")
        assert "AWS4-HMAC-SHA256" in captured["headers"]["Authorization"]

    @pytest.mark.asyncio
    async def test_delete_object_error_raises(self):
        client = _client()

        class _Resp:
            status_code = 403
            text = "AccessDenied"

        class _MockAsyncClient:
            def __init__(self, proxy=None, timeout=None):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def delete(self, url, headers=None):
                return _Resp()

        with patch("httpx.AsyncClient", side_effect=_MockAsyncClient):
            with pytest.raises(RuntimeError, match="S3 删除失败"):
                await client.delete_object("auto-1.tar.gz")

    @pytest.mark.asyncio
    async def test_check_connection_success(self):
        client = _client()

        class _Resp:
            status_code = 200
            text = LIST_XML

        class _MockAsyncClient:
            def __init__(self, proxy=None, timeout=None):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, headers=None):
                return _Resp()

        with patch("httpx.AsyncClient", side_effect=_MockAsyncClient):
            result = await client.check_connection()
        assert result == {
            "success": True,
            "message": "对象存储连接成功",
            "status_code": 200,
        }

    @pytest.mark.asyncio
    async def test_path_style_endpoint_with_base_path(self):
        """endpoint 带子路径时（如 /minio）canonical URI 与 URL 都要带上该前缀。"""
        client = _client(endpoint_url="https://minio.local/minio")
        captured = {}

        class _Resp:
            status_code = 200
            text = LIST_XML

        class _MockAsyncClient:
            def __init__(self, proxy=None, timeout=None):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, headers=None):
                captured["url"] = url
                return _Resp()

        with patch("httpx.AsyncClient", side_effect=_MockAsyncClient):
            await client.list_objects()
        assert "/minio/bk?list-type=2" in captured["url"]


class TestPruneS3Backups:
    CFG = {
        "s3_enabled": True,
        "s3_endpoint_url": "https://s3.example.com",
        "s3_bucket": "bk",
        "s3_access_key": "AK",
        "s3_secret_key": "SK",
    }

    @pytest.mark.asyncio
    async def test_prune_keeps_newest(self):
        deleted = []

        class _FakeClient:
            async def list_objects(self, name_suffix=".tar.gz", limit=100):
                assert name_suffix == ".tar.gz"
                return [
                    {"name": f"auto-{i}.tar.gz", "key": f"k{i}"} for i in range(5)
                ]

            async def delete_object(self, name, timeout=60.0):
                deleted.append(name)

        with patch("backend.services.s3_backup._client_from_cfg", return_value=_FakeClient()):
            result = await prune_s3_backups(self.CFG, keep=2)
        assert result["success"] is True
        assert result["removed"] == 3
        assert result["kept"] == 2
        assert deleted == ["auto-2.tar.gz", "auto-3.tar.gz", "auto-4.tar.gz"]

    @pytest.mark.asyncio
    async def test_prune_list_failure_reports_error(self):
        class _FakeClient:
            async def list_objects(self, name_suffix=".tar.gz", limit=100):
                raise RuntimeError("boom")

            async def delete_object(self, name, timeout=60.0):
                raise AssertionError("列表失败时不应删除")

        with patch("backend.services.s3_backup._client_from_cfg", return_value=_FakeClient()):
            result = await prune_s3_backups(self.CFG, keep=2)
        assert result["success"] is False
        assert result["removed"] == 0
        assert "boom" in result["error"]

    @pytest.mark.asyncio
    async def test_prune_collects_delete_errors(self):
        class _FakeClient:
            async def list_objects(self, name_suffix=".tar.gz", limit=100):
                return [{"name": "a.tar.gz", "key": "a"}, {"name": "b.tar.gz", "key": "b"}]

            async def delete_object(self, name, timeout=60.0):
                raise RuntimeError(f"denied:{name}")

        with patch("backend.services.s3_backup._client_from_cfg", return_value=_FakeClient()):
            result = await prune_s3_backups(self.CFG, keep=1)
        assert result["success"] is False
        assert result["removed"] == 0
        assert len(result["errors"]) == 1


class TestModuleHelpers:
    @pytest.mark.asyncio
    async def test_list_s3_files_not_configured(self):
        from backend.services.s3_backup import list_s3_files

        result = await list_s3_files({"s3_enabled": False})
        assert result["success"] is False
        assert result["files"] == []
        assert "未配置" in result["message"]

    @pytest.mark.asyncio
    async def test_list_s3_files_success(self):
        from backend.services.s3_backup import list_s3_files

        class _FakeClient:
            async def list_objects(self, name_suffix=".tar.gz", limit=100):
                return [{"name": "auto-1.tar.gz", "key": "k"}]

        cfg = {
            "s3_enabled": True,
            "s3_endpoint_url": "https://s3.example.com",
            "s3_bucket": "bk",
            "s3_access_key": "AK",
            "s3_secret_key": "SK",
        }
        with patch("backend.services.s3_backup._client_from_cfg", return_value=_FakeClient()):
            result = await list_s3_files(cfg)
        assert result["success"] is True
        assert result["files"][0]["name"] == "auto-1.tar.gz"

    @pytest.mark.asyncio
    async def test_check_s3_connection_not_configured(self):
        from backend.services.s3_backup import check_s3_connection

        result = await check_s3_connection({})
        assert result["success"] is False
        assert "未配置" in result["message"]

    @pytest.mark.asyncio
    async def test_download_s3_file_rejects_unsafe_name(self):
        from backend.services.s3_backup import download_s3_file

        with pytest.raises(ValueError):
            await download_s3_file({"s3_enabled": True}, "../../etc/passwd")

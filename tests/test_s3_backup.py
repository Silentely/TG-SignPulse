import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from backend.services.s3_backup import S3BackupClient, _get_signature_key


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

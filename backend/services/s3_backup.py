"""S3 / Cloudflare R2 / MinIO 兼容对象存储备份上传器（轻量纯 Python 原生 SigV4 实现，零 boto3 依赖）。"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("backend.s3_backup")


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _get_signature_key(key: str, date_stamp: str, region_name: str, service_name: str) -> bytes:
    k_date = _sign(("AWS4" + key).encode("utf-8"), date_stamp)
    k_region = _sign(k_date, region_name)
    k_service = _sign(k_region, service_name)
    k_signing = _sign(k_service, "aws4_request")
    return k_signing


class S3BackupClient:
    """轻量 S3 客户端，用于上传备份归档至 S3/R2 桶。"""

    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "auto",
        prefix: str = "tg-signpulse-backups/",
    ) -> None:
        self.endpoint_url = endpoint_url.rstrip("/")
        self.bucket = bucket.strip()
        self.access_key = access_key.strip()
        self.secret_key = secret_key.strip()
        self.region = region.strip() or "auto"
        self.prefix = prefix.strip().strip("/")
        if self.prefix:
            self.prefix += "/"

    def _build_url_and_host(self, object_key: str) -> tuple[str, str, str]:
        """构建目标 URL、host 头与路径。支持路径风格 (Path-Style) 与虚拟主机风格。"""
        parsed = urlparse(self.endpoint_url)
        host = parsed.netloc
        path_prefix = parsed.path.rstrip("/")
        
        # 默认使用通用 Path-Style: {endpoint}/{bucket}/{key}
        clean_key = object_key.lstrip("/")
        canonical_uri = f"{path_prefix}/{self.bucket}/{clean_key}" if path_prefix else f"/{self.bucket}/{clean_key}"
        target_url = f"{self.endpoint_url}/{self.bucket}/{clean_key}"
        return target_url, host, canonical_uri

    async def upload_file(self, file_path: Path, object_name: Optional[str] = None) -> Dict[str, Any]:
        """上传本地文件到 S3 存储桶。"""
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        key = f"{self.prefix}{object_name or file_path.name}"
        target_url, host, canonical_uri = self._build_url_and_host(key)

        with open(file_path, "rb") as f:
            data = f.read()

        payload_hash = hashlib.sha256(data).hexdigest()
        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")

        service = "s3"
        canonical_headers = (
            f"host:{host}\n"
            f"x-amz-content-sha256:{payload_hash}\n"
            f"x-amz-date:{amz_date}\n"
        )
        signed_headers = "host;x-amz-content-sha256;x-amz-date"
        canonical_request = (
            f"PUT\n"
            f"{canonical_uri}\n"
            f"\n"
            f"{canonical_headers}\n"
            f"{signed_headers}\n"
            f"{payload_hash}"
        )

        credential_scope = f"{date_stamp}/{self.region}/{service}/aws4_request"
        string_to_sign = (
            f"AWS4-HMAC-SHA256\n"
            f"{amz_date}\n"
            f"{credential_scope}\n"
            f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
        )

        signing_key = _get_signature_key(self.secret_key, date_stamp, self.region, service)
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        authorization_header = (
            f"AWS4-HMAC-SHA256 Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )

        headers = {
            "Host": host,
            "x-amz-date": amz_date,
            "x-amz-content-sha256": payload_hash,
            "Authorization": authorization_header,
            "Content-Type": "application/gzip" if file_path.name.endswith(".gz") else "application/octet-stream",
            "Content-Length": str(len(data)),
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.put(target_url, content=data, headers=headers)
            if resp.status_code not in (200, 201, 204):
                raise RuntimeError(
                    f"S3 上传失败 (HTTP {resp.status_code}): {resp.text[:300]}"
                )

        logger.info("已成功上传备份至 S3 存储桶 [%s]: %s", self.bucket, key)
        return {
            "success": True,
            "bucket": self.bucket,
            "key": key,
            "size": len(data),
            "url": target_url,
        }

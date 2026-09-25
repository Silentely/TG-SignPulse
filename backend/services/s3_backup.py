"""S3 / Cloudflare R2 / MinIO 兼容对象存储备份上传器（轻量纯 Python 原生 SigV4 实现，零 boto3 依赖）。

除上传外还提供列表 / 下载 / 删除 / 清理与连通性探测，供设置页的「备份到对象存储」
分区与自动备份调度复用。签名逻辑统一收在 `S3BackupClient._sign_request`，
新增请求方法时只需给出 method 与 canonical_uri，避免各处重复拼装 SigV4。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional
from urllib.parse import quote, urlparse
from xml.etree import ElementTree

import httpx

logger = logging.getLogger("backend.s3_backup")

# 空 body 的 SHA256：GET/DELETE 等无载荷请求固定用它
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
DEFAULT_REGION = "auto"
DEFAULT_PREFIX = "tg-signpulse-backups"


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _get_signature_key(key: str, date_stamp: str, region_name: str, service_name: str) -> bytes:
    k_date = _sign(("AWS4" + key).encode("utf-8"), date_stamp)
    k_region = _sign(k_date, region_name)
    k_service = _sign(k_region, service_name)
    k_signing = _sign(k_service, "aws4_request")
    return k_signing


def validate_s3_settings(
    *,
    endpoint_url: str,
    bucket: str,
    access_key: str,
    secret_key: str,
) -> None:
    """校验对象存储必填项，缺项抛 ValueError（与 WebDAV 侧校验口径一致）。"""
    if not (endpoint_url or "").strip():
        raise ValueError("S3 Endpoint 未配置")
    if not (bucket or "").strip():
        raise ValueError("S3 存储桶未配置")
    if not (access_key or "").strip():
        raise ValueError("S3 Access Key 未配置")
    if not (secret_key or "").strip():
        raise ValueError("S3 Secret Key 未配置")


class S3BackupClient:
    """轻量 S3 客户端，用于上传备份归档至 S3/R2 桶。"""

    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = DEFAULT_REGION,
        prefix: str = DEFAULT_PREFIX,
        proxy: Optional[str] = None,
    ) -> None:
        self.endpoint_url = endpoint_url.rstrip("/")
        self.bucket = bucket.strip()
        self.access_key = access_key.strip()
        self.secret_key = secret_key.strip()
        self.region = region.strip() or DEFAULT_REGION
        self.prefix = prefix.strip().strip("/")
        if self.prefix:
            self.prefix += "/"
        self.proxy = proxy

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

    def _bucket_url_and_host(self, query: str) -> tuple[str, str, str]:
        """桶级请求（列表等）的 URL、host 与 canonical URI。"""
        parsed = urlparse(self.endpoint_url)
        host = parsed.netloc
        path_prefix = parsed.path.rstrip("/")
        base_path = f"{path_prefix}/{self.bucket}" if path_prefix else f"/{self.bucket}"
        target_url = f"{self.endpoint_url}/{self.bucket}?{query}"
        return target_url, host, base_path

    def _sign_request(
        self,
        *,
        method: str,
        canonical_uri: str,
        canonical_query: str,
        host: str,
        payload_hash: str,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """生成 SigV4 请求头（含 Authorization）。

        所有参与签名的头按小写名字排序后进入 canonical request；
        返回的头字典可直接交给 httpx。
        """
        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")

        signed: Dict[str, str] = {
            "host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if extra_headers:
            signed.update({str(k).lower(): str(v) for k, v in extra_headers.items()})
        names = sorted(signed)
        canonical_headers = "".join(f"{name}:{signed[name]}\n" for name in names)
        signed_headers = ";".join(names)

        canonical_request = (
            f"{method}\n"
            f"{canonical_uri}\n"
            f"{canonical_query}\n"
            f"{canonical_headers}\n"
            f"{signed_headers}\n"
            f"{payload_hash}"
        )

        credential_scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        string_to_sign = (
            f"AWS4-HMAC-SHA256\n"
            f"{amz_date}\n"
            f"{credential_scope}\n"
            f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
        )

        signing_key = _get_signature_key(self.secret_key, date_stamp, self.region, "s3")
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        headers = dict(signed)
        headers["Authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        # httpx 自行设置 Host，显式传入会与 URL 主机不一致时被拒
        headers.pop("host", None)
        return headers

    def _proxy_url(self) -> Optional[str]:
        if not self.proxy:
            return None
        from backend.utils.proxy import format_proxy_url

        return format_proxy_url(self.proxy)

    def object_key(self, object_name: str) -> str:
        return f"{self.prefix}{object_name}"

    async def upload_file(self, file_path: Path, object_name: Optional[str] = None) -> Dict[str, Any]:
        """上传本地文件到 S3 存储桶。"""
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        key = self.object_key(object_name or file_path.name)
        target_url, host, canonical_uri = self._build_url_and_host(key)

        with open(file_path, "rb") as f:
            data = f.read()

        payload_hash = hashlib.sha256(data).hexdigest()
        headers = self._sign_request(
            method="PUT",
            canonical_uri=canonical_uri,
            canonical_query="",
            host=host,
            payload_hash=payload_hash,
            extra_headers={"content-type": self._content_type(file_path.name)},
        )
        headers["Content-Type"] = self._content_type(file_path.name)
        headers["Content-Length"] = str(len(data))

        async with httpx.AsyncClient(proxy=self._proxy_url(), timeout=60.0) as client:
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

    @staticmethod
    def _content_type(name: str) -> str:
        return "application/gzip" if name.endswith(".gz") else "application/octet-stream"

    async def list_objects(
        self,
        *,
        name_suffix: str = ".tar.gz",
        limit: int = 100,
        timeout: float = 60.0,
    ) -> List[Dict[str, Any]]:
        """列出 prefix 下的对象，按 LastModified 倒序返回。"""
        query = f"list-type=2&prefix={quote(self.prefix, safe='')}"
        target_url, host, canonical_uri = self._bucket_url_and_host(query)
        headers = self._sign_request(
            method="GET",
            canonical_uri=canonical_uri,
            canonical_query=query,
            host=host,
            payload_hash=EMPTY_SHA256,
        )
        async with httpx.AsyncClient(proxy=self._proxy_url(), timeout=timeout) as client:
            resp = await client.get(target_url, headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(f"S3 列表失败 (HTTP {resp.status_code}): {resp.text[:300]}")
        return _parse_list_objects(resp.text, suffix=name_suffix, limit=limit)

    async def get_object(
        self, object_name: str, *, timeout: float = 60.0
    ) -> bytes:
        """下载对象内容（仅备份包等小文件使用，调用方需自行限制大小）。"""
        key = self.object_key(object_name)
        target_url, host, canonical_uri = self._build_url_and_host(key)
        headers = self._sign_request(
            method="GET",
            canonical_uri=canonical_uri,
            canonical_query="",
            host=host,
            payload_hash=EMPTY_SHA256,
        )
        async with httpx.AsyncClient(proxy=self._proxy_url(), timeout=timeout) as client:
            resp = await client.get(target_url, headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(f"S3 下载失败 (HTTP {resp.status_code}): {resp.text[:300]}")
        return resp.content

    async def iter_object(
        self,
        object_name: str,
        *,
        chunk_size: int = 64 * 1024,
        timeout: float = 60.0,
    ) -> AsyncIterator[bytes]:
        """以分块方式下载对象，避免将整个备份包读入进程内存。"""
        key = self.object_key(object_name)
        target_url, host, canonical_uri = self._build_url_and_host(key)
        headers = self._sign_request(
            method="GET",
            canonical_uri=canonical_uri,
            canonical_query="",
            host=host,
            payload_hash=EMPTY_SHA256,
        )
        async with httpx.AsyncClient(proxy=self._proxy_url(), timeout=timeout) as client:
            async with client.stream("GET", target_url, headers=headers) as resp:
                if resp.status_code != 200:
                    detail = (await resp.aread()).decode("utf-8", errors="replace")[:300]
                    raise RuntimeError(f"S3 下载失败 (HTTP {resp.status_code}): {detail}")
                async for chunk in resp.aiter_bytes(chunk_size=chunk_size):
                    if chunk:
                        yield chunk

    async def delete_object(
        self, object_name: str, *, timeout: float = 60.0
    ) -> None:
        key = self.object_key(object_name)
        target_url, host, canonical_uri = self._build_url_and_host(key)
        headers = self._sign_request(
            method="DELETE",
            canonical_uri=canonical_uri,
            canonical_query="",
            host=host,
            payload_hash=EMPTY_SHA256,
        )
        async with httpx.AsyncClient(proxy=self._proxy_url(), timeout=timeout) as client:
            resp = await client.delete(target_url, headers=headers)
        if resp.status_code not in (200, 204):
            raise RuntimeError(f"S3 删除失败 (HTTP {resp.status_code}): {resp.text[:300]}")

    async def check_connection(self, *, timeout: float = 15.0) -> Dict[str, Any]:
        """列出 prefix 探测连通性与凭据有效性。"""
        await self.list_objects(limit=1, timeout=timeout)
        return {
            "success": True,
            "message": "对象存储连接成功",
            "status_code": 200,
        }


def _parse_list_objects(
    xml_text: str, *, suffix: str, limit: int
) -> List[Dict[str, Any]]:
    """解析 ListBucketResult（v2）XML 为备份文件列表，按 LastModified 倒序。"""
    entries: List[Dict[str, Any]] = []
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise RuntimeError(f"S3 列表响应解析失败: {exc}") from exc

    for node in root.iter():
        if not node.tag.endswith("Contents"):
            continue
        fields: Dict[str, str] = {}
        for child in node:
            fields[child.tag.split("}")[-1]] = (child.text or "").strip()
        key = fields.get("Key") or ""
        if not key:
            continue
        name = key.rsplit("/", 1)[-1]
        if suffix and not name.endswith(suffix):
            continue
        try:
            size = int(fields.get("Size") or 0)
        except ValueError:
            size = 0
        entries.append(
            {
                "name": name,
                "key": key,
                "size_bytes": size,
                "mtime": fields.get("LastModified") or "",
            }
        )

    # LastModified 为 ISO8601 字符串，字典序即时间序
    entries.sort(key=lambda e: e.get("mtime") or "", reverse=True)
    return entries[: max(0, int(limit))]


def _client_from_cfg(cfg: Dict[str, Any]) -> S3BackupClient:
    """从全局设置构造客户端，必填项缺失时抛 ValueError。"""
    endpoint = str(cfg.get("s3_endpoint_url") or "").strip()
    bucket = str(cfg.get("s3_bucket") or "").strip()
    access_key = str(cfg.get("s3_access_key") or "").strip()
    secret_key = str(cfg.get("s3_secret_key") or "")
    validate_s3_settings(
        endpoint_url=endpoint,
        bucket=bucket,
        access_key=access_key,
        secret_key=secret_key,
    )
    return S3BackupClient(
        endpoint_url=endpoint,
        bucket=bucket,
        access_key=access_key,
        secret_key=secret_key,
        region=str(cfg.get("s3_region") or DEFAULT_REGION),
        prefix=str(cfg.get("s3_prefix") or DEFAULT_PREFIX),
        proxy=str(cfg.get("s3_proxy") or cfg.get("proxy") or "").strip() or None,
    )


def s3_enabled(cfg: Optional[dict]) -> bool:
    """对象存储是否已配置且启用（未启用时自动备份/导出走 WebDAV 或本地）。"""
    if not isinstance(cfg, dict):
        return False
    if not bool(cfg.get("s3_enabled")):
        return False
    try:
        validate_s3_settings(
            endpoint_url=str(cfg.get("s3_endpoint_url") or ""),
            bucket=str(cfg.get("s3_bucket") or ""),
            access_key=str(cfg.get("s3_access_key") or ""),
            secret_key=str(cfg.get("s3_secret_key") or ""),
        )
    except ValueError:
        return False
    return True


async def list_s3_files(
    cfg: Dict[str, Any], *, name_suffix: str = ".tar.gz", limit: int = 20
) -> Dict[str, Any]:
    """列出对象存储中的备份包（设置页远端列表）。"""
    try:
        client = _client_from_cfg(cfg)
    except ValueError as exc:
        return {"success": False, "files": [], "message": str(exc)}
    try:
        files = await client.list_objects(name_suffix=name_suffix, limit=limit)
    except Exception as exc:
        logger.warning("S3 列表失败: %s", exc)
        return {"success": False, "files": [], "message": f"列表失败: {exc}"}
    return {"success": True, "files": files, "message": ""}


async def download_s3_file(cfg: Dict[str, Any], filename: str) -> bytes:
    """下载指定备份包内容。"""
    from backend.services.webdav_client import validate_backup_filename

    safe_name = validate_backup_filename(filename)
    client = _client_from_cfg(cfg)
    return await client.get_object(safe_name)


async def stream_s3_file(
    cfg: Dict[str, Any],
    filename: str,
    *,
    chunk_size: int = 64 * 1024,
) -> AsyncIterator[bytes]:
    """校验文件名后返回对象存储的分块下载迭代器。"""
    from backend.services.webdav_client import validate_backup_filename

    safe_name = validate_backup_filename(filename)
    client = _client_from_cfg(cfg)
    return client.iter_object(safe_name, chunk_size=chunk_size)


async def prune_s3_backups(
    cfg: Dict[str, Any], *, keep: int = 3, name_suffix: str = ".tar.gz"
) -> Dict[str, Any]:
    """保留最近 keep 份备份，删除更旧的（与 WebDAV 轮转口径一致）。"""
    keep = max(0, int(keep))
    client = _client_from_cfg(cfg)
    try:
        files = await client.list_objects(name_suffix=name_suffix, limit=100)
    except Exception as exc:
        logger.warning("S3 清理前列表失败: %s", exc)
        return {"success": False, "removed": 0, "kept": 0, "error": str(exc)}
    to_delete = files[keep:] if keep > 0 else files
    removed = 0
    errors: List[str] = []
    for item in to_delete:
        name = str(item.get("name") or "")
        if not name:
            continue
        try:
            await client.delete_object(name)
            removed += 1
        except Exception as exc:
            logger.warning("S3 远端备份删除失败 %s: %s", name, exc)
            errors.append(f"{name}: {exc}")
    return {
        "success": not errors,
        "removed": removed,
        "kept": min(keep, len(files)),
        "errors": errors,
    }


async def check_s3_connection(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """探测对象存储连通性，失败时返回可展示的 message 而不抛出。"""
    try:
        client = _client_from_cfg(cfg)
        return await client.check_connection()
    except ValueError as exc:
        return {"success": False, "message": str(exc)}
    except Exception as exc:
        logger.warning("S3 连接测试失败: %s", exc)
        return {"success": False, "message": f"测试失败: {exc}"}


async def upload_backup_to_s3(cfg: Dict[str, Any], local_path: Path) -> Dict[str, Any]:
    """上传自动备份归档到对象存储。"""
    client = _client_from_cfg(cfg)
    return await client.upload_file(local_path)

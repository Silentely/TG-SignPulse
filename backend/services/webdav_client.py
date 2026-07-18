"""WebDAV 上传客户端（完整备份导出）。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urljoin, urlparse

import httpx

logger = logging.getLogger("backend.webdav")


def _join_url(base: str, *parts: str) -> str:
    """拼接 WebDAV URL，保留 base 中已有路径。"""
    base = (base or "").strip().rstrip("/") + "/"
    segs = []
    for p in parts:
        s = str(p or "").strip().strip("/")
        if s:
            segs.append(s)
    if not segs:
        return base.rstrip("/")
    # 对路径段编码但保留斜杠
    encoded = "/".join(quote(seg, safe="") for seg in segs)
    return urljoin(base, encoded)


def validate_webdav_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        raise ValueError("WebDAV URL 不能为空")
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("WebDAV URL 须为 http 或 https")
    if not parsed.netloc:
        raise ValueError("WebDAV URL 无效")
    return raw.rstrip("/")


def upload_file_to_webdav(
    *,
    base_url: str,
    username: str,
    password: str,
    remote_dir: str,
    local_path: Path,
    filename: Optional[str] = None,
    timeout: float = 120.0,
) -> dict:
    """
    将本地文件 PUT 到 WebDAV。

    base_url: 服务器根，如 https://cloud.example.com/remote.php/dav/files/user
    remote_dir: 远端目录相对路径，如 backups/tg-signpulse
    """
    base = validate_webdav_url(base_url)
    user = (username or "").strip()
    if not user:
        raise ValueError("WebDAV 用户名不能为空")
    if not local_path.is_file():
        raise ValueError(f"本地文件不存在: {local_path}")

    name = filename or local_path.name
    dir_rel = (remote_dir or "").strip().strip("/")
    auth = (user, password or "")

    file_url = _join_url(base, dir_rel, name) if dir_rel else _join_url(base, name)
    dir_url = _join_url(base, dir_rel) if dir_rel else base

    with httpx.Client(timeout=timeout, auth=auth, follow_redirects=True) as client:
        # 尝试创建远端目录（已存在时多数服务返回 405/409/301）
        if dir_rel:
            mk = client.request("MKCOL", dir_url)
            if mk.status_code not in (201, 200, 405, 409, 301, 302):
                logger.debug("MKCOL %s -> %s %s", dir_url, mk.status_code, mk.text[:200])

        data = local_path.read_bytes()
        put = client.put(
            file_url,
            content=data,
            headers={"Content-Type": "application/gzip"},
        )
        if put.status_code not in (200, 201, 204):
            detail = (put.text or "")[:300]
            raise RuntimeError(
                f"WebDAV 上传失败 HTTP {put.status_code}: {detail or put.reason_phrase}"
            )

    return {
        "success": True,
        "remote_url": file_url,
        "filename": name,
        "size_bytes": local_path.stat().st_size,
    }


def test_webdav_connection(
    *,
    base_url: str,
    username: str,
    password: str,
    remote_dir: str = "",
    timeout: float = 15.0,
) -> dict:
    """用 PROPFIND/HEAD 探测 WebDAV 是否可访问。"""
    base = validate_webdav_url(base_url)
    user = (username or "").strip()
    if not user:
        raise ValueError("WebDAV 用户名不能为空")
    dir_rel = (remote_dir or "").strip().strip("/")
    target = _join_url(base, dir_rel) if dir_rel else base
    auth = (user, password or "")

    with httpx.Client(timeout=timeout, auth=auth, follow_redirects=True) as client:
        # 优先 PROPFIND Depth:0
        resp = client.request(
            "PROPFIND",
            target,
            headers={"Depth": "0"},
            content=b'<?xml version="1.0"?><propfind xmlns="DAV:"><prop><resourcetype/></prop></propfind>',
        )
        if resp.status_code in (207, 200, 404, 405):
            # 404 可能是目录不存在但仍可建；405 表示方法不支持，再试 HEAD
            if resp.status_code in (207, 200):
                return {"success": True, "message": "WebDAV 连接成功", "status_code": resp.status_code}
            head = client.head(base)
            if head.status_code < 400 or head.status_code in (401, 403):
                # 401 表示服务在但凭据可能不对
                if head.status_code in (401, 403):
                    return {
                        "success": False,
                        "message": f"认证失败 HTTP {head.status_code}",
                        "status_code": head.status_code,
                    }
                return {
                    "success": True,
                    "message": "WebDAV 服务可达（目录可能需首次上传时创建）",
                    "status_code": head.status_code,
                }
            return {
                "success": False,
                "message": f"探测失败 HTTP {resp.status_code}",
                "status_code": resp.status_code,
            }
        if resp.status_code in (401, 403):
            return {
                "success": False,
                "message": f"认证失败 HTTP {resp.status_code}",
                "status_code": resp.status_code,
            }
        return {
            "success": False,
            "message": f"探测失败 HTTP {resp.status_code}",
            "status_code": resp.status_code,
        }

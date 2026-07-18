"""WebDAV 上传客户端（完整备份导出）。"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, List, Optional, Union
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx

logger = logging.getLogger("backend.webdav")

# 备份包可能较大：连接短超时，读写长超时
_DEFAULT_UPLOAD_TIMEOUT = httpx.Timeout(30.0, read=600.0, write=600.0, pool=30.0)
_MKCOL_OK = frozenset({201, 200, 405, 409, 301, 302})
_DAV_NS = {"d": "DAV:"}
_PROPFIND_PROP = (
    b'<?xml version="1.0" encoding="utf-8"?>'
    b'<d:propfind xmlns:d="DAV:">'
    b"<d:prop><d:displayname/><d:getcontentlength/><d:getlastmodified/>"
    b"<d:resourcetype/></d:prop></d:propfind>"
)


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


def _ensure_remote_dirs(client: httpx.Client, base: str, dir_rel: str) -> None:
    """逐级 MKCOL 创建远端目录（兼容 Nextcloud 等多级路径）。"""
    segs = [s for s in (dir_rel or "").split("/") if s]
    if not segs:
        return
    acc: list[str] = []
    for seg in segs:
        acc.append(seg)
        dir_url = _join_url(base, *acc)
        mk = client.request("MKCOL", dir_url)
        if mk.status_code not in _MKCOL_OK:
            logger.debug(
                "MKCOL %s -> %s %s",
                dir_url,
                mk.status_code,
                (mk.text or "")[:200],
            )


def upload_file_to_webdav(
    *,
    base_url: str,
    username: str,
    password: str,
    remote_dir: str,
    local_path: Path,
    filename: Optional[str] = None,
    timeout: Optional[Union[float, httpx.Timeout]] = None,
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
    req_timeout = timeout if timeout is not None else _DEFAULT_UPLOAD_TIMEOUT

    with httpx.Client(timeout=req_timeout, auth=auth, follow_redirects=True) as client:
        # 多级目录逐段创建（已存在时多数服务返回 405/409/301）
        if dir_rel:
            _ensure_remote_dirs(client, base, dir_rel)

        # 流式上传，避免大备份包整包读入内存
        with local_path.open("rb") as fh:
            put = client.put(
                file_url,
                content=fh,
                headers={
                    "Content-Type": "application/gzip",
                    "Content-Length": str(local_path.stat().st_size),
                },
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


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _parse_propfind_entries(xml_text: str, base_url: str) -> List[dict]:
    """解析 PROPFIND multistatus，返回文件条目（跳过集合目录自身）。"""
    entries: List[dict] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(f"WebDAV 列表响应无法解析: {exc}") from exc

    base_path = urlparse(base_url.rstrip("/") + "/").path.rstrip("/")

    for resp_el in root.iter():
        if _local_name(resp_el.tag) != "response":
            continue
        href = ""
        size: Optional[int] = None
        mtime = ""
        is_collection = False
        displayname = ""
        for child in resp_el.iter():
            ln = _local_name(child.tag)
            if ln == "href" and child.text and not href:
                href = child.text.strip()
            elif ln == "getcontentlength" and child.text:
                try:
                    size = int(child.text.strip())
                except ValueError:
                    size = None
            elif ln == "getlastmodified" and child.text:
                mtime = child.text.strip()
            elif ln == "displayname" and child.text:
                displayname = child.text.strip()
            elif ln == "collection":
                is_collection = True
        if not href or is_collection:
            continue
        # 解析文件名
        path = urlparse(href).path if "://" in href else href
        path = unquote(path.rstrip("/"))
        name = path.rsplit("/", 1)[-1] if path else ""
        if not name:
            name = displayname
        if not name:
            continue
        # 跳过目录本身（href 恰好等于目标目录）
        if path.rstrip("/") == base_path:
            continue
        entries.append(
            {
                "name": name,
                "href": href,
                "size_bytes": size,
                "mtime": mtime or None,
            }
        )
    return entries


def list_webdav_files(
    *,
    base_url: str,
    username: str,
    password: str,
    remote_dir: str = "",
    name_suffix: str = ".tar.gz",
    limit: int = 20,
    timeout: float = 30.0,
) -> dict:
    """
    PROPFIND Depth:1 列出远端目录中的备份文件。

    返回 {success, files: [{name, href, size_bytes, mtime}], message?}
    """
    base = validate_webdav_url(base_url)
    user = (username or "").strip()
    if not user:
        raise ValueError("WebDAV 用户名不能为空")
    dir_rel = (remote_dir or "").strip().strip("/")
    target = _join_url(base, dir_rel) if dir_rel else base
    auth = (user, password or "")
    limit = max(1, min(int(limit), 100))

    with httpx.Client(timeout=timeout, auth=auth, follow_redirects=True) as client:
        resp = client.request(
            "PROPFIND",
            target,
            headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
            content=_PROPFIND_PROP,
        )
        if resp.status_code in (401, 403):
            return {
                "success": False,
                "files": [],
                "message": f"认证失败 HTTP {resp.status_code}",
                "status_code": resp.status_code,
            }
        if resp.status_code == 404:
            return {
                "success": True,
                "files": [],
                "message": "远端目录不存在（尚未上传过备份）",
                "status_code": 404,
            }
        if resp.status_code not in (207, 200):
            detail = (resp.text or "")[:200]
            return {
                "success": False,
                "files": [],
                "message": f"列出失败 HTTP {resp.status_code}: {detail}",
                "status_code": resp.status_code,
            }

        entries = _parse_propfind_entries(resp.text or "", target)
        suffix = (name_suffix or "").lower()
        if suffix:
            entries = [
                e
                for e in entries
                if str(e.get("name") or "").lower().endswith(suffix)
            ]
        # 按 mtime 字符串倒序（HTTP-date 可字典序近似）；无 mtime 则按名
        entries.sort(
            key=lambda e: (e.get("mtime") or "", e.get("name") or ""),
            reverse=True,
        )
        files: List[dict[str, Any]] = entries[:limit]
        return {
            "success": True,
            "files": files,
            "message": f"共 {len(files)} 个文件" if files else "目录为空",
            "status_code": resp.status_code,
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
            content=_PROPFIND_PROP,
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

"""WebDAV 上传客户端（完整备份导出）。"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterator, List, Optional, Union
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx

logger = logging.getLogger("backend.webdav")

# 备份包可能较大：连接短超时，读写长超时
_DEFAULT_UPLOAD_TIMEOUT = httpx.Timeout(30.0, read=600.0, write=600.0, pool=30.0)
_MKCOL_OK = frozenset({201, 200, 405, 409, 301, 302})
_DELETE_OK = frozenset({200, 204, 404})  # 404 视为已删除
_DAV_NS = {"d": "DAV:"}
_PROPFIND_PROP = (
    b'<?xml version="1.0" encoding="utf-8"?>'
    b'<d:propfind xmlns:d="DAV:">'
    b"<d:prop><d:displayname/><d:getcontentlength/><d:getlastmodified/>"
    b"<d:resourcetype/></d:prop></d:propfind>"
)
# 仅允许安全备份文件名，防止路径穿越
_SAFE_BACKUP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}\.tar\.gz$")


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


def validate_backup_filename(name: str) -> str:
    """校验远端备份文件名（仅 basename + .tar.gz）。"""
    raw = (name or "").strip()
    if not raw or "/" in raw or "\\" in raw or ".." in raw:
        raise ValueError("非法备份文件名")
    base = Path(raw).name
    if base != raw or not _SAFE_BACKUP_NAME.match(base):
        raise ValueError("备份文件名须为安全的 .tar.gz 名称")
    return base


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
        # 优先解析 HTTP-date；失败则回退文件名中的时间戳片段
        entries.sort(key=_backup_sort_key, reverse=True)
        files: List[dict[str, Any]] = entries[:limit]
        return {
            "success": True,
            "files": files,
            "message": f"共 {len(files)} 个文件" if files else "目录为空",
            "status_code": resp.status_code,
            "total_matched": len(entries),
        }


def _parse_mtime_key(mtime: Optional[str], name: str) -> tuple:
    """生成排序键：(epoch, name)，越大越新。"""
    epoch = 0.0
    raw = (mtime or "").strip()
    if raw:
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            epoch = dt.timestamp()
        except (TypeError, ValueError, IndexError, OverflowError):
            epoch = 0.0
    if epoch <= 0:
        # auto-YYYYMMDD-HHMMSS / tg-signpulse-backup-YYYYMMDD-HHMMSS
        m = re.search(r"(20\d{6})-(\d{6})", name or "")
        if m:
            try:
                dt = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
                epoch = dt.replace(tzinfo=timezone.utc).timestamp()
            except ValueError:
                epoch = 0.0
    return (epoch, name or "")


def _backup_sort_key(entry: dict) -> tuple:
    return _parse_mtime_key(entry.get("mtime"), str(entry.get("name") or ""))


def delete_webdav_file(
    *,
    base_url: str,
    username: str,
    password: str,
    remote_dir: str,
    filename: str,
    timeout: float = 30.0,
) -> dict:
    """删除远端备份文件（按目录 + 安全文件名构造 URL）。"""
    base = validate_webdav_url(base_url)
    user = (username or "").strip()
    if not user:
        raise ValueError("WebDAV 用户名不能为空")
    name = validate_backup_filename(filename)
    dir_rel = (remote_dir or "").strip().strip("/")
    file_url = _join_url(base, dir_rel, name) if dir_rel else _join_url(base, name)
    auth = (user, password or "")

    with httpx.Client(timeout=timeout, auth=auth, follow_redirects=True) as client:
        resp = client.delete(file_url)
        if resp.status_code not in _DELETE_OK:
            detail = (resp.text or "")[:200]
            raise RuntimeError(
                f"WebDAV 删除失败 HTTP {resp.status_code}: {detail or resp.reason_phrase}"
            )
    return {"success": True, "filename": name, "status_code": resp.status_code}


def _webdav_file_url(
    base_url: str, remote_dir: str, filename: str
) -> tuple[str, str, str]:
    """返回 (base, safe_name, file_url)。"""
    base = validate_webdav_url(base_url)
    name = validate_backup_filename(filename)
    dir_rel = (remote_dir or "").strip().strip("/")
    file_url = _join_url(base, dir_rel, name) if dir_rel else _join_url(base, name)
    return base, name, file_url


def download_webdav_file(
    *,
    base_url: str,
    username: str,
    password: str,
    remote_dir: str,
    filename: str,
    dest_path: Path,
    timeout: Optional[Union[float, httpx.Timeout]] = None,
) -> Path:
    """从 WebDAV 流式下载备份到本地 dest_path。"""
    user = (username or "").strip()
    if not user:
        raise ValueError("WebDAV 用户名不能为空")
    _, name, file_url = _webdav_file_url(base_url, remote_dir, filename)
    auth = (user, password or "")
    req_timeout = timeout if timeout is not None else _DEFAULT_UPLOAD_TIMEOUT
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=req_timeout, auth=auth, follow_redirects=True) as client:
        with client.stream("GET", file_url) as resp:
            if resp.status_code != 200:
                detail = ""
                try:
                    detail = (resp.read() or b"")[:200].decode("utf-8", errors="replace")
                except Exception:
                    detail = resp.reason_phrase or ""
                raise RuntimeError(
                    f"WebDAV 下载失败 HTTP {resp.status_code}: {detail}"
                )
            with dest_path.open("wb") as fh:
                for chunk in resp.iter_bytes():
                    if chunk:
                        fh.write(chunk)
    if not dest_path.is_file() or dest_path.stat().st_size == 0:
        try:
            dest_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError("WebDAV 下载结果为空")
    return dest_path


def iter_webdav_file(
    *,
    base_url: str,
    username: str,
    password: str,
    remote_dir: str,
    filename: str,
    timeout: Optional[Union[float, httpx.Timeout]] = None,
    chunk_size: int = 64 * 1024,
) -> Iterator[bytes]:
    """
    流式读取远端备份内容（不落本地临时整包）。

    调用方必须完整消费迭代器，以便关闭 HTTP 连接。
    """
    user = (username or "").strip()
    if not user:
        raise ValueError("WebDAV 用户名不能为空")
    _, _name, file_url = _webdav_file_url(base_url, remote_dir, filename)
    auth = (user, password or "")
    req_timeout = timeout if timeout is not None else _DEFAULT_UPLOAD_TIMEOUT

    client = httpx.Client(timeout=req_timeout, auth=auth, follow_redirects=True)
    try:
        with client.stream("GET", file_url) as resp:
            if resp.status_code != 200:
                detail = ""
                try:
                    detail = (resp.read() or b"")[:200].decode(
                        "utf-8", errors="replace"
                    )
                except Exception:
                    detail = resp.reason_phrase or ""
                raise RuntimeError(
                    f"WebDAV 下载失败 HTTP {resp.status_code}: {detail}"
                )
            got_any = False
            for chunk in resp.iter_bytes(chunk_size=chunk_size):
                if chunk:
                    got_any = True
                    yield chunk
            if not got_any:
                raise RuntimeError("WebDAV 下载结果为空")
    finally:
        client.close()


def prune_webdav_backups(
    *,
    base_url: str,
    username: str,
    password: str,
    remote_dir: str,
    keep: int = 3,
    name_suffix: str = ".tar.gz",
    timeout: float = 60.0,
) -> dict:
    """保留远端最近 keep 份备份，删除更旧的 .tar.gz。"""
    keep = max(0, int(keep))
    listed = list_webdav_files(
        base_url=base_url,
        username=username,
        password=password,
        remote_dir=remote_dir,
        name_suffix=name_suffix,
        limit=100,
        timeout=timeout,
    )
    if not listed.get("success"):
        return {
            "success": False,
            "removed": 0,
            "kept": 0,
            "error": listed.get("message") or "list failed",
        }
    files = list(listed.get("files") or [])
    # list 已按 mtime 倒序；仅保留前 keep
    to_keep = files[:keep] if keep > 0 else []
    to_delete = files[keep:] if keep > 0 else files
    removed = 0
    errors: List[str] = []
    for item in to_delete:
        name = str(item.get("name") or "")
        try:
            delete_webdav_file(
                base_url=base_url,
                username=username,
                password=password,
                remote_dir=remote_dir,
                filename=name,
                timeout=timeout,
            )
            removed += 1
        except Exception as exc:
            logger.warning("远端备份删除失败 %s: %s", name, exc)
            errors.append(f"{name}: {exc}")
    return {
        "success": len(errors) == 0,
        "removed": removed,
        "kept": len(to_keep),
        "errors": errors,
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

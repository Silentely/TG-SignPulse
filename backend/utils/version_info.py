"""应用版本解析与可选远程更新检查。

版本真相源：
1. 环境变量 APP_VERSION（镜像/CI 注入）
2. 回退 tg_signer.__version__

构建元数据：GIT_SHA / GIT_BRANCH / BUILD_TIME（可选）
远程检查：可关，失败 soft-fail。

默认不走 api.github.com（未认证仅约 60 次/小时，自部署用户易踩限流）：
1. 优先 github.com/.../releases/latest 的 302 Location 解析 tag（零配置）
2. 仅当 HTML 失败，或自定义 URL 是非 GitHub 的 JSON 源时，再请求 JSON/API
3. 可选 APP_GITHUB_TOKEN 仅用于仍走 API 的场景；不要求用户配置
4. 失败时若仍有成功缓存则返回过期缓存（stale）
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import httpx

from backend.utils.time import utc_now_iso

logger = logging.getLogger("backend.version_info")

DEFAULT_UPDATE_CHECK_URL = (
    "https://api.github.com/repos/Silentely/TG-SignPulse/releases/latest"
)
DEFAULT_GITHUB_HTML_LATEST = (
    "https://github.com/Silentely/TG-SignPulse/releases/latest"
)
UPDATE_CACHE_TTL_SECONDS = 6 * 3600
_HTTP_TIMEOUT_SECONDS = 8.0
# Docker 未注入真实版本时的占位，不应覆盖包版本
_PLACEHOLDER_VERSIONS = frozenset({"0.0.0", "0.0.0-dev"})
# api.github.com/repos/{owner}/{repo}/releases/latest
_GITHUB_API_RELEASES_RE = re.compile(
    r"^https://api\.github\.com/repos/([^/]+)/([^/]+)/releases/latest/?$",
    re.IGNORECASE,
)
_RATE_LIMIT_HINT = "检查更新暂时失败，请稍后再试。"

_cache_lock = threading.Lock()
_cache: Dict[str, Any] = {
    "expires_at": 0.0,
    "payload": None,
}


def clear_update_check_cache() -> None:
    """清空远程检查缓存（测试与运维排障用）。"""
    with _cache_lock:
        _cache["expires_at"] = 0.0
        _cache["payload"] = None


def normalize_version(raw: str) -> str:
    """去掉空白与可选 v/V 前缀，返回规范化版本字符串。"""
    s = (raw or "").strip()
    if len(s) >= 2 and (s[0] == "v" or s[0] == "V") and s[1].isdigit():
        s = s[1:]
    return s


def parse_semver(raw: str) -> Tuple[int, int, int]:
    """解析 major.minor.patch；忽略 -prerelease 与 +build；无法解析的段视为 0。"""
    s = normalize_version(raw)
    if not s:
        return (0, 0, 0)
    # 去掉 build metadata 与 prerelease
    s = s.split("+", 1)[0]
    s = s.split("-", 1)[0]
    parts: list[int] = []
    for piece in s.split("."):
        digits = ""
        for ch in piece:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits:
            try:
                parts.append(int(digits))
            except ValueError:
                parts.append(0)
        else:
            parts.append(0)
        if len(parts) >= 3:
            break
    while len(parts) < 3:
        parts.append(0)
    return (parts[0], parts[1], parts[2])


def is_update_available(current: str, latest: str) -> bool:
    """当 latest 严格大于 current 时返回 True。任一为空则 False。"""
    cur = normalize_version(current)
    lat = normalize_version(latest)
    if not cur or not lat:
        return False
    return parse_semver(lat) > parse_semver(cur)


def is_update_check_enabled() -> bool:
    raw = (os.environ.get("APP_UPDATE_CHECK") or "1").strip().lower()
    if raw in {"0", "false", "off", "no", "disabled"}:
        return False
    return True


def _read_env(*names: str, default: str = "") -> str:
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return default


def resolve_app_version(package_version: str, env_version: str = "") -> str:
    """解析展示/比较用版本：空或占位 APP_VERSION 回退到包版本。"""
    raw = (env_version or "").strip()
    if not raw:
        return str(package_version)
    normalized = normalize_version(raw)
    if not normalized or normalized in _PLACEHOLDER_VERSIONS:
        return str(package_version)
    return normalized


def validate_update_check_url(url: str) -> str:
    """仅允许 https 远程检查地址，降低 SSRF/误配风险。"""
    raw = (url or "").strip()
    if not raw:
        raise ValueError("update check URL is empty")
    parsed = urlparse(raw)
    if parsed.scheme != "https":
        raise ValueError("update check URL must use https")
    if not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("update check URL host is invalid")
    return raw


def get_local_version_info() -> Dict[str, Any]:
    """收集本进程版本与构建信息（无网络）。"""
    from tg_signer import __version__ as package_version

    version = resolve_app_version(
        str(package_version),
        _read_env("APP_VERSION", default=""),
    )
    git_sha = _read_env("GIT_SHA", default="")
    git_branch = _read_env("GIT_BRANCH", default="")
    build_time = _read_env("BUILD_TIME", "APP_BUILD_TIME", default="")

    try:
        from backend.core.config import get_settings

        app_name = get_settings().app_name
    except Exception:
        app_name = _read_env("APP_APP_NAME", "APP_NAME", default="tg-signer-panel")

    return {
        "version": version,
        "git_sha": git_sha,
        "git_branch": git_branch,
        "build_time": build_time,
        "app_name": app_name,
        "python": sys.version.split()[0],
        "update_check_enabled": is_update_check_enabled(),
    }


def _empty_update_payload(
    *,
    enabled: bool,
    error: Optional[str] = None,
    cached: bool = False,
) -> Dict[str, Any]:
    return {
        "enabled": enabled,
        "latest_version": None,
        "latest_url": None,
        "update_available": False,
        "checked_at": utc_now_iso(),
        "error": error,
        "source": "github_releases",
        "cached": cached,
    }


def _safe_release_page_url(raw: Optional[str]) -> Optional[str]:
    """仅保留 http(s) 发布页链接，避免异常协议进入 API 响应。"""
    if not raw:
        return None
    try:
        parsed = urlparse(str(raw).strip())
    except Exception:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return str(raw).strip()


def _github_token() -> str:
    """可选：仅当仍请求 GitHub API 时附加；自部署用户无需配置。"""
    return _read_env("APP_GITHUB_TOKEN", "GITHUB_TOKEN", default="")


def _request_headers(*, accept: str = "application/vnd.github+json") -> Dict[str, str]:
    headers = {
        "Accept": accept,
        # 固定 UA，避免部分站点对空/默认 UA 拦截
        "User-Agent": "TG-SignPulse-VersionCheck/1.0",
    }
    token = _github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _is_rate_limit_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    if "rate limit" in text or "ratelimit" in text:
        return True
    if "403" in text and ("api.github.com" in text or "github" in text):
        return True
    code = getattr(exc, "status", None) or getattr(getattr(exc, "response", None), "status_code", None)
    if code in {403, 429}:
        return True
    return False


def _friendly_error(exc: BaseException) -> str:
    """将 httpx/原始异常压成对用户友好的短文案（不提 Token）。"""
    if _is_rate_limit_error(exc):
        return _RATE_LIMIT_HINT
    if isinstance(exc, httpx.HTTPStatusError):
        return f"远程版本源返回 HTTP {exc.response.status_code}，请稍后重试"
    if isinstance(exc, httpx.TimeoutException):
        return "连接版本源超时，请检查网络后重试"
    if isinstance(exc, httpx.RequestError):
        return "无法连接版本源，请检查网络后重试"
    msg = str(exc).strip() or type(exc).__name__
    if "for url" in msg.lower() and len(msg) > 100:
        if "403" in msg or "rate limit" in msg.lower():
            return _RATE_LIMIT_HINT
        return msg[:100].rstrip() + "…"
    return msg[:300]


def _github_html_latest_url(api_or_custom_url: str) -> Optional[str]:
    """从 GitHub API latest URL 推导 HTML releases/latest（不计入 API 配额）。"""
    m = _GITHUB_API_RELEASES_RE.match((api_or_custom_url or "").strip())
    if not m:
        # 默认 API 源
        if (api_or_custom_url or "").strip() in {"", DEFAULT_UPDATE_CHECK_URL}:
            return DEFAULT_GITHUB_HTML_LATEST
        return None
    owner, repo = m.group(1), m.group(2)
    return f"https://github.com/{owner}/{repo}/releases/latest"


def _tag_from_release_location(location: str) -> Optional[str]:
    """从 Location / 最终 URL 提取 tag（…/releases/tag/vX.Y.Z）。"""
    raw = (location or "").strip()
    if not raw:
        return None
    try:
        path = urlparse(raw).path
    except Exception:
        return None
    marker = "/releases/tag/"
    idx = path.find(marker)
    if idx < 0:
        return None
    tag = path[idx + len(marker) :].strip("/")
    # 去掉可能的 query 残留（path 通常无 query）
    tag = tag.split("/")[0].strip()
    return tag or None


def _fetch_via_html_redirect(html_latest_url: str) -> Dict[str, Any]:
    """
    走 github.com/…/releases/latest 的 302 Location 解析 tag。
    默认主路径：不走 api.github.com，自部署零配置、不吃 API 配额。
    """
    safe_url = validate_update_check_url(html_latest_url)
    # HTML 站不需要 Authorization，避免误带 Token
    headers = {
        "Accept": "text/html,application/xhtml+xml",
        "User-Agent": "TG-SignPulse-VersionCheck/1.0",
    }
    # 不跟随跳转，只读 Location
    with httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS, follow_redirects=False) as client:
        resp = client.get(safe_url, headers=headers)
    # 部分环境可能直接 200 渲染；优先 Location
    location = resp.headers.get("location") or resp.headers.get("Location") or ""
    tag = _tag_from_release_location(location)
    final_url = location
    if not tag and resp.is_redirect:
        # 相对 Location
        try:
            final_url = str(resp.url.join(location)) if location else ""
        except Exception:
            final_url = location
        tag = _tag_from_release_location(final_url)
    if not tag and resp.status_code == 200:
        # 极少数 CDN 直出最终页：从最终 URL 取 tag
        tag = _tag_from_release_location(str(resp.url))
        final_url = str(resp.url)
    if not tag:
        # 再试一次跟随跳转，取最终 URL
        with httpx.Client(
            timeout=_HTTP_TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            resp2 = client.get(safe_url, headers=headers)
        tag = _tag_from_release_location(str(resp2.url))
        final_url = str(resp2.url)
        if not tag:
            raise ValueError(
                f"无法从 releases/latest 解析 tag（HTTP {resp.status_code}）"
            )
    html_url = _safe_release_page_url(final_url) or safe_url
    latest = normalize_version(tag)
    local = get_local_version_info()
    return {
        "enabled": True,
        "latest_version": latest,
        "latest_url": html_url,
        "update_available": is_update_available(local["version"], latest),
        "checked_at": utc_now_iso(),
        "error": None,
        "source": "github_releases_redirect",
        "cached": False,
    }


def _payload_from_release_json(
    data: Dict[str, Any], *, source: str = "github_releases"
) -> Dict[str, Any]:
    tag = str(data.get("tag_name") or data.get("name") or "").strip()
    if not tag:
        raise ValueError("release missing tag_name")
    html_url = _safe_release_page_url(data.get("html_url"))
    latest = normalize_version(tag)
    local = get_local_version_info()
    return {
        "enabled": True,
        "latest_version": latest,
        "latest_url": html_url,
        "update_available": is_update_available(local["version"], latest),
        "checked_at": utc_now_iso(),
        "error": None,
        "source": source,
        "cached": False,
    }


def _fetch_json_release(url: str) -> Dict[str, Any]:
    """请求 JSON 版本源（自定义镜像或 GitHub API 兜底）。"""
    safe_url = validate_update_check_url(url)
    headers = _request_headers()
    with httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS, follow_redirects=True) as client:
        resp = client.get(safe_url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    if not isinstance(data, dict):
        raise ValueError("release payload is not an object")
    source = (
        "github_releases"
        if "api.github.com" in safe_url
        else "custom_release_json"
    )
    return _payload_from_release_json(data, source=source)


def _fetch_latest_release(url: str) -> Dict[str, Any]:
    """
    解析最新版本。

    - 能映射到 GitHub HTML latest 时：优先重定向解析（零配置、不限流）
    - 否则或 HTML 失败：再请求 JSON（自定义源 / API 兜底）
    """
    safe_url = validate_update_check_url(url)
    html_url = _github_html_latest_url(safe_url)
    html_error: Optional[BaseException] = None

    if html_url:
        try:
            return _fetch_via_html_redirect(html_url)
        except Exception as exc:
            html_error = exc
            logger.info("HTML 版本检查失败，尝试 JSON/API 兜底: %s", exc)

    try:
        return _fetch_json_release(safe_url)
    except Exception as json_exc:
        if html_error is not None:
            logger.warning(
                "版本检查 HTML 与 JSON 均失败: html=%s json=%s",
                html_error,
                json_exc,
            )
            # 优先抛出更晚的 JSON 错误；若 JSON 是限流则用友好路径由上层处理
            raise json_exc from html_error
        raise


def _cached_success_payload(*, allow_stale: bool) -> Optional[Dict[str, Any]]:
    """读取成功缓存；allow_stale 时忽略 TTL（限流/网络失败兜底）。"""
    now = time.time()
    with _cache_lock:
        payload = _cache.get("payload")
        expires_at = float(_cache.get("expires_at") or 0.0)
        if (
            payload is None
            or payload.get("error")
            or not payload.get("latest_version")
        ):
            return None
        if not allow_stale and now >= expires_at:
            return None
        cached = dict(payload)
    local = get_local_version_info()
    cached["update_available"] = is_update_available(
        local["version"], str(cached.get("latest_version") or "")
    )
    cached["cached"] = True
    # 过期复用时附带轻量提示，方便前端区分
    if allow_stale and now >= expires_at:
        cached["error"] = None  # 成功数据优先展示，不报失败
        cached["source"] = str(cached.get("source") or "github_releases") + "_stale"
    return cached


def check_remote_update(*, force: bool = False) -> Dict[str, Any]:
    """检查远程最新版本；关闭时不联网；失败 soft-fail。

    仅缓存成功结果；失败不写缓存，避免短暂网络故障被锁 6 小时。
    force=true 时仍会在失败时复用过期成功缓存（stale），降低限流噪音。
    """
    if not is_update_check_enabled():
        return _empty_update_payload(enabled=False)

    if not force:
        hit = _cached_success_payload(allow_stale=False)
        if hit is not None:
            return hit

    url = _read_env("APP_UPDATE_CHECK_URL", default=DEFAULT_UPDATE_CHECK_URL)
    try:
        result = _fetch_latest_release(url)
    except Exception as exc:
        friendly = _friendly_error(exc)
        logger.warning("远程版本检查失败: %s", friendly)
        # 有成功历史时返回过期缓存，避免面板直接 403 文案
        stale = _cached_success_payload(allow_stale=True)
        if stale is not None:
            logger.info("版本检查失败，复用过期缓存 latest=%s", stale.get("latest_version"))
            return stale
        return _empty_update_payload(enabled=True, error=friendly)

    with _cache_lock:
        _cache["payload"] = dict(result)
        _cache["payload"]["cached"] = False
        _cache["expires_at"] = time.time() + UPDATE_CACHE_TTL_SECONDS

    return result

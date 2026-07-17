"""应用版本解析与可选远程更新检查。

版本真相源：
1. 环境变量 APP_VERSION（镜像/CI 注入）
2. 回退 tg_signer.__version__

构建元数据：GIT_SHA / GIT_BRANCH / BUILD_TIME（可选）
远程检查：GitHub Releases latest，可关，失败 soft-fail。
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("backend.version_info")

DEFAULT_UPDATE_CHECK_URL = (
    "https://api.github.com/repos/Silentely/TG-SignPulse/releases/latest"
)
UPDATE_CACHE_TTL_SECONDS = 6 * 3600
_HTTP_TIMEOUT_SECONDS = 8.0
# Docker 未注入真实版本时的占位，不应覆盖包版本
_PLACEHOLDER_VERSIONS = frozenset({"0.0.0", "0.0.0-dev"})

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
        "checked_at": datetime.now(timezone.utc).isoformat(),
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


def _fetch_latest_release(url: str) -> Dict[str, Any]:
    safe_url = validate_update_check_url(url)
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "TG-SignPulse-VersionCheck/1.0",
    }
    # 允许有限跳转（GitHub 可能 30x），超时限制外网耗时
    with httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS, follow_redirects=True) as client:
        resp = client.get(safe_url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    if not isinstance(data, dict):
        raise ValueError("release payload is not an object")
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
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "error": None,
        "source": "github_releases",
        "cached": False,
    }


def check_remote_update(*, force: bool = False) -> Dict[str, Any]:
    """检查远程最新版本；关闭时不联网；失败 soft-fail。

    仅缓存成功结果；失败不写缓存，避免短暂网络故障被锁 6 小时。
    """
    if not is_update_check_enabled():
        return _empty_update_payload(enabled=False)

    now = time.time()
    if not force:
        with _cache_lock:
            payload = _cache.get("payload")
            expires_at = float(_cache.get("expires_at") or 0.0)
            if (
                payload is not None
                and now < expires_at
                and not payload.get("error")
                and payload.get("latest_version")
            ):
                cached = dict(payload)
                # 缓存命中时按当前本地版本重算是否可更新
                local = get_local_version_info()
                cached["update_available"] = is_update_available(
                    local["version"], str(cached.get("latest_version") or "")
                )
                cached["cached"] = True
                return cached

    url = _read_env("APP_UPDATE_CHECK_URL", default=DEFAULT_UPDATE_CHECK_URL)
    try:
        result = _fetch_latest_release(url)
    except Exception as exc:
        logger.warning("远程版本检查失败: %s", exc)
        # 不缓存失败结果
        return _empty_update_payload(enabled=True, error=str(exc)[:300])

    with _cache_lock:
        _cache["payload"] = dict(result)
        _cache["payload"]["cached"] = False
        _cache["expires_at"] = time.time() + UPDATE_CACHE_TTL_SECONDS

    return result

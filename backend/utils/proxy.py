from __future__ import annotations

import asyncio
import ipaddress
import logging
import urllib.parse
import urllib.request
from enum import Enum
from typing import Optional
from urllib.parse import urlparse

import httpx

try:
    import socks
    from sockshandler import SocksiPyHandler
except ImportError:
    socks = None
    SocksiPyHandler = None

from backend.utils.cache import TTLCache

logger = logging.getLogger("backend.utils.proxy")

SUPPORTED_PROXY_SCHEMES = frozenset({"http", "https", "socks4", "socks5"})
DEFAULT_PROBE_ENDPOINTS = (
    "https://api64.ipify.org",
    "https://icanhazip.com",
)

# 代理探测缓存 (TTL = 600s)
_PROBE_CACHE: TTLCache[tuple[ProxyProbeStatus, Optional[str]]] = TTLCache(
    maxsize=256, ttl=600.0
)
# 宿主机直连出口 IP 缓存 (TTL = 600s)
_HOST_IP_CACHE: TTLCache[str] = TTLCache(maxsize=1, ttl=600.0)


class ProxyProbeStatus(str, Enum):
    OK = "OK"
    FAILED = "PROXY_PROBE_FAILED"         # 出口 IP 等于服务器宿主机 IP
    UNAVAILABLE = "PROXY_PROBE_UNAVAILABLE" # 探针端点无法访问/超时


def clear_proxy_probe_cache() -> None:
    """清空代理探测与宿主机 IP 缓存（供测试与重载使用）。"""
    _PROBE_CACHE.clear()
    _HOST_IP_CACHE.clear()


def normalize_proxy_url(raw: str) -> str:
    value = raw.strip()
    if not value:
        return value
    if "://" in value:
        return value
    if "@" in value:
        return f"socks5://{value}"
    parts = value.split(":")
    if len(parts) == 2:
        host, port = parts
        return f"socks5://{host}:{port}"
    if len(parts) == 4:
        host, port, user, password = parts
        return f"socks5://{user}:{password}@{host}:{port}"
    return f"socks5://{value}"


def build_proxy_dict(raw: str) -> Optional[dict]:
    value = normalize_proxy_url(raw)
    if not value:
        return None
    try:
        parsed = urlparse(value)
        port = parsed.port
    except (ValueError, AttributeError):
        return None
    scheme = (parsed.scheme or "").lower()
    if not (scheme in SUPPORTED_PROXY_SCHEMES and parsed.hostname and port):
        return None
    if not (1 <= port <= 65535):
        return None
    proxy = {
        "scheme": scheme,
        "hostname": parsed.hostname,
        "port": port,
    }
    if parsed.username:
        proxy["username"] = urllib.parse.unquote(parsed.username)
    if parsed.password:
        proxy["password"] = urllib.parse.unquote(parsed.password)
    return proxy



def _format_host_for_url(hostname: str) -> str:
    """若 hostname 为未加括号的 IPv6 地址，包裹为 [ipv6]，以兼容标准 URL 解析。"""
    if ":" in hostname and not (hostname.startswith("[") and hostname.endswith("]")):
        return f"[{hostname}]"
    return hostname

def format_proxy_url(raw: str | dict | None) -> Optional[str]:
    """将代理字符串或字典格式化为标准 URL（如 socks5://127.0.0.1:1080 或 http://user:pass@host:port）。"""
    if not raw:
        return None
    if isinstance(raw, str):
        proxy_dict = build_proxy_dict(raw)
    elif isinstance(raw, dict):
        proxy_dict = raw
    else:
        return None
    if not proxy_dict or not proxy_dict.get("hostname") or not proxy_dict.get("port"):
        return None
    scheme = str(proxy_dict.get("scheme", "http")).lower()
    host = _format_host_for_url(str(proxy_dict["hostname"]))
    user = proxy_dict.get("username")
    pwd = proxy_dict.get("password")
    if user:
        quoted_user = urllib.parse.quote(str(user), safe="")
        if pwd:
            quoted_pwd = urllib.parse.quote(str(pwd), safe="")
            auth = f"{quoted_user}:{quoted_pwd}@"
        else:
            auth = f"{quoted_user}@"
    else:
        auth = ""
    return f"{scheme}://{auth}{host}:{proxy_dict['port']}"


def _make_proxy_cache_key(proxy_dict: dict) -> str:
    scheme = str(proxy_dict.get("scheme", "")).lower()
    host = str(proxy_dict.get("hostname", "")).lower()
    port = str(proxy_dict.get("port", ""))
    user = str(proxy_dict.get("username") or "")
    pwd = str(proxy_dict.get("password") or "")
    return f"{scheme}://{user}:{pwd}@{host}:{port}"


async def _fetch_ip_direct(endpoint: str, timeout: float = 5.0) -> Optional[str]:
    """直连请求 IP 探测端点（禁止 trust_env）。"""
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=timeout) as client:
            resp = await client.get(endpoint, headers={"User-Agent": "TG-SignPulse-Probe/1.0"})
            resp.raise_for_status()
            text = resp.text.strip()
            ipaddress.ip_address(text)
            return text
    except Exception as exc:
        logger.debug("Direct IP probe endpoint %s failed: %s", endpoint, exc)
        return None


async def get_host_direct_ip(timeout: float = 5.0) -> Optional[str]:
    """探测并缓存服务器宿主机的直连出口 IP（TTL=600s）。"""
    cached = _HOST_IP_CACHE.get("host_exit_ip")
    if cached is not None:
        return cached

    for endpoint in DEFAULT_PROBE_ENDPOINTS:
        ip = await _fetch_ip_direct(endpoint, timeout=timeout)
        if ip:
            _HOST_IP_CACHE.set("host_exit_ip", ip)
            return ip
    return None


def _fetch_socks_sync(proxy_dict: dict, endpoint: str, timeout: float) -> str:
    """使用 PySocks 同步请求 socks 代理（在线程池运行）。"""
    if SocksiPyHandler is None or socks is None:
        raise RuntimeError("PySocks is not installed")
    scheme = str(proxy_dict.get("scheme", "socks5")).lower()
    proxy_type = socks.SOCKS4 if scheme == "socks4" else socks.SOCKS5
    handler = SocksiPyHandler(
        proxy_type,
        str(proxy_dict["hostname"]),
        int(proxy_dict["port"]),
        username=proxy_dict.get("username"),
        password=proxy_dict.get("password"),
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), handler)
    req = urllib.request.Request(endpoint, headers={"User-Agent": "TG-SignPulse-Probe/1.0"})
    with opener.open(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8").strip()


async def _fetch_ip_via_proxy(
    proxy_dict: dict, endpoint: str, timeout: float = 8.0
) -> Optional[str]:
    """通过代理请求指定端点并返回解析后的 IP 地址。"""
    scheme = str(proxy_dict.get("scheme", "http")).lower()
    if scheme in ("http", "https"):
        user = proxy_dict.get("username")
        pwd = proxy_dict.get("password")
        if user:
            quoted_user = urllib.parse.quote(str(user), safe="")
            if pwd:
                quoted_pwd = urllib.parse.quote(str(pwd), safe="")
                auth = f"{quoted_user}:{quoted_pwd}@"
            else:
                auth = f"{quoted_user}@"
        else:
            auth = ""
        host = _format_host_for_url(str(proxy_dict["hostname"]))
        proxy_url = f"{scheme}://{auth}{host}:{proxy_dict['port']}"
        try:
            async with httpx.AsyncClient(proxy=proxy_url, trust_env=False, timeout=timeout) as client:
                resp = await client.get(endpoint, headers={"User-Agent": "TG-SignPulse-Probe/1.0"})
                resp.raise_for_status()
                text = resp.text.strip()
                ipaddress.ip_address(text)
                return text
        except Exception as exc:
            logger.debug("HTTP proxy probe failed via %s: %s", endpoint, exc)
            return None
    elif scheme in ("socks4", "socks5"):
        try:
            text = await asyncio.to_thread(_fetch_socks_sync, proxy_dict, endpoint, timeout)
            ipaddress.ip_address(text)
            return text
        except Exception as exc:
            logger.debug("SOCKS proxy probe failed via %s: %s", endpoint, exc)
            return None
    return None


async def probe_proxy_exit(
    proxy_dict: dict | None,
    timeout: float = 8.0,
    host_ip: Optional[str] = None,
) -> tuple[ProxyProbeStatus, str | None]:
    """
    探测代理出口 IP 并与本地基线对比。
    - 若出口 IP 等于宿主机直连出口 IP，返回 PROXY_PROBE_FAILED
    - 若端点不可达或超时，返回 PROXY_PROBE_UNAVAILABLE
    - 否则返回 OK 及探测到的出口 IP
    具备 TTL=600s 缓存；UNAVAILABLE 同样入缓存，避免代理不可达时
    每次账号操作都阻塞在 8s×端点数的重复探测上。
    """
    if not proxy_dict:
        return ProxyProbeStatus.UNAVAILABLE, "No proxy configured"

    cache_key = _make_proxy_cache_key(proxy_dict)
    cached = _PROBE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    if host_ip is None:
        host_ip = await get_host_direct_ip(timeout=min(timeout, 5.0))

    detected_ip: Optional[str] = None
    last_err: Optional[str] = None

    for endpoint in DEFAULT_PROBE_ENDPOINTS:
        try:
            ip = await _fetch_ip_via_proxy(proxy_dict, endpoint, timeout=timeout)
            if ip:
                detected_ip = ip
                break
        except Exception as exc:
            last_err = str(exc)

    if detected_ip is not None:
        if host_ip is None:
            # Baseline direct IP probe failed: cannot prove proxy is not leaking host direct IP.
            # Fail closed to prevent silent leaks.
            result = (
                ProxyProbeStatus.UNAVAILABLE,
                "Host direct IP baseline probe unavailable",
            )
        elif detected_ip == host_ip:
            result = (ProxyProbeStatus.FAILED, detected_ip)
        else:
            result = (ProxyProbeStatus.OK, detected_ip)
    else:
        result = (ProxyProbeStatus.UNAVAILABLE, last_err or "Connection timed out")

    _PROBE_CACHE.set(cache_key, result)
    return result

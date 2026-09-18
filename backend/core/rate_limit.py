from __future__ import annotations

import ipaddress
import math
import time
from collections import deque
from threading import Lock
from typing import Deque, Dict, Iterable, Tuple

from fastapi import HTTPException, Request, status

BucketKey = Tuple[str, str]


class InMemoryRateLimiter:
    # 桶内条目超过该时长即视为过期可清理；远大于业务窗口（≤600s）与封锁（≤1800s）
    _STALE_BUCKET_AGE = 3600.0
    # 每 N 次 hit 触发一次全局清扫，摊薄 O(n) 成本
    _SWEEP_INTERVAL = 256

    def __init__(self) -> None:
        self._lock = Lock()
        self._attempts: Dict[BucketKey, Deque[float]] = {}
        self._blocked_until: Dict[BucketKey, float] = {}
        self._hits_since_sweep = 0

    def reset(self, scope: str, key: str) -> None:
        bucket = (scope, key)
        with self._lock:
            self._attempts.pop(bucket, None)
            self._blocked_until.pop(bucket, None)

    def discard_latest_attempt(self, scope: str, key: str) -> None:
        """撤销当前请求的计数，但保留此前失败次数与封锁状态。"""
        bucket = (scope, key)
        with self._lock:
            attempts = self._attempts.get(bucket)
            if not attempts:
                return
            attempts.pop()
            if not attempts:
                self._attempts.pop(bucket, None)

    def reset_all(self) -> None:
        with self._lock:
            self._attempts.clear()
            self._blocked_until.clear()
            self._hits_since_sweep = 0

    def _sweep_expired(self, now: float) -> None:
        """机会式清理过期桶，防止 (scope, key) 组合随请求数无限增长。"""
        stale = now - self._STALE_BUCKET_AGE
        for bucket, attempts in list(self._attempts.items()):
            if not attempts or attempts[-1] <= stale:
                self._attempts.pop(bucket, None)
        for bucket, blocked_until in list(self._blocked_until.items()):
            if blocked_until <= now:
                self._blocked_until.pop(bucket, None)

    def hit(
        self,
        *,
        scope: str,
        key: str,
        max_attempts: int,
        window_seconds: int,
        block_seconds: int,
        detail: str,
    ) -> None:
        bucket = (scope, key)
        now = time.monotonic()

        with self._lock:
            self._hits_since_sweep += 1
            if self._hits_since_sweep >= self._SWEEP_INTERVAL:
                self._hits_since_sweep = 0
                self._sweep_expired(now)

            blocked_until = self._blocked_until.get(bucket, 0.0)
            if blocked_until > now:
                retry_after = max(int(math.ceil(blocked_until - now)), 1)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=detail,
                    headers={"Retry-After": str(retry_after)},
                )

            attempts = self._attempts.setdefault(bucket, deque())
            cutoff = now - max(window_seconds, 1)
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()

            attempts.append(now)
            if len(attempts) <= max(max_attempts, 1):
                return

            retry_after = max(int(block_seconds), 1)
            self._blocked_until[bucket] = now + retry_after
            attempts.clear()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=detail,
                headers={"Retry-After": str(retry_after)},
            )


def is_trusted_proxy(client_host: str, trusted_list: Iterable[str]) -> bool:
    """判断 client_host 是否属于受信任的反向代理 IP 或网段。"""
    if not client_host or not isinstance(client_host, str):
        return False
    try:
        client_ip = ipaddress.ip_address(client_host.strip())
        # 归一化 IPv4-mapped IPv6 地址 (例如 ::ffff:127.0.0.1 -> 127.0.0.1)
        if isinstance(client_ip, ipaddress.IPv6Address) and client_ip.ipv4_mapped:
            client_ip = client_ip.ipv4_mapped
    except ValueError:
        return False

    for trusted in trusted_list:
        trusted = str(trusted).strip()
        if not trusted:
            continue
        if trusted in ("*", "all"):
            return True
        try:
            if "/" in trusted:
                net = ipaddress.ip_network(trusted, strict=False)
                if client_ip in net:
                    return True
            else:
                target_ip = ipaddress.ip_address(trusted)
                if isinstance(target_ip, ipaddress.IPv6Address) and target_ip.ipv4_mapped:
                    target_ip = target_ip.ipv4_mapped
                if client_ip == target_ip:
                    return True
        except ValueError:
            continue
    return False


def get_client_identifier(request: Request) -> str:
    """
    提取安全的客户端标识 IP。
    仅当直连对端处于受信任代理列表时，才解析转发标头；
    采用从右向左逐级回溯跳过可信代理的策略，防止攻击者通过伪造 X-Forwarded-For 最左端 IP 绕过限流。
    """
    raw_host = getattr(getattr(request, "client", None), "host", None)
    client_host = raw_host.strip() if isinstance(raw_host, str) else ""

    trusted: list[str] = ["127.0.0.1", "::1"]
    try:
        from backend.core.config import get_settings

        trusted = get_settings().trusted_proxies
    except Exception:
        pass

    # 若对端为空（如单元测试未伪造 client）或直连对端为可信反向代理，才解析转发头
    if not client_host or is_trusted_proxy(client_host, trusted):
        headers = getattr(request, "headers", {})
        forwarded_for = headers.get("x-forwarded-for", "") if hasattr(headers, "get") else ""
        if isinstance(forwarded_for, str) and forwarded_for.strip():
            hops = [h.strip() for h in forwarded_for.split(",") if h.strip()]
            if not client_host:
                # 针对缺少直连客户端信息的测试 Mock 请求，取首跳并截断
                return hops[0][:64]

            # 真实代理场景：从右至左跳过所有受信任的反向代理，取首个不可信的外部客户端 IP
            for hop in reversed(hops):
                if not is_trusted_proxy(hop, trusted):
                    return hop[:64]
            # 若所有跳数都在受信任网段内，回退取最左跳
            if hops:
                return hops[0][:64]

        real_ip = headers.get("x-real-ip", "") if hasattr(headers, "get") else ""
        if isinstance(real_ip, str) and real_ip.strip():
            return real_ip.strip()[:64]

    if client_host:
        return client_host[:64]
    return "unknown"


def compose_rate_limit_key(request: Request, *parts: str) -> str:
    normalized_parts = [
        str(part).strip().lower()[:128]
        for part in parts
        if part is not None and str(part).strip()
    ]
    return "|".join([get_client_identifier(request), *normalized_parts])


_rate_limiter: InMemoryRateLimiter | None = None


def get_rate_limiter() -> InMemoryRateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = InMemoryRateLimiter()
    return _rate_limiter

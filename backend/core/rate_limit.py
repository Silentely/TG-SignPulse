from __future__ import annotations

import math
import time
from collections import deque
from threading import Lock
from typing import Deque, Dict, Tuple

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


def get_client_identifier(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        first_hop = forwarded_for.split(",", 1)[0].strip()
        if first_hop:
            return first_hop

    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip

    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def compose_rate_limit_key(request: Request, *parts: str) -> str:
    normalized_parts = [part.strip().lower() for part in parts if isinstance(part, str) and part.strip()]
    return "|".join([get_client_identifier(request), *normalized_parts])


_rate_limiter: InMemoryRateLimiter | None = None


def get_rate_limiter() -> InMemoryRateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = InMemoryRateLimiter()
    return _rate_limiter

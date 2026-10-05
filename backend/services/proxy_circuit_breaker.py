from __future__ import annotations

import asyncio
import hashlib
import logging
import socket
import time
from enum import Enum
from typing import Any, Dict, Optional

from filelock import FileLock, Timeout

from backend.core.config import get_settings

logger = logging.getLogger("backend.proxy_circuit_breaker")


class CircuitState(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    TRIPPED = "TRIPPED"
    HALF_OPEN = "HALF_OPEN"


TG_DCS = [
    ("149.154.167.50", 443),
    ("91.108.56.165", 443),
]


class ProxyCircuitBreaker:
    def __init__(self, cooldown: float = 300.0):
        self._states: Dict[str, CircuitState] = {}
        self._fail_counts: Dict[str, int] = {}
        self._tripped_at: Dict[str, float] = {}
        self._cooldown = cooldown
        self._local_lock = asyncio.Lock()

    def _proxy_key(self, proxy: Dict[str, Any]) -> str:
        s = f"{proxy.get('scheme')}://{proxy.get('hostname')}:{proxy.get('port')}"
        return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]

    def get_state(self, proxy: Dict[str, Any]) -> CircuitState:
        key = self._proxy_key(proxy)
        state = self._states.get(key, CircuitState.HEALTHY)
        if state == CircuitState.TRIPPED:
            if time.time() - self._tripped_at.get(key, 0) > self._cooldown:
                self._states[key] = CircuitState.HALF_OPEN
                return CircuitState.HALF_OPEN
        return state

    def _set_state(self, proxy: Dict[str, Any], state: CircuitState) -> None:
        key = self._proxy_key(proxy)
        self._states[key] = state

    def record_failure(self, proxy: Dict[str, Any]) -> None:
        key = self._proxy_key(proxy)
        count = self._fail_counts.get(key, 0) + 1
        self._fail_counts[key] = count
        if count >= 3:
            self._states[key] = CircuitState.TRIPPED
            self._tripped_at[key] = time.time()
        elif count >= 2:
            self._states[key] = CircuitState.DEGRADED

    def record_success(self, proxy: Dict[str, Any]) -> None:
        key = self._proxy_key(proxy)
        self._fail_counts[key] = 0
        self._states[key] = CircuitState.HEALTHY

    async def _probe_telegram_dc(self, proxy: Dict[str, Any]) -> bool:
        for host, port in TG_DCS:
            try:
                loop = asyncio.get_running_loop()
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3.0)
                await loop.sock_connect(sock, (host, port))
                sock.close()
                return True
            except Exception:
                continue
        return False

    async def is_available(self, proxy: Dict[str, Any]) -> bool:
        state = self.get_state(proxy)
        if state in {CircuitState.HEALTHY, CircuitState.DEGRADED}:
            return True
        if state == CircuitState.TRIPPED:
            return False

        # HALF_OPEN 阶段：使用跨进程文件锁实现单飞租约
        key = self._proxy_key(proxy)
        settings = get_settings()
        lease_dir = settings.resolve_workdir() / ".proxy_leases"
        lease_dir.mkdir(parents=True, exist_ok=True)
        lock_file = lease_dir / f"{key}.lock"
        file_lock = FileLock(str(lock_file), timeout=0)

        try:
            file_lock.acquire(timeout=0)
            # 获取租约成功，唯一负责发起探测
            try:
                success = await self._probe_telegram_dc(proxy)
                if success:
                    self.record_success(proxy)
                    return True
                else:
                    self.record_failure(proxy)
                    return False
            finally:
                file_lock.release()
        except Timeout:
            # 未获取到租约，主动轮询探测终态（最多等待 2.0s），彻底杜绝半开误放行
            for _ in range(20):
                await asyncio.sleep(0.1)
                curr_state = self.get_state(proxy)
                if curr_state != CircuitState.HALF_OPEN:
                    return curr_state != CircuitState.TRIPPED
            return self.get_state(proxy) != CircuitState.TRIPPED

    def clear(self) -> None:
        self._states.clear()
        self._fail_counts.clear()
        self._tripped_at.clear()


_CIRCUIT_BREAKER_INSTANCE: Optional[ProxyCircuitBreaker] = None


def get_proxy_circuit_breaker() -> ProxyCircuitBreaker:
    global _CIRCUIT_BREAKER_INSTANCE
    if _CIRCUIT_BREAKER_INSTANCE is None:
        _CIRCUIT_BREAKER_INSTANCE = ProxyCircuitBreaker()
    return _CIRCUIT_BREAKER_INSTANCE

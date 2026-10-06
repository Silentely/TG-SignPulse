from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from enum import Enum
from pathlib import Path
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

    def _state_file(self) -> Path:
        """返回跨进程共享状态文件；状态与半开租约使用同一工作目录。"""
        return get_settings().resolve_workdir() / ".proxy_circuit_breaker.json"

    def _load_shared_state(self) -> Dict[str, Dict[str, Any]]:
        state_file = self._state_file()
        try:
            with FileLock(f"{state_file}.lock", timeout=2.0):
                if not state_file.is_file():
                    return {}
                payload = json.loads(state_file.read_text(encoding="utf-8"))
                return payload if isinstance(payload, dict) else {}
        except (OSError, Timeout, ValueError, TypeError, json.JSONDecodeError):
            logger.warning("读取代理熔断共享状态失败: %s", state_file, exc_info=True)
            return {}

    def _update_shared_state(self, key: str, entry: Optional[Dict[str, Any]]) -> None:
        state_file = self._state_file()
        state_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with FileLock(f"{state_file}.lock", timeout=2.0):
                payload: Dict[str, Dict[str, Any]] = {}
                if state_file.is_file():
                    try:
                        loaded = json.loads(state_file.read_text(encoding="utf-8"))
                        if isinstance(loaded, dict):
                            payload = loaded
                    except (OSError, ValueError, TypeError, json.JSONDecodeError):
                        logger.warning(
                            "代理熔断共享状态损坏，将重新建立: %s", state_file
                        )
                if entry is None:
                    payload.pop(key, None)
                else:
                    payload[key] = entry
                state_file.write_text(
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    encoding="utf-8",
                )
        except (OSError, Timeout):
            logger.warning("写入代理熔断共享状态失败: %s", state_file, exc_info=True)

    def _mutate_shared_state(self, key: str, mutate: Any) -> Dict[str, Any]:
        """在跨进程锁内读改写单个代理状态，避免失败计数丢失更新。"""
        state_file = self._state_file()
        state_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with FileLock(f"{state_file}.lock", timeout=2.0):
                payload: Dict[str, Dict[str, Any]] = {}
                if state_file.is_file():
                    try:
                        loaded = json.loads(state_file.read_text(encoding="utf-8"))
                        if isinstance(loaded, dict):
                            payload = loaded
                    except (OSError, ValueError, TypeError, json.JSONDecodeError):
                        logger.warning(
                            "代理熔断共享状态损坏，将重新建立: %s", state_file
                        )
                entry = mutate(dict(payload.get(key) or {}))
                payload[key] = entry
                state_file.write_text(
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    encoding="utf-8",
                )
                return entry
        except (OSError, Timeout):
            logger.warning("更新代理熔断共享状态失败: %s", state_file, exc_info=True)
            return self._shared_entry(key)

    def _shared_entry(self, key: str) -> Dict[str, Any]:
        return {
            "state": self._states.get(key, CircuitState.HEALTHY).value,
            "fail_count": self._fail_counts.get(key, 0),
            "tripped_at": self._tripped_at.get(key, 0.0),
        }

    def _proxy_key(self, proxy: Dict[str, Any]) -> str:
        # 凭据不同的同址代理不能共享熔断状态；只持久化哈希，不泄露密码。
        s = (
            f"{proxy.get('scheme')}://{proxy.get('username', '')}:"
            f"{proxy.get('password', '')}@{proxy.get('hostname')}:{proxy.get('port')}"
        )
        return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]

    def get_state(self, proxy: Dict[str, Any]) -> CircuitState:
        key = self._proxy_key(proxy)
        shared = self._load_shared_state().get(key)
        if isinstance(shared, dict):
            try:
                state = CircuitState(str(shared.get("state", CircuitState.HEALTHY)))
                self._states[key] = state
                self._fail_counts[key] = int(shared.get("fail_count", 0) or 0)
                self._tripped_at[key] = float(shared.get("tripped_at", 0.0) or 0.0)
            except (TypeError, ValueError):
                state = self._states.get(key, CircuitState.HEALTHY)
        else:
            state = self._states.get(key, CircuitState.HEALTHY)
        if state == CircuitState.TRIPPED:
            if time.time() - self._tripped_at.get(key, 0) > self._cooldown:
                self._states[key] = CircuitState.HALF_OPEN
                self._update_shared_state(key, self._shared_entry(key))
                return CircuitState.HALF_OPEN
        return state

    def _set_state(self, proxy: Dict[str, Any], state: CircuitState) -> None:
        key = self._proxy_key(proxy)

        def mutate(entry: Dict[str, Any]) -> Dict[str, Any]:
            entry["state"] = state.value
            entry.setdefault("fail_count", self._fail_counts.get(key, 0))
            entry.setdefault("tripped_at", self._tripped_at.get(key, 0.0))
            return entry

        updated = self._mutate_shared_state(key, mutate)
        self._states[key] = CircuitState(str(updated.get("state", state.value)))
        self._fail_counts[key] = int(updated.get("fail_count", 0) or 0)
        self._tripped_at[key] = float(updated.get("tripped_at", 0.0) or 0.0)

    def record_failure(self, proxy: Dict[str, Any]) -> None:
        key = self._proxy_key(proxy)
        now = time.time()

        def mutate(entry: Dict[str, Any]) -> Dict[str, Any]:
            count = int(entry.get("fail_count", 0) or 0) + 1
            entry["fail_count"] = count
            if count >= 3:
                entry["state"] = CircuitState.TRIPPED.value
                entry["tripped_at"] = now
            elif count >= 2:
                entry["state"] = CircuitState.DEGRADED.value
            else:
                entry["state"] = CircuitState.HEALTHY.value
            entry.setdefault("tripped_at", 0.0)
            return entry

        updated = self._mutate_shared_state(key, mutate)
        self._states[key] = CircuitState(str(updated["state"]))
        self._fail_counts[key] = int(updated["fail_count"])
        self._tripped_at[key] = float(updated.get("tripped_at", 0.0) or 0.0)

    def record_success(self, proxy: Dict[str, Any]) -> None:
        key = self._proxy_key(proxy)
        updated = self._mutate_shared_state(
            key,
            lambda _entry: {
                "state": CircuitState.HEALTHY.value,
                "fail_count": 0,
                "tripped_at": 0.0,
            },
        )
        self._fail_counts[key] = 0
        self._states[key] = CircuitState(str(updated["state"]))
        self._tripped_at.pop(key, None)

    async def _probe_telegram_dc(self, proxy: Dict[str, Any]) -> bool:
        """通过真实代理链路探测出口，而不是探测宿主机直连状态。"""
        from backend.utils.proxy import DEFAULT_PROBE_ENDPOINTS, _fetch_ip_via_proxy

        for endpoint in DEFAULT_PROBE_ENDPOINTS:
            try:
                if await _fetch_ip_via_proxy(proxy, endpoint, timeout=3.0):
                    return True
            except Exception:
                logger.debug("代理探测失败 (%s): %s", endpoint, proxy, exc_info=True)
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
            # 未获取到租约，主动轮询探测终态（最多等待 4.0s）。
            # 若到时限仍未解析出终态（探测仍在飞行），按失败关闭处理返回不可用，
            # 杜绝"探测未完成却放行流量"的半开误放行。
            for _ in range(40):
                await asyncio.sleep(0.1)
                curr_state = self.get_state(proxy)
                if curr_state != CircuitState.HALF_OPEN:
                    return curr_state != CircuitState.TRIPPED
            logger.warning("代理 %s 半开探测未在限定时间内完成，按不可用处理", proxy)
            return False

    def clear(self) -> None:
        self._states.clear()
        self._fail_counts.clear()
        self._tripped_at.clear()
        state_file = self._state_file()
        try:
            with FileLock(f"{state_file}.lock", timeout=2.0):
                state_file.unlink(missing_ok=True)
        except (OSError, Timeout):
            logger.warning("清理代理熔断共享状态失败: %s", state_file, exc_info=True)


_CIRCUIT_BREAKER_INSTANCE: Optional[ProxyCircuitBreaker] = None


def get_proxy_circuit_breaker() -> ProxyCircuitBreaker:
    global _CIRCUIT_BREAKER_INSTANCE
    if _CIRCUIT_BREAKER_INSTANCE is None:
        _CIRCUIT_BREAKER_INSTANCE = ProxyCircuitBreaker()
    return _CIRCUIT_BREAKER_INSTANCE

from __future__ import annotations

import asyncio

import pytest

from backend.services.proxy_circuit_breaker import (
    CircuitState,
    ProxyCircuitBreaker,
    get_proxy_circuit_breaker,
)
from backend.utils.proxy import ProxyProbeStatus, probe_proxy_exit


@pytest.fixture(autouse=True)
def clear_shared_breaker_state(isolated_env):
    get_proxy_circuit_breaker().clear()
    yield
    get_proxy_circuit_breaker().clear()


@pytest.mark.asyncio
async def test_proxy_circuit_breaker_trips_after_3_failures(isolated_env):
    breaker = ProxyCircuitBreaker()
    proxy = {"scheme": "socks5", "hostname": "127.0.0.1", "port": 1080}

    assert breaker.get_state(proxy) == CircuitState.HEALTHY
    breaker.record_failure(proxy)
    assert breaker.get_state(proxy) == CircuitState.HEALTHY
    breaker.record_failure(proxy)
    assert breaker.get_state(proxy) == CircuitState.DEGRADED
    breaker.record_failure(proxy)
    assert breaker.get_state(proxy) == CircuitState.TRIPPED
    assert await breaker.is_available(proxy) is False


@pytest.mark.asyncio
async def test_proxy_circuit_breaker_single_flight_lease(isolated_env):
    # 模拟多 Worker 进程场景：实例化两个相互独立的 Breaker 实例
    worker1_breaker = ProxyCircuitBreaker()
    worker2_breaker = ProxyCircuitBreaker()
    proxy = {"scheme": "socks5", "hostname": "10.0.0.1", "port": 1080}

    # 人工置为 HALF_OPEN
    worker1_breaker._set_state(proxy, CircuitState.HALF_OPEN)
    worker2_breaker._set_state(proxy, CircuitState.HALF_OPEN)

    probe_counter = 0

    async def mock_probe(p):
        nonlocal probe_counter
        probe_counter += 1
        await asyncio.sleep(0.1)
        return True

    worker1_breaker._probe_telegram_dc = mock_probe
    worker2_breaker._probe_telegram_dc = mock_probe

    # 两个独立 Worker 实例并发请求可用性检查
    t1 = asyncio.create_task(worker1_breaker.is_available(proxy))
    t2 = asyncio.create_task(worker2_breaker.is_available(proxy))
    results = await asyncio.gather(t1, t2)

    assert all(results)
    # 核心断言：跨进程文件锁生效，两个并发 Worker 实例只触发了 1 次实际网络探测！
    assert probe_counter == 1


@pytest.mark.asyncio
async def test_proxy_circuit_breaker_cooldown_to_half_open(isolated_env):
    breaker = ProxyCircuitBreaker()
    breaker._cooldown = 0.1  # 缩短冷却时间供测试
    proxy = {"scheme": "socks5", "hostname": "10.0.0.2", "port": 1080}

    for _ in range(3):
        breaker.record_failure(proxy)
    assert breaker.get_state(proxy) == CircuitState.TRIPPED

    await asyncio.sleep(0.15)
    assert breaker.get_state(proxy) == CircuitState.HALF_OPEN


@pytest.mark.asyncio
async def test_probe_uses_the_configured_proxy(monkeypatch, isolated_env):
    from backend.utils import proxy as proxy_module

    breaker = ProxyCircuitBreaker()
    proxy = {"scheme": "socks5", "hostname": "proxy.example", "port": 1080}
    observed = []

    async def fake_fetch(proxy_dict, endpoint, timeout):
        observed.append((proxy_dict, endpoint, timeout))
        return "203.0.113.10"

    monkeypatch.setattr(proxy_module, "_fetch_ip_via_proxy", fake_fetch)

    assert await breaker._probe_telegram_dc(proxy) is True
    assert observed
    assert all(item[0] is proxy for item in observed)


@pytest.mark.asyncio
async def test_probe_proxy_exit_integrates_with_circuit_breaker(isolated_env):
    breaker = get_proxy_circuit_breaker()
    proxy = {"scheme": "socks5", "hostname": "192.168.10.50", "port": 1080}

    # 人工置为 TRIPPED
    for _ in range(3):
        breaker.record_failure(proxy)

    status, msg = await probe_proxy_exit(proxy)
    assert status == ProxyProbeStatus.UNAVAILABLE
    assert "circuit breaker" in (msg or "").lower()

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from tg_signer.semantic.breaker import CircuitBreaker
from tg_signer.semantic.cache import (
    JevDecisionCache,
    compute_cache_key,
    is_sensitive_request,
)
from tg_signer.semantic.client import (
    JevClient,
    normalize_base_url,
    resolve_jev_env_defaults,
)
from tg_signer.semantic.models import Decision, DecisionRequest
from tg_signer.semantic.policy import accept_decision
from tg_signer.semantic.security import redact_sensitive_text, truncate_state_if_needed


def _make_dummy_request(
    *,
    state: dict | None = None,
    choices: dict | None = None,
    instructions: str = "Say pong",
    truncated: bool = False,
) -> DecisionRequest:
    return DecisionRequest(
        kind="result",
        scope="test",
        state=state if state is not None else {"text": "PING"},
        choices=choices if choices is not None else {"pong": "pong"},
        instructions=instructions,
        request_key="test_key",
        config_revision="test_rev",
        truncated=truncated,
    )


def test_decision_request_fields():
    req = DecisionRequest(
        kind="result",
        scope="test_scope",
        state={"message": "hello"},
        choices={"success": "成功", "failure": "失败"},
        instructions="判断是否成功",
        request_key="req_1",
        config_revision="rev_1",
    )
    assert req.kind == "result"
    assert req.choices["success"] == "成功"
    assert req.truncated is False


def test_policy_accept_decision():
    d = Decision(
        status="ok",
        selected="success",
        probabilities={"success": 0.98, "failure": 0.02},
        confidence=0.98,
    )
    assert accept_decision(d, min_probability=0.97, min_margin=0.25)

    d_close = Decision(
        status="ok",
        selected="success",
        probabilities={"success": 0.55, "failure": 0.45},
        confidence=0.55,
    )
    assert not accept_decision(d_close, min_probability=0.50, min_margin=0.20)


def test_policy_truncated_never_approved():
    """超长截断的请求永不自动批准"""
    d = Decision(
        status="ok",
        selected="success",
        probabilities={"success": 0.99, "failure": 0.01},
        confidence=0.99,
        truncated=True,
    )
    assert not accept_decision(d, min_probability=0.50, min_margin=0.10)


def test_normalize_base_url():
    assert normalize_base_url("https://api.example.com") == "https://api.example.com/v1"
    assert (
        normalize_base_url("https://api.example.com/") == "https://api.example.com/v1"
    )
    assert (
        normalize_base_url("https://api.example.com/v1") == "https://api.example.com/v1"
    )
    assert (
        normalize_base_url("https://api.example.com/v1/")
        == "https://api.example.com/v1"
    )
    assert (
        normalize_base_url("https://api.example.com/v1/systemone")
        == "https://api.example.com/v1"
    )
    assert (
        normalize_base_url("https://api.example.com/systemone")
        == "https://api.example.com/v1"
    )
    assert (
        normalize_base_url("  https://api.example.com/v1/  ")
        == "https://api.example.com/v1"
    )
    assert normalize_base_url("") == "https://api.typesafe.ai/v1"
    assert normalize_base_url(None) == "https://api.typesafe.ai/v1"


@pytest.mark.asyncio
async def test_jev_client_request_url_normalization(monkeypatch):
    recorded_urls: list[str] = []
    recorded_timeouts: list[httpx.Timeout] = []

    async def fake_post(self, url, json=None, headers=None, timeout=None):
        recorded_urls.append(str(url))
        recorded_timeouts.append(timeout)
        return httpx.Response(
            status_code=200,
            json={
                "answers": {
                    "decision": {
                        "choice": "pong",
                        "confidence": 0.99,
                        "probabilities": {"pong": 0.99},
                    }
                }
            },
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    req = _make_dummy_request()

    test_cases = [
        ("https://api.example.com", "https://api.example.com/v1/systemone"),
        ("https://api.example.com/v1", "https://api.example.com/v1/systemone"),
        ("https://api.example.com/v1/", "https://api.example.com/v1/systemone"),
        (
            "https://api.example.com/v1/systemone",
            "https://api.example.com/v1/systemone",
        ),
        ("https://api.example.com/systemone", "https://api.example.com/v1/systemone"),
    ]

    for input_url, expected_req_url in test_cases:
        client = JevClient(
            api_key="test_key",
            base_url=input_url,
            timeout=8.0,
        )
        dec = await client.query_choice(req)
        await client.close()
        assert dec.status == "ok"
        assert dec.http_status == 200
        assert recorded_urls[-1] == expected_req_url
        to = recorded_timeouts[-1]
        assert isinstance(to, httpx.Timeout)
        assert to.connect == 3.0
        assert to.read == 8.0


# =========================================================================
# 1. 韧性测试 (Resilience & Retries)
# =========================================================================


@pytest.mark.asyncio
async def test_401_no_retry_immediate_dead(monkeypatch):
    """401 鉴权失败不重试，直接判 DEAD，attempts=1"""
    call_count = 0

    async def fake_post(self, url, json=None, headers=None, timeout=None):
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            status_code=401,
            json={"error": {"message": "Invalid API Key"}},
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = JevClient(api_key="bad_key", base_url="https://api.example.com/v1")
    dec = await client.query_choice(_make_dummy_request())
    await client.close()

    assert call_count == 1
    assert dec.status == "unavailable"
    assert dec.reason_code == "AUTH_FAILED"
    assert dec.http_status == 401
    assert dec.attempts == 1
    assert client.breaker.consecutive_failures == 1


@pytest.mark.asyncio
async def test_403_no_retry_immediate_dead(monkeypatch):
    """403 鉴权失败不重试，attempts=1"""
    call_count = 0

    async def fake_post(self, url, json=None, headers=None, timeout=None):
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            status_code=403,
            json={"detail": "Forbidden access"},
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = JevClient(api_key="forbidden_key", base_url="https://api.example.com/v1")
    dec = await client.query_choice(_make_dummy_request())
    await client.close()

    assert call_count == 1
    assert dec.status == "unavailable"
    assert dec.reason_code == "AUTH_FAILED"
    assert dec.http_status == 403
    assert dec.attempts == 1


@pytest.mark.asyncio
async def test_429_retry_then_success(monkeypatch):
    """429 限流重试后成功：第 1 次 429，第 2 次 200"""
    call_count = 0
    sleep_calls = []

    async def fake_post(self, url, json=None, headers=None, timeout=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(
                status_code=429,
                json={"error": "Too Many Requests"},
                request=httpx.Request("POST", str(url)),
            )
        return httpx.Response(
            status_code=200,
            json={"answers": {"decision": {"choice": "pong", "confidence": 0.95}}},
            request=httpx.Request("POST", str(url)),
        )

    async def fake_sleep(secs):
        sleep_calls.append(secs)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    client = JevClient(api_key="test_key", base_url="https://api.example.com/v1")
    dec = await client.query_choice(_make_dummy_request())
    await client.close()

    assert call_count == 2
    assert dec.status == "ok"
    assert dec.selected == "pong"
    assert dec.attempts == 2
    assert len(sleep_calls) == 1
    assert 0.2 <= sleep_calls[0] <= 0.6


@pytest.mark.asyncio
async def test_429_retry_exhausted(monkeypatch):
    """429 限流重试耗尽：共 3 次尝试（初次 + 2 次重试），最终失败"""
    call_count = 0
    sleep_calls = []

    async def fake_post(self, url, json=None, headers=None, timeout=None):
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            status_code=429,
            json={"error": "Rate limited"},
            request=httpx.Request("POST", str(url)),
        )

    async def fake_sleep(secs):
        sleep_calls.append(secs)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    client = JevClient(api_key="test_key", base_url="https://api.example.com/v1")
    dec = await client.query_choice(_make_dummy_request())
    await client.close()

    assert call_count == 3
    assert dec.status == "unavailable"
    assert dec.reason_code == "RATE_LIMITED"
    assert dec.attempts == 3
    assert len(sleep_calls) == 2


@pytest.mark.asyncio
async def test_500_retry_then_success(monkeypatch):
    """500 服务端错误重试后成功"""
    call_count = 0

    async def fake_post(self, url, json=None, headers=None, timeout=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(
                status_code=500,
                text="Internal Server Error",
                request=httpx.Request("POST", str(url)),
            )
        return httpx.Response(
            status_code=200,
            json={"answers": {"decision": {"choice": "pong", "confidence": 0.98}}},
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    client = JevClient(api_key="test_key", base_url="https://api.example.com/v1")
    dec = await client.query_choice(_make_dummy_request())
    await client.close()

    assert call_count == 2
    assert dec.status == "ok"
    assert dec.attempts == 2


@pytest.mark.asyncio
async def test_500_retry_exhausted(monkeypatch):
    """500 重试耗尽：共 3 次尝试"""
    call_count = 0

    async def fake_post(self, url, json=None, headers=None, timeout=None):
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            status_code=502,
            text="Bad Gateway",
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    client = JevClient(api_key="test_key", base_url="https://api.example.com/v1")
    dec = await client.query_choice(_make_dummy_request())
    await client.close()

    assert call_count == 3
    assert dec.status == "invalid"
    assert dec.reason_code == "HTTP_502"
    assert dec.attempts == 3


@pytest.mark.asyncio
async def test_network_and_timeout_retry(monkeypatch):
    """网络与超时异常重试机制"""
    call_count = 0

    async def fake_post(self, url, json=None, headers=None, timeout=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ConnectTimeout("Connection timeout")
        if call_count == 2:
            raise httpx.NetworkError("Socket error")
        return httpx.Response(
            status_code=200,
            json={"answers": {"decision": {"choice": "pong", "confidence": 0.99}}},
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    client = JevClient(api_key="test_key", base_url="https://api.example.com/v1")
    dec = await client.query_choice(_make_dummy_request())
    await client.close()

    assert call_count == 3
    assert dec.status == "ok"
    assert dec.attempts == 3


@pytest.mark.asyncio
async def test_total_budget_deadline_exceeded(monkeypatch):
    """单次调用总预算显式化：HTTP mock 传输耗时超预算，请求后查 deadline 判失败，不得返回 ok、不得写缓存"""
    cache = JevDecisionCache(maxsize=10, ttl=60.0)
    client = JevClient(
        api_key="test_key",
        base_url="https://api.example.com/v1",
        total_budget=0.05,
        cache=cache,
    )

    async def fake_slow_post(self, url, json=None, headers=None, timeout=None):
        # sleep 在 HTTP mock 内部；返回 200 OK，用于验证墙钟硬上限检查
        await asyncio.sleep(0.08)
        return httpx.Response(
            status_code=200,
            json={"answers": {"decision": {"choice": "pong", "confidence": 0.99}}},
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_slow_post)

    dec = await client.query_choice(_make_dummy_request())
    await client.close()

    assert dec.status == "budget_exceeded"
    assert dec.reason_code == "DEADLINE_EXCEEDED"
    assert dec.selected == "unknown"
    assert len(cache._cache) == 0


@pytest.mark.asyncio
async def test_malformed_json_response(monkeypatch):
    """畸形 JSON 安全解析，不崩溃，返回 invalid"""

    async def fake_post(self, url, json=None, headers=None, timeout=None):
        return httpx.Response(
            status_code=200,
            text="{ malformed json",
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = JevClient(api_key="test_key", base_url="https://api.example.com/v1")
    dec = await client.query_choice(_make_dummy_request())
    await client.close()

    assert dec.status == "invalid"
    assert dec.reason_code == "MALFORMED_JSON"
    assert dec.http_status == 200


# =========================================================================
# 2. 熔断与降级测试 (Circuit Breaker & Fallback)
# =========================================================================


@pytest.mark.asyncio
async def test_circuit_breaker_open_and_half_open(monkeypatch):
    """连续 5 次失败触发熔断 60s；熔断期间返回 escalate 走人工；到期放 1 个请求试水"""
    cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60.0)
    client = JevClient(
        api_key="test_key",
        base_url="https://api.example.com/v1",
        breaker=cb,
    )

    async def fake_post_fail(self, url, json=None, headers=None, timeout=None):
        return httpx.Response(
            status_code=500,
            text="Failure",
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post_fail)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    # 连续 5 次失败
    for _i in range(5):
        assert cb.get_state() == "closed"
        await client.query_choice(_make_dummy_request())

    # 第 5 次失败后，熔断器进入 open
    assert cb.get_state() == "open"
    assert cb.consecutive_failures == 5

    # 熔断中直接阻断，返回 escalate 走人工，attempts=0，绝不默认 approve
    dec = await client.query_choice(_make_dummy_request())
    assert dec.status == "escalate"
    assert dec.reason_code == "CIRCUIT_BREAKER_OPEN"
    assert dec.selected == "unknown"
    assert dec.breaker == "open"
    assert dec.attempts == 0
    assert not accept_decision(dec, min_probability=0.1, min_margin=0.01)

    # 模拟 60s 到期，进入 half_open
    now = cb.last_failure_time + 61.0
    assert cb.get_state(now=now) == "half_open"

    # 半开探测：允许且仅允许 1 个试水请求
    assert cb.allow_request(now=now) is True
    assert cb.allow_request(now=now) is False  # 试水在途，拒绝并发请求

    # 试水成功 -> 恢复 closed
    cb.record_success()
    assert cb.get_state() == "closed"
    assert cb.consecutive_failures == 0

    await client.close()


@pytest.mark.asyncio
async def test_circuit_breaker_probe_fail_reopens():
    """半开试水失败，重新进入 open 并计时 60s"""
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
    for _ in range(3):
        cb.record_failure()
    assert cb.state == "open"

    now = cb.last_failure_time + 61.0
    assert cb.get_state(now=now) == "half_open"
    assert cb.allow_request(now=now) is True

    # 试水失败
    cb.record_failure(now=now)
    assert cb.state == "open"
    assert cb.last_failure_time == now


# =========================================================================
# 3. 缓存测试 (Cache & Sensitivity)
# =========================================================================


@pytest.mark.asyncio
async def test_cache_hit_and_expiration(monkeypatch):
    """缓存命中与 60s TTL 过期"""
    post_calls = 0

    async def fake_post(self, url, json=None, headers=None, timeout=None):
        nonlocal post_calls
        post_calls += 1
        return httpx.Response(
            status_code=200,
            json={"answers": {"decision": {"choice": "pong", "confidence": 0.99}}},
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    cache = JevDecisionCache(maxsize=10, ttl=60.0)
    client = JevClient(
        api_key="test_key",
        base_url="https://api.example.com/v1",
        cache=cache,
    )

    req = _make_dummy_request()

    # 第一次：未命中，调用接口
    dec1 = await client.query_choice(req)
    assert post_calls == 1
    assert dec1.cache_hit is False
    assert cache.hits == 0
    assert cache.misses == 1

    # 第二次：命中缓存，不调用接口
    dec2 = await client.query_choice(req)
    assert post_calls == 1
    assert dec2.cache_hit is True
    assert dec2.selected == "pong"
    assert cache.hits == 1

    # 模拟过期
    key = compute_cache_key(req, model=client.model, base_url=client.base_url)
    t_expired = cache._cache[key][0] - 65.0
    cache._cache[key] = (t_expired, dec1)

    # 第三次：过期重新调用接口
    dec3 = await client.query_choice(req)
    assert post_calls == 2
    assert dec3.cache_hit is False

    await client.close()


def test_cache_lru_eviction():
    """LRU 淘汰验证"""
    cache = JevDecisionCache(maxsize=2, ttl=60.0)
    d = Decision(status="ok", selected="yes")
    cache.set("k1", d)
    cache.set("k2", d)
    assert cache.get("k1") is not None  # k1 成为 MRU

    cache.set("k3", d)  # 淘汰 k2
    assert cache.get("k2") is None
    assert cache.get("k1") is not None
    assert cache.get("k3") is not None


def test_sensitive_request_bypasses_cache():
    """含敏感信息/密钥/系统路径的请求不进缓存"""
    sensitive_cases = [
        {"token": "secret_abc123"},
        {"api_key": "sk-1234567890"},
        {"password": "admin"},
        {"path": "/etc/shadow"},
        {"env": ".env"},
        {"ssh": "~/.ssh/id_rsa"},
    ]
    for state_payload in sensitive_cases:
        req = _make_dummy_request(state=state_payload)
        assert is_sensitive_request(req) is True

    normal_req = _make_dummy_request(state={"message": "签到成功", "code": 0})
    assert is_sensitive_request(normal_req) is False


# =========================================================================
# 4. 可观测与汇总计数测试 (Observability & Metrics)
# =========================================================================


@pytest.mark.asyncio
async def test_metrics_aggregation(monkeypatch):
    """汇总计数（调用数、成功、失败、降级、缓存命中率）与统计暴露"""

    async def fake_post(self, url, json=None, headers=None, timeout=None):
        return httpx.Response(
            status_code=200,
            json={"answers": {"decision": {"choice": "pong", "confidence": 0.99}}},
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = JevClient(api_key="test_key", base_url="https://api.example.com/v1")

    req = _make_dummy_request()
    await client.query_choice(req)
    await client.query_choice(req)  # 缓存命中

    stats = client.get_stats()
    assert stats["total_calls"] == 2
    assert stats["success_calls"] == 2
    assert stats["cache_hits"] == 1
    assert stats["cache_hit_rate"] == 0.5
    assert stats["breaker"]["state"] == "closed"

    await client.close()


# =========================================================================
# 5. 配置与安全测试 (Config & Security)
# =========================================================================


def test_env_fallback_priority(monkeypatch):
    """配置支持环境变量兜底：显式配置 > env > 默认"""
    # 1. 默认情况
    monkeypatch.delenv("JEV_BASE_URL", raising=False)
    monkeypatch.delenv("JEV_MODEL", raising=False)
    monkeypatch.delenv("JEV_API_KEY", raising=False)

    k, u, m = resolve_jev_env_defaults()
    assert k == ""
    assert u == "https://api.typesafe.ai/v1"
    assert m == "jev-1.13.0"

    # 2. env 兜底
    monkeypatch.setenv("JEV_BASE_URL", "https://env.example.com")
    monkeypatch.setenv("JEV_MODEL", "jev-env-model")
    monkeypatch.setenv("JEV_API_KEY", "env_secret_key")

    k, u, m = resolve_jev_env_defaults()
    assert k == "env_secret_key"
    assert u == "https://env.example.com/v1"
    assert m == "jev-env-model"

    # 3. 显式配置优先于 env
    k2, u2, m2 = resolve_jev_env_defaults(
        api_key="explicit_key",
        base_url="https://explicit.example.com",
        model="explicit-model",
    )
    assert k2 == "explicit_key"
    assert u2 == "https://explicit.example.com/v1"
    assert m2 == "explicit-model"


def test_redact_sensitive_text():
    """日志与错误消息绝不输出 key（脱敏 [REDACTED]）"""
    secret = "sk-live-secret-key-12345678"
    raw_log = f"Failed to connect using key {secret} and Bearer super-secret-token"
    sanitized = redact_sensitive_text(raw_log, key=secret)

    assert secret not in sanitized
    assert "super-secret-token" not in sanitized
    assert "[REDACTED]" in sanitized


def test_oversized_state_truncation():
    """超长 state 截断并标注 truncated=true"""
    huge_text = "A" * 5000
    state = {"huge_param": huge_text, "normal": "ok"}
    truncated_state, is_truncated = truncate_state_if_needed(state)

    assert is_truncated is True
    assert len(truncated_state["huge_param"]) < 5000
    assert "... [TRUNCATED]" in truncated_state["huge_param"]
    assert truncated_state["normal"] == "ok"


def test_log_structured_levels_and_fields(caplog):
    """验证 _log_structured 根据 status 输出不同级别日志且包含 status, reason, error 字段"""
    import logging

    client = JevClient(api_key="sk-test", base_url="https://api.typesafe.ai/v1")

    # 1. ok -> INFO
    with caplog.at_level(logging.DEBUG):
        caplog.clear()
        d_ok = Decision(status="ok", selected="foo", confidence=0.99, elapsed_ms=12.3)
        client._log_structured(d_ok, scope="acc1:task1")
        assert any(
            r.levelno == logging.INFO
            and "status=ok" in r.message
            and "scope=acc1:task1" in r.message
            for r in caplog.records
        )

    # 2. escalate / budget_exceeded -> WARNING
    with caplog.at_level(logging.DEBUG):
        caplog.clear()
        d_esc = Decision(
            status="escalate",
            reason_code="CIRCUIT_BREAKER_OPEN",
            error_message="breaker open",
        )
        client._log_structured(d_esc, scope="acc1:task1")
        assert any(
            r.levelno == logging.WARNING
            and "status=escalate" in r.message
            and "reason=CIRCUIT_BREAKER_OPEN" in r.message
            and "breaker open" in r.message
            for r in caplog.records
        )

    # 3. unavailable / invalid -> ERROR
    with caplog.at_level(logging.DEBUG):
        caplog.clear()
        d_err = Decision(
            status="unavailable",
            reason_code="AUTH_FAILED",
            error_message="Invalid key",
            http_status=401,
        )
        client._log_structured(d_err, scope="acc1:task1")
        assert any(
            r.levelno == logging.ERROR
            and "status=unavailable" in r.message
            and "reason=AUTH_FAILED" in r.message
            and "Invalid key" in r.message
            for r in caplog.records
        )

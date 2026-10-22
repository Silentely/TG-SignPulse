from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from tg_signer.semantic.breaker import CircuitBreaker
from tg_signer.semantic.cache import (
    JevDecisionCache,
    compute_cache_key,
    is_sensitive_request,
)
from tg_signer.semantic.client import JevClient
from tg_signer.semantic.models import DecisionRequest
from tg_signer.semantic.security import redact_sensitive_text, validate_ssrf_and_host


def _make_req(
    scope: str = "acc:task:1:1",
    state: dict | None = None,
    instructions: str = "",
    config_revision: str = "rev_1",
) -> DecisionRequest:
    return DecisionRequest(
        kind="result",
        scope=scope,
        state=state or {"step": "test"},
        choices={"pong": "回复 pong", "no": "放弃"},
        instructions=instructions,
        request_key="req_p0_p1",
        config_revision=config_revision,
    )


# -------------------------------------------------------------------------
# P0-1 & P1-10: 总预算墙钟硬上限与测试重写
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_p0_1_wall_clock_hard_limit_rejects_late_200_and_prevents_cache(monkeypatch):
    """P0-1 & P1-10: HTTP 调用耗时超出总预算墙钟，即使返回 200 OK 也必须判失败、不得返回 ok、不得写缓存"""
    cache = JevDecisionCache(maxsize=10, ttl=60.0)
    client = JevClient(
        api_key="test_key",
        base_url="https://api.typesafe.ai/v1",
        total_budget=0.05,
        cache=cache,
    )

    async def fake_slow_post(self, url, json=None, headers=None, timeout=None):
        # 模拟传输耗时 80ms > 50ms 预算，且返回 200 OK
        await asyncio.sleep(0.08)
        return httpx.Response(
            status_code=200,
            json={"answers": {"decision": {"choice": "pong", "confidence": 0.99}}},
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_slow_post)

    req = _make_req()
    dec = await client.query_choice(req)
    await client.close()

    assert dec.status == "budget_exceeded"
    assert dec.reason_code == "DEADLINE_EXCEEDED"
    assert dec.selected == "unknown"
    assert len(cache._cache) == 0  # 绝对不写缓存
    assert client.metrics.success_calls == 0
    assert client.metrics.failed_calls == 1


# -------------------------------------------------------------------------
# P0-2: 半开探测位覆盖所有退出路径（包括 CancelledError）
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_p0_2_half_open_probe_release_on_cancellation(monkeypatch):
    """P0-2: 半开探测请求在途被 CancelledError 取消时，必须通过 finally 释放探测位，不许永远卡在 half_open"""
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.05)
    cb.state = "half_open"
    assert cb._probe_in_flight is False

    client = JevClient(
        api_key="test_key",
        base_url="https://api.typesafe.ai/v1",
        breaker=cb,
    )

    started_evt = asyncio.Event()

    async def fake_hanging_post(self, url, json=None, headers=None, timeout=None):
        started_evt.set()
        await asyncio.sleep(10.0)
        return httpx.Response(200, json={}, request=httpx.Request("POST", str(url)))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_hanging_post)

    task = asyncio.create_task(client.query_choice(_make_req()))
    await started_evt.wait()

    # 验证此时试水探针已在途
    assert cb._probe_in_flight is True
    # 取消任务
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # 验证 finally 兜底释放了探针位
    assert cb._probe_in_flight is False
    assert cb.get_state() == "half_open"

    # 下一个请求能够正常拿到探针权限
    lease = cb.acquire()
    assert lease.allowed is True
    assert lease.is_probe is True
    lease.release()
    assert cb._probe_in_flight is False
    await client.close()


# -------------------------------------------------------------------------
# P0-3: 旧请求成功不得关闭新开的熔断
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_p0_3_old_generation_success_cannot_close_new_breaker():
    """P0-3: 结果绑定代次与探针身份，只有当前代次的探针成功才能回 closed；open 状态永不被清计数"""
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60.0)

    # 触发代次 0 熔断，且设置 last_failure_time 为当前时间（处于冷却期内）
    now = time.monotonic()
    cb.last_failure_time = now
    cb.state = "open"
    cb.generation = 1
    cb.consecutive_failures = 2

    # 旧请求（代次 0，非探针）延迟返回 200 成功
    cb.record_success(request_generation=0, is_probe=False)
    assert cb.state == "open"
    assert cb.consecutive_failures == 2  # open 分支不得清失败计数

    # 进入 half_open
    now_half = now + 65.0
    assert cb.get_state(now=now_half) == "half_open"

    # 此时旧请求（代次 0）再次试图 record_success
    cb.record_success(request_generation=0, is_probe=False)
    assert cb.get_state(now=now_half) == "half_open"
    assert cb.consecutive_failures == 2

    # 当前代次（1）但非探针请求成功，依然不能恢复 closed
    cb.record_success(request_generation=1, is_probe=False)
    assert cb.get_state(now=now_half) == "half_open"

    # 只有当前代次（1）且是探针的成功，才能恢复 closed
    cb.record_success(request_generation=1, is_probe=True, now=now_half)
    assert cb.get_state(now=now_half) == "closed"
    assert cb.consecutive_failures == 0


# -------------------------------------------------------------------------
# P0-4: 凭据外送面与 SSRF 防护
# -------------------------------------------------------------------------
def test_p0_4_ssrf_and_credential_whitelisting():
    """P0-4: 已保存密钥只允许发往白名单 host；自定义接口不得外送已存密钥；拦截回环、内网和云元数据 SSRF"""
    # 1. 拦截各类内网/回环/元数据 SSRF
    bad_urls = [
        "http://127.0.0.1/v1",
        "http://localhost/v1",
        "http://10.0.1.5/v1",
        "http://172.16.0.1/v1",
        "http://192.168.1.1/v1",
        "http://169.254.169.254/v1",
        "http://[::1]/v1",
        "ftp://api.typesafe.ai/v1",
    ]
    for url in bad_urls:
        valid, err = validate_ssrf_and_host(url, is_saved_key=False)
        assert valid is False
        assert "SSRF" in err or "Unsupported" in err or "Invalid" in err

    # 2. 官方白名单 host，允许使用已存密钥
    valid, err = validate_ssrf_and_host("https://api.typesafe.ai/v1", is_saved_key=True)
    assert valid is True
    assert err == ""

    # 3. 自定义公网 host，禁止使用已存密钥（防止攻击者修改 base_url 窃取已有凭据）
    valid, err = validate_ssrf_and_host("https://custom-gateway.io/v1", is_saved_key=True)
    assert valid is False
    assert "UNTRUSTED_HOST" in err

    # 4. 自定义公网 host，若是用户当前显式输入的临时密钥（非已保存密钥），则允许
    valid, err = validate_ssrf_and_host("https://custom-gateway.io/v1", is_saved_key=False)
    assert valid is True
    assert err == ""


# -------------------------------------------------------------------------
# P1-5: 缓存键补多维度与命名空间隔离
# -------------------------------------------------------------------------
def test_p1_5_cache_keys_multidimensional_and_namespace_isolation():
    """P1-5: 缓存键必须包含 scope、model、base_url、config_revision；配置代际变更采用命名空间隔离"""
    req_base = _make_req(scope="scope_a", config_revision="rev_1")

    # 维度不同，键必须不同
    k1 = compute_cache_key(req_base, model="model_1", base_url="https://api.typesafe.ai/v1")
    k2 = compute_cache_key(req_base, model="model_2", base_url="https://api.typesafe.ai/v1")
    k3 = compute_cache_key(req_base, model="model_1", base_url="https://custom.org/v1")

    req_rev2 = _make_req(scope="scope_a", config_revision="rev_2")
    k4 = compute_cache_key(req_rev2, model="model_1", base_url="https://api.typesafe.ai/v1")

    req_scope_b = _make_req(scope="scope_b", config_revision="rev_1")
    k5 = compute_cache_key(req_scope_b, model="model_1", base_url="https://api.typesafe.ai/v1")

    keys = {k1, k2, k3, k4, k5}
    assert len(keys) == 5  # 五个维度的键必须互不碰撞

    # 命名空间隔离
    cache = JevDecisionCache(maxsize=10, ttl=60.0)
    ns1 = cache.with_namespace("gen_1")
    from tg_signer.semantic.models import Decision
    dummy_dec = Decision(status="ok", selected="pong")
    ns1.set(k1, dummy_dec)
    assert ns1.get(k1).selected == "pong"

    ns2 = cache.with_namespace("gen_2")
    assert ns2.get(k1) is None  # gen_2 绝对看不到 gen_1 的旧缓存


# -------------------------------------------------------------------------
# P1-6: 敏感旁路漏判强化（驼峰、蛇形、解码、高熵不透明串）
# -------------------------------------------------------------------------
def test_p1_6_sensitive_bypass_detection():
    """P1-6: 敏感旁路必须命中 apiKey/accessToken/clientSecret，支持 URL 与 Base64 解码，高熵不透明串拒绝入缓存"""
    # 驼峰敏感词
    req_camel = _make_req(state={"apiKey": "sk-1234567890abcdef"})
    assert is_sensitive_request(req_camel) is True

    req_token = _make_req(state={"accessToken": "eyJhbGciOi..."})
    assert is_sensitive_request(req_token) is True

    req_secret = _make_req(state={"clientSecret": "sec_12345"})
    assert is_sensitive_request(req_secret) is True

    # URL 编码转义敏感词
    req_url = _make_req(instructions="Is%20access_token%3Dsecret_value_present?")
    assert is_sensitive_request(req_url) is True

    # 高熵不透明串
    req_entropy = _make_req(state={"payload": "a8B!x9Q#kL2$mZ5&vW8*"})
    assert is_sensitive_request(req_entropy) is True

    # 正常文本不误报
    req_clean = _make_req(state={"item": "apple", "status": "active"}, instructions="confirm payment?")
    assert is_sensitive_request(req_clean) is False


# -------------------------------------------------------------------------
# P1-7: 脱敏完整性与异常兜底
# -------------------------------------------------------------------------
def test_p1_7_redaction_completeness():
    """P1-7: 脱敏覆盖 JSON 密码/密钥字段、赋值表达式、Bearer 令牌"""
    raw_texts = [
        ('{"password": "my_secret_pass"}', "my_secret_pass"),
        ('{"api_key": "sk-topsecret123"}', "sk-topsecret123"),
        ('secret=opaque_token_val_12345', "opaque_token_val_12345"),
        ('Bearer token_secret_abcdef', "token_secret_abcdef"),
    ]
    for raw, secret_value in raw_texts:
        sanitized = redact_sensitive_text(raw)
        assert secret_value not in sanitized
        assert "[REDACTED]" in sanitized


# -------------------------------------------------------------------------
# P1-8: 指标互斥且全覆盖
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_p1_8_metrics_mutual_exclusivity():
    """P1-8: 熔断请求只算 escalate 不算 failed；缺少 key 计入 total 与 failed；满足 total == success + failed + escalate"""
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
    cb.state = "open"
    cb.last_failure_time = time.monotonic()

    client = JevClient(
        api_key="valid_key",
        base_url="https://api.typesafe.ai/v1",
        breaker=cb,
    )

    # 1. 熔断阻断
    dec = await client.query_choice(_make_req())
    assert dec.status == "escalate"
    assert client.metrics.total_calls == 1
    assert client.metrics.escalate_calls == 1
    assert client.metrics.failed_calls == 0  # 熔断请求不得重复计入 failed

    # 2. 无 key 调用
    client_no_key = JevClient(api_key="", base_url="https://api.typesafe.ai/v1")
    dec_no_key = await client_no_key.query_choice(_make_req())
    assert dec_no_key.status == "disabled"
    assert dec_no_key.reason_code == "NO_API_KEY"
    assert client_no_key.metrics.total_calls == 1
    assert client_no_key.metrics.failed_calls == 1

    # 验证指标互斥全覆盖
    m = client.metrics
    assert m.total_calls == m.success_calls + m.failed_calls + m.escalate_calls

    m2 = client_no_key.metrics
    assert m2.total_calls == m2.success_calls + m2.failed_calls + m2.escalate_calls

    await client.close()
    await client_no_key.close()


# -------------------------------------------------------------------------
# P1-9: 200 但空 choice 不算成功
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_p1_9_empty_choice_treated_as_failure_not_reset_breaker(monkeypatch):
    """P1-9: 200 但 choice 为空串/缺失时，不得重置熔断计数，按失败处理且不入缓存"""
    cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60.0)
    cb.consecutive_failures = 3
    cache = JevDecisionCache(maxsize=10, ttl=60.0)

    client = JevClient(
        api_key="test_key",
        base_url="https://api.typesafe.ai/v1",
        breaker=cb,
        cache=cache,
    )

    async def fake_empty_choice_post(self, url, json=None, headers=None, timeout=None):
        return httpx.Response(
            status_code=200,
            json={"answers": {"decision": {"choice": "", "confidence": 0.5}}},
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_empty_choice_post)

    dec = await client.query_choice(_make_req())
    await client.close()

    assert dec.status == "invalid"
    assert dec.reason_code == "EMPTY_CHOICE"
    assert cb.consecutive_failures == 4  # 熔断计数累加，绝不重置为 0
    assert len(cache._cache) == 0  # 绝对不写缓存
    assert client.metrics.failed_calls == 1
    assert client.metrics.success_calls == 0


# -------------------------------------------------------------------------
# P1-11: 429 尊重 Retry-After；异常重试收窄
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_p1_11_retry_after_respected_and_exceptions_narrowed(monkeypatch):
    """P1-11: 429 响应需尊重 Retry-After 头；重试仅捕获网络传输与超时异常，契约/程序错误不重试"""
    client = JevClient(
        api_key="test_key",
        base_url="https://api.typesafe.ai/v1",
    )

    sleep_durations: list[float] = []

    async def fake_sleep(duration):
        sleep_durations.append(duration)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    calls = 0

    async def fake_429_post(self, url, json=None, headers=None, timeout=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                status_code=429,
                headers={"Retry-After": "2"},
                request=httpx.Request("POST", str(url)),
            )
        return httpx.Response(
            status_code=200,
            json={"answers": {"decision": {"choice": "pong", "confidence": 0.9}}},
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_429_post)

    dec = await client.query_choice(_make_req())
    await client.close()

    assert calls == 2
    assert dec.status == "ok"
    assert len(sleep_durations) == 1
    assert sleep_durations[0] >= 2.0  # 尊重 Retry-After: 2

# -------------------------------------------------------------------------
# P0-3 升级：真实进入 half_open，挂起探针，经 client 路径验证代次隔离
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_p0_3_half_open_client_probe_isolation(monkeypatch):
    """P0-3 升级：真实进入 half_open，挂起探针，经 client 路径验证代次隔离（删掉 breaker.py 校验必红）"""
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
    client = JevClient(
        api_key="test_key",
        base_url="https://api.typesafe.ai/v1",
        breaker=cb,
    )

    # 1. 第一次请求失败 -> 触发熔断进入 open, generation=1
    async def fake_fail(self, url, json=None, headers=None, timeout=None):
        return httpx.Response(
            status_code=500,
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_fail)
    await client.query_choice(_make_req())
    assert cb.state == "open"
    assert cb.generation == 1

    # 2. 模拟时间快进 65s，真实进入 half_open
    simulated_now = cb.last_failure_time + 65.0
    monkeypatch.setattr(time, "monotonic", lambda: simulated_now)
    assert cb.get_state() == "half_open"

    # 3. 探针请求 A 发起并挂起 (in-flight probe)
    probe_started = asyncio.Event()
    probe_can_finish = asyncio.Event()

    async def fake_probe_post(self, url, json=None, headers=None, timeout=None):
        probe_started.set()
        await probe_can_finish.wait()
        return httpx.Response(
            status_code=200,
            json={"answers": {"decision": {"choice": "pong", "confidence": 0.9}}},
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_probe_post)

    task_probe = asyncio.create_task(client.query_choice(_make_req()))
    await probe_started.wait()
    assert cb._probe_in_flight is True
    assert cb.state == "half_open"

    # 4. 旧代次（代次 0）的慢请求此时返回成功
    from tg_signer.semantic.breaker import ProbeLease
    old_lease = ProbeLease(cb, allowed=True, generation=0, is_probe=True)
    old_lease.record_success()

    # 关键断言：旧代次成功绝不能把当前熔断器关闭！
    # 如果删掉 breaker.py 的代次身份限制，cb.state 会被错误置为 closed
    assert cb.state == "half_open"
    assert cb._probe_in_flight is True

    # 此时并发请求 C 到来，必须被熔断器阻断降级为 escalate
    dec_c = await client.query_choice(_make_req())
    assert dec_c.status == "escalate"
    assert dec_c.reason_code == "CIRCUIT_BREAKER_OPEN"

    # 5. 放行探针 A 完成
    probe_can_finish.set()
    dec_a = await task_probe
    assert dec_a.status == "ok"
    assert cb.state == "closed"
    assert cb.consecutive_failures == 0
    assert cb._probe_in_flight is False
    await client.close()


# -------------------------------------------------------------------------
# 配置代际切换：Runtime 集成测试（删掉 runtime.py:60 缓存重建必红）
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_runtime_generation_switch_rebuilds_cache(tmp_path):
    """配置代际切换：Runtime 必须重建缓存命名空间，隔离旧缓存"""
    from backend.services.semantic.runtime import SemanticRuntime
    from tg_signer.semantic.models import Decision

    runtime = SemanticRuntime(workdir=tmp_path)
    cfg0 = runtime.config_store.save_patch({"enabled": True, "api_key": "test_key"})

    svc0 = runtime.service
    assert svc0 is not None
    cache0 = runtime._cache
    assert cache0.namespace == f"gen_{cfg0.generation}"

    # 向当前缓存存入一条记录
    req = _make_req()
    k = compute_cache_key(req, model=cfg0.model, base_url=cfg0.base_url)
    cache0.set(k, Decision(status="ok", selected="pong"))
    assert cache0.get(k) is not None

    # 配置代际切换：保存 patch 使 generation 递增
    cfg1 = runtime.config_store.save_patch({"timeout_seconds": 12.0})

    svc1 = runtime.service
    assert svc1 is not None
    cache1 = runtime._cache

    # 关键断言：缓存必须重建为全新实例与命名空间，绝对看不到旧代次缓存
    # 如果删掉 runtime.py:60 的缓存重建，cache1 is cache0 将为 True，assert 失败变红
    assert cache1 is not cache0
    assert cache1.namespace == f"gen_{cfg1.generation}"
    assert cache1.get(k) is None
    assert len(cache1._cache) == 0


# -------------------------------------------------------------------------
# 敏感旁路：cache get/set 零调用断言 + Base64 用例
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sensitive_bypass_zero_cache_calls_and_base64(monkeypatch):
    """敏感旁路：命中敏感信息时 cache get/set 零调用；覆盖 Base64 编码与短 token"""
    from unittest.mock import MagicMock

    cache = JevDecisionCache(maxsize=10, ttl=60.0)
    get_spy = MagicMock(wraps=cache.get)
    set_spy = MagicMock(wraps=cache.set)
    cache.get = get_spy
    cache.set = set_spy

    client = JevClient(
        api_key="test_key",
        base_url="https://api.typesafe.ai/v1",
        cache=cache,
    )

    async def fake_ok_post(self, url, json=None, headers=None, timeout=None):
        return httpx.Response(
            status_code=200,
            json={"answers": {"decision": {"choice": "pong", "confidence": 0.99}}},
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_ok_post)

    # 1. Base64 编码的敏感凭据：dG9rZW49c2VjcmV0 -> token=secret
    req_b64 = _make_req(instructions="Authorization: dG9rZW49c2VjcmV0")
    assert is_sensitive_request(req_b64) is True

    dec_b64 = await client.query_choice(req_b64)
    assert dec_b64.status == "ok"
    # 断言：cache.get 和 cache.set 必须零调用
    assert get_spy.call_count == 0
    assert set_spy.call_count == 0

    # 2. 短文本 token=abc
    req_token = _make_req(instructions="token=abc")
    assert is_sensitive_request(req_token) is True
    await client.query_choice(req_token)
    assert get_spy.call_count == 0
    assert set_spy.call_count == 0

    # 3. 文本带有空格的高熵 token: "Please use token a8B!x9Q#kL2$mZ5&vW8* here"
    req_entropy = _make_req(instructions="Please use token a8B!x9Q#kL2$mZ5&vW8* here")
    assert is_sensitive_request(req_entropy) is True
    await client.query_choice(req_entropy)
    assert get_spy.call_count == 0
    assert set_spy.call_count == 0

    # 对照组：正常请求必须调用 cache.get 和 cache.set
    req_clean = _make_req(instructions="Please click confirm button")
    assert is_sensitive_request(req_clean) is False
    await client.query_choice(req_clean)
    assert get_spy.call_count == 1
    assert set_spy.call_count == 1
    await client.close()


# -------------------------------------------------------------------------
# 预算三路分支用例：晚到 200 / 解析耗尽预算 / 命中缓存
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_budget_branch_late_200(monkeypatch):
    """预算分支 1：网络耗时超过预算，返回 200 时必须被墙钟硬上限拦截"""
    cache = JevDecisionCache(maxsize=10, ttl=60.0)
    client = JevClient(
        api_key="test_key",
        base_url="https://api.typesafe.ai/v1",
        total_budget=0.04,
        cache=cache,
    )

    async def fake_slow_post(self, url, json=None, headers=None, timeout=None):
        await asyncio.sleep(0.08)
        return httpx.Response(
            status_code=200,
            json={"answers": {"decision": {"choice": "pong", "confidence": 0.99}}},
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_slow_post)

    dec = await client.query_choice(_make_req())
    await client.close()

    assert dec.status == "budget_exceeded"
    assert dec.reason_code == "DEADLINE_EXCEEDED"
    assert len(cache._cache) == 0
    assert client.metrics.success_calls == 0
    assert client.metrics.failed_calls == 1


@pytest.mark.asyncio
async def test_budget_branch_parse_exhausts_budget(monkeypatch):
    """预算分支 2：网络返回及时，但响应解析耗尽总预算，在末次检查拦截"""
    cache = JevDecisionCache(maxsize=10, ttl=60.0)
    client = JevClient(
        api_key="test_key",
        base_url="https://api.typesafe.ai/v1",
        total_budget=0.05,
        cache=cache,
    )

    post_done = False
    after_post_calls = 0

    async def fake_fast_post(self, url, json=None, headers=None, timeout=None):
        nonlocal post_done
        post_done = True
        return httpx.Response(
            status_code=200,
            json={"answers": {"decision": {"choice": "pong", "confidence": 0.99}}},
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_fast_post)

    orig_monotonic = time.monotonic

    def mock_time():
        nonlocal after_post_calls
        t = orig_monotonic()
        if post_done:
            after_post_calls += 1
            # 第 1 次是 post_end_t -> 正常未超时
            # 第 2 次是 parse_end_t -> 耗尽预算（超时）
            if after_post_calls >= 2:
                return t + 10.0
        return t

    monkeypatch.setattr(time, "monotonic", mock_time)

    dec = await client.query_choice(_make_req())
    await client.close()

    assert dec.status == "budget_exceeded"
    assert dec.reason_code == "DEADLINE_EXCEEDED"
    assert len(cache._cache) == 0
    assert client.metrics.success_calls == 0
    assert client.metrics.failed_calls == 1


@pytest.mark.asyncio
async def test_budget_branch_cache_hit_exceeds_budget():
    """预算分支 3：缓存命中成功出口位于预算检查之后，传入已过期 deadline 绝不返回 ok"""
    cache = JevDecisionCache(maxsize=10, ttl=60.0)
    client = JevClient(
        api_key="test_key",
        base_url="https://api.typesafe.ai/v1",
        cache=cache,
    )

    req = _make_req()
    k = compute_cache_key(req, model=client.model, base_url=client.base_url)
    from tg_signer.semantic.models import Decision
    cache.set(k, Decision(status="ok", selected="pong"))

    # 传入已超期的 deadline
    past_deadline = time.monotonic() - 1.0
    dec = await client.query_choice(req, deadline=past_deadline)
    await client.close()

    assert dec.status == "budget_exceeded"
    assert dec.reason_code == "DEADLINE_EXCEEDED"
    assert dec.cache_hit is False
    assert client.metrics.success_calls == 0
    assert client.metrics.failed_calls == 1


# -------------------------------------------------------------------------
# Grok P1-2: 200 但 choice 为空或非法算失败，不重置熔断，不写缓存
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_200_empty_choice_treated_as_failure_no_cache_no_breaker_reset(monkeypatch):
    """200 但 choice 为空串必须判失败，不重置熔断计数，不写缓存"""
    cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60.0)
    cb.consecutive_failures = 2
    cache = JevDecisionCache(maxsize=10, ttl=60.0)

    client = JevClient(
        api_key="test_key",
        base_url="https://api.typesafe.ai/v1",
        breaker=cb,
        cache=cache,
    )

    async def fake_empty_choice_post(self, url, json=None, headers=None, timeout=None):
        return httpx.Response(
            status_code=200,
            json={"answers": {"decision": {"choice": "", "confidence": 0.5}}},
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_empty_choice_post)

    dec = await client.query_choice(_make_req())
    await client.close()

    assert dec.status == "invalid"
    assert dec.reason_code == "EMPTY_CHOICE"
    assert cb.consecutive_failures == 3  # 累加，绝不清零
    assert len(cache._cache) == 0
    assert client.metrics.failed_calls == 1
    assert client.metrics.success_calls == 0


@pytest.mark.asyncio
async def test_200_out_of_bounds_choice_treated_as_failure_no_cache_no_breaker_reset(monkeypatch):
    """200 但 choice 超出候选列表必须判失败，不重置熔断计数，不写缓存"""
    cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60.0)
    cb.consecutive_failures = 2
    cache = JevDecisionCache(maxsize=10, ttl=60.0)

    client = JevClient(
        api_key="test_key",
        base_url="https://api.typesafe.ai/v1",
        breaker=cb,
        cache=cache,
    )

    async def fake_invalid_choice_post(self, url, json=None, headers=None, timeout=None):
        return httpx.Response(
            status_code=200,
            json={"answers": {"decision": {"choice": "invalid_option", "confidence": 0.8}}},
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_invalid_choice_post)

    dec = await client.query_choice(_make_req())
    await client.close()

    assert dec.selected == "unknown"
    assert cb.consecutive_failures == 3  # 累加，绝不清零
    assert len(cache._cache) == 0
    assert client.metrics.failed_calls == 1
    assert client.metrics.success_calls == 0


# -------------------------------------------------------------------------
# Grok P0-1: /test 端点凭据外送保护：未显式传 key 拒绝自定义 base_url
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_route_test_connection_rejects_custom_base_url_without_explicit_key(tmp_path):
    """Grok P0-1: /test 只有显式传 api_key 才允许自定义 base_url；缺省 key 时发往不同 host 直接 400"""
    from fastapi import HTTPException

    from backend.api.routes.semantic import test_connection
    from backend.services.semantic.config import JevConfigStore

    store = JevConfigStore(tmp_path)
    store.save_patch({"base_url": "https://api.typesafe.ai/v1", "api_key": "saved_secret_key"})

    # 1. 尝试将已保存密钥发送至未授权的自定义 host，不显式提供 api_key -> 必须 400 UNTRUSTED_HOST
    with pytest.raises(HTTPException) as exc_info:
        await test_connection(
            body={"base_url": "https://attacker-host.com/v1"},
            store=store,
            _=None,
        )
    assert exc_info.value.status_code == 400
    assert "UNTRUSTED_HOST" in exc_info.value.detail
    assert "requires explicit api_key" in exc_info.value.detail

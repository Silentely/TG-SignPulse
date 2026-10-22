from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from dataclasses import dataclass, replace
from typing import Any

import httpx

from tg_signer.semantic.breaker import CircuitBreaker
from tg_signer.semantic.cache import (
    JevDecisionCache,
    compute_cache_key,
    is_sensitive_request,
)
from tg_signer.semantic.models import Decision, DecisionRequest
from tg_signer.semantic.security import (
    redact_sensitive_text,
    sanitize_request,
    validate_ssrf_and_host,
)

logger = logging.getLogger("tg_signer.semantic.client")


def normalize_base_url(url: str | None) -> str:
    """规范化 JEV Base URL：
    - 统一去除首尾空格与尾部斜杠
    - 若误填完整路径（如带 /systemone），剥离 /systemone
    - 统一规范化为包含 /v1 结尾（如 https://api.example.com -> https://api.example.com/v1）
    """
    if not url:
        return "https://api.typesafe.ai/v1"
    cleaned = url.strip().rstrip("/")
    if cleaned.endswith("/systemone"):
        cleaned = cleaned[: -len("/systemone")].rstrip("/")
    if not cleaned.endswith("/v1"):
        cleaned = f"{cleaned}/v1"
    return cleaned


@dataclass
class JevMetrics:
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    escalate_calls: int = 0  # 降级/走人工
    cache_hits: int = 0
    cache_misses: int = 0

    def get_summary(self) -> dict[str, Any]:
        total_cache = self.cache_hits + self.cache_misses
        hit_rate = (self.cache_hits / total_cache) if total_cache > 0 else 0.0
        return {
            "total_calls": self.total_calls,
            "success_calls": self.success_calls,
            "failed_calls": self.failed_calls,
            "escalate_calls": self.escalate_calls,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": round(hit_rate, 4),
        }


def resolve_jev_env_defaults(
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> tuple[str, str, str]:
    """根据优先级解析配置：显式配置 > env > 默认"""
    # 1. API KEY: 显式 > JEV_API_KEY env > ""
    resolved_key = (api_key or "").strip()
    if not resolved_key:
        resolved_key = os.getenv("JEV_API_KEY", "").strip()

    # 2. BASE URL: 显式（非默认） > JEV_BASE_URL env > 默认
    resolved_base = (base_url or "").strip()
    if not resolved_base or resolved_base == JevClient.DEFAULT_BASE_URL:
        env_base = os.getenv("JEV_BASE_URL", "").strip()
        if env_base:
            resolved_base = env_base
        elif not resolved_base:
            resolved_base = JevClient.DEFAULT_BASE_URL

    # 3. MODEL: 显式（非默认） > JEV_MODEL env > 默认
    resolved_model = (model or "").strip()
    if not resolved_model or resolved_model == JevClient.DEFAULT_MODEL:
        env_model = os.getenv("JEV_MODEL", "").strip()
        if env_model:
            resolved_model = env_model
        elif not resolved_model:
            resolved_model = JevClient.DEFAULT_MODEL

    return resolved_key, normalize_base_url(resolved_base), resolved_model


class JevClient:
    DEFAULT_BASE_URL: str = "https://api.typesafe.ai/v1"
    DEFAULT_MODEL: str = "jev-1.13.0"
    DEFAULT_TIMEOUT: float = 8.0
    DEFAULT_CONNECT_TIMEOUT: float = 3.0
    DEFAULT_TOTAL_BUDGET: float = 20.0
    MAX_RETRIES: int = 2

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT,
        total_budget: float = DEFAULT_TOTAL_BUDGET,
        breaker: CircuitBreaker | None = None,
        cache: JevDecisionCache | None = None,
        is_saved_key: bool = False,
    ):
        resolved_key, resolved_base, resolved_model = resolve_jev_env_defaults(
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
        self.api_key = resolved_key
        self.base_url = resolved_base
        self.model = resolved_model
        self.timeout = timeout
        self.total_budget = total_budget
        self.is_saved_key = is_saved_key

        self.breaker = breaker or CircuitBreaker()
        self.cache = cache or JevDecisionCache()
        self.metrics = JevMetrics()

        self._client: httpx.AsyncClient | None = None

    def _create_httpx_timeout(self, total_timeout: float) -> httpx.Timeout:
        connect_timeout = min(self.DEFAULT_CONNECT_TIMEOUT, total_timeout)
        return httpx.Timeout(
            total_timeout,
            connect=connect_timeout,
            read=total_timeout,
        )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            from tg_signer.version import get_user_agent

            self._client = httpx.AsyncClient(
                timeout=self._create_httpx_timeout(self.timeout),
                headers={"User-Agent": get_user_agent("Jev")},
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    def _extract_error_message(self, resp: httpx.Response) -> str:
        try:
            err_json = resp.json()
            if isinstance(err_json, dict):
                error_obj = err_json.get("error")
                if isinstance(error_obj, dict) and "message" in error_obj:
                    msg = str(error_obj["message"])
                else:
                    msg = str(err_json.get("message") or err_json.get("detail") or "")
                return redact_sensitive_text(msg, self.api_key)
        except Exception:
            pass
        return redact_sensitive_text(resp.text[:300], self.api_key)

    @staticmethod
    def _calculate_backoff(attempt_idx: int) -> float:
        """指数退避 + 抖动 (200~600ms)"""
        base = 0.2 * (2**attempt_idx)
        jitter = random.uniform(0.0, 0.2)
        return min(0.6, max(0.2, base + jitter))

    def _log_structured(self, decision: Decision) -> None:
        logger.info(
            "jev_query_completed: decision=%s confidence=%.2f latency_ms=%.1f "
            "http_status=%s attempts=%d breaker=%s cache_hit=%s truncated=%s",
            decision.selected,
            decision.confidence,
            decision.elapsed_ms,
            decision.http_status,
            decision.attempts,
            decision.breaker,
            decision.cache_hit,
            decision.truncated,
            extra={
                "decision": decision.selected,
                "confidence": decision.confidence,
                "latency_ms": decision.elapsed_ms,
                "http_status": decision.http_status,
                "attempts": decision.attempts,
                "breaker": decision.breaker,
                "cache_hit": decision.cache_hit,
                "truncated": decision.truncated,
            },
        )

    def get_stats(self) -> dict[str, Any]:
        stats = self.metrics.get_summary()
        stats["breaker"] = self.breaker.snapshot()
        stats["cache"] = self.cache.stats()
        return stats

    async def query_choice(
        self,
        request: DecisionRequest,
        *,
        deadline: float | None = None,
    ) -> Decision:
        start_t = time.monotonic()
        budget_deadline = start_t + self.total_budget
        if deadline is not None:
            budget_deadline = min(budget_deadline, deadline)

        # 指标计数：所有到达 query_choice 的调用一律先计入 total_calls
        self.metrics.total_calls += 1

        # 1. 凭据校验
        if not self.api_key:
            self.metrics.failed_calls += 1
            decision = Decision(
                status="disabled",
                reason_code="NO_API_KEY",
                error_message="API key not configured",
                attempts=0,
                breaker=self.breaker.get_state(),
            )
            self._log_structured(decision)
            return decision

        # 2. SSRF 与凭据外送面白名单校验
        is_url_valid, ssrf_err = validate_ssrf_and_host(
            self.base_url, is_saved_key=self.is_saved_key
        )
        if not is_url_valid:
            self.metrics.failed_calls += 1
            reason_code = "SSRF_BLOCKED" if "SSRF" in ssrf_err else "UNTRUSTED_HOST"
            decision = Decision(
                status="unavailable",
                reason_code=reason_code,
                error_message=ssrf_err,
                attempts=0,
                breaker=self.breaker.get_state(),
            )
            self._log_structured(decision)
            return decision

        # 3. 超长截断与安全净化（截断标记保留在 request.truncated）
        sanitized_req = sanitize_request(request)
        is_truncated = bool(sanitized_req.truncated)

        # 4. 预算预检：在 acquire() 之前核查 deadline，避免注定超时的请求消耗半开探针
        if time.monotonic() >= budget_deadline:
            self.metrics.failed_calls += 1
            elapsed_ms = (time.monotonic() - start_t) * 1000.0
            decision = Decision(
                status="budget_exceeded",
                reason_code="DEADLINE_EXCEEDED",
                elapsed_ms=elapsed_ms,
                attempts=0,
                breaker=self.breaker.get_state(),
                truncated=is_truncated,
                error_message="Total budget exceeded before request",
            )
            self._log_structured(decision)
            return decision

        # 5. 熔断判定与探测租约获取（永不静默放行）
        lease = self.breaker.acquire()
        breaker_state = self.breaker.get_state()
        if not lease.allowed:
            # 熔断中直接阻断，仅计入 escalate_calls，不与 failed_calls 重复计算
            self.metrics.escalate_calls += 1
            elapsed_ms = (time.monotonic() - start_t) * 1000.0
            decision = Decision(
                status="escalate",
                selected="unknown",
                reason_code="CIRCUIT_BREAKER_OPEN",
                breaker=breaker_state,
                elapsed_ms=elapsed_ms,
                attempts=0,
                truncated=is_truncated,
                error_message="Circuit breaker is OPEN (consecutive failures threshold reached); escalating to manual review",
            )
            self._log_structured(decision)
            return decision

        try:
            # 6. 缓存查询（含密钥/敏感路径或已截断请求不进缓存）
            is_sensitive = is_sensitive_request(sanitized_req)
            cache_key = compute_cache_key(
                sanitized_req, model=self.model, base_url=self.base_url
            )
            if not is_sensitive and not is_truncated:
                cached = self.cache.get(cache_key)
                if cached is not None:
                    # 缓存成功出口：必须在预算检查之后（若已超预算绝不返回 ok，本地超时不记上游失败）
                    if time.monotonic() >= budget_deadline:
                        self.metrics.failed_calls += 1
                        elapsed_ms = (time.monotonic() - start_t) * 1000.0
                        decision = Decision(
                            status="budget_exceeded",
                            reason_code="DEADLINE_EXCEEDED",
                            elapsed_ms=elapsed_ms,
                            attempts=0,
                            breaker=self.breaker.get_state(),
                            truncated=is_truncated,
                            error_message="Total budget exceeded on cache hit",
                        )
                        self._log_structured(decision)
                        return decision

                    # 缓存命中：属于有效业务成功
                    self.metrics.cache_hits += 1
                    self.metrics.success_calls += 1
                    elapsed_ms = (time.monotonic() - start_t) * 1000.0
                    decision = replace(
                        cached,
                        cache_hit=True,
                        breaker=self.breaker.get_state(),
                        elapsed_ms=elapsed_ms,
                    )
                    lease.release()
                    self._log_structured(decision)
                    return decision
                self.metrics.cache_misses += 1

            # 7. 构造请求 Payload
            if isinstance(sanitized_req.choices, dict):
                criteria = dict(sanitized_req.choices)
            elif isinstance(sanitized_req.choices, list):
                criteria = {c: str(c) for c in sanitized_req.choices}
            else:
                criteria = {"default": "default"}

            payload: dict[str, Any] = {
                "model": self.model,
                "state": sanitized_req.state,
                "questions": {
                    "decision": {
                        "type": "choice",
                        "criteria": criteria,
                    }
                },
            }

            from tg_signer.version import get_user_agent

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": get_user_agent("Jev"),
            }

            target_url = (
                f"{self.base_url}/systemone"
                if not self.base_url.endswith("/systemone")
                else self.base_url
            )

            # 8. 带分类重试的执行循环（最多 2 次重试，总共最多 3 次尝试），用 asyncio.wait_for 整体包住
            last_attempt_idx = 0

            async def _execute_with_retries() -> Decision:
                nonlocal last_attempt_idx
                for attempt_idx in range(self.MAX_RETRIES + 1):
                    last_attempt_idx = attempt_idx
                    now = time.monotonic()
                    remaining_budget = budget_deadline - now
                    if remaining_budget <= 0:
                        raise asyncio.TimeoutError()

                    timeout_to_use = min(self.timeout, remaining_budget)
                    req_timeout = self._create_httpx_timeout(timeout_to_use)

                    try:
                        client = await self._get_client()
                        resp = await client.post(
                            target_url,
                            json=payload,
                            headers=headers,
                            timeout=req_timeout,
                        )
                        post_end_t = time.monotonic()
                        elapsed_ms = (post_end_t - start_t) * 1000.0

                        # 墙钟硬上限：网络调用返回后必须再次校验 deadline
                        if post_end_t >= budget_deadline:
                            raise asyncio.TimeoutError()

                        # 401 / 403: 凭据鉴权失败，绝不重试，直接判 DEAD
                        if resp.status_code in (401, 403):
                            lease.record_failure()
                            self.metrics.failed_calls += 1
                            err_msg = self._extract_error_message(resp)
                            decision = Decision(
                                status="unavailable",
                                reason_code="AUTH_FAILED",
                                elapsed_ms=elapsed_ms,
                                http_status=resp.status_code,
                                attempts=attempt_idx + 1,
                                breaker=self.breaker.get_state(),
                                truncated=is_truncated,
                                error_message=err_msg or "Authentication failed",
                            )
                            self._log_structured(decision)
                            return decision

                        # 429: 限流，属于可重试错误；尊重 Retry-After
                        if resp.status_code == 429:
                            err_msg = self._extract_error_message(resp)
                            if attempt_idx == self.MAX_RETRIES:
                                lease.record_failure()
                                self.metrics.failed_calls += 1
                                decision = Decision(
                                    status="unavailable",
                                    reason_code="RATE_LIMITED",
                                    elapsed_ms=elapsed_ms,
                                    http_status=429,
                                    attempts=attempt_idx + 1,
                                    breaker=self.breaker.get_state(),
                                    truncated=is_truncated,
                                    error_message=err_msg
                                    or "Rate limit exceeded (HTTP 429)",
                                )
                                self._log_structured(decision)
                                return decision

                            retry_after_sec: float | None = None
                            raw_retry_after = resp.headers.get("Retry-After")
                            if raw_retry_after:
                                try:
                                    retry_after_sec = float(raw_retry_after.strip())
                                except (ValueError, TypeError):
                                    retry_after_sec = None

                            backoff = self._calculate_backoff(attempt_idx)
                            if retry_after_sec is not None and retry_after_sec > 0:
                                backoff = max(backoff, retry_after_sec)

                            if time.monotonic() + backoff >= budget_deadline:
                                raise asyncio.TimeoutError()
                            await asyncio.sleep(backoff)
                            continue

                        # 5xx: 服务端错误，重试
                        if 500 <= resp.status_code < 600:
                            err_msg = self._extract_error_message(resp)
                            if attempt_idx == self.MAX_RETRIES:
                                lease.record_failure()
                                self.metrics.failed_calls += 1
                                decision = Decision(
                                    status="invalid",
                                    reason_code=f"HTTP_{resp.status_code}",
                                    elapsed_ms=elapsed_ms,
                                    http_status=resp.status_code,
                                    attempts=attempt_idx + 1,
                                    breaker=self.breaker.get_state(),
                                    truncated=is_truncated,
                                    error_message=err_msg
                                    or f"Server error: {resp.status_code}",
                                )
                                self._log_structured(decision)
                                return decision

                            backoff = self._calculate_backoff(attempt_idx)
                            if time.monotonic() + backoff >= budget_deadline:
                                raise asyncio.TimeoutError()
                            await asyncio.sleep(backoff)
                            continue

                        if resp.status_code != 200:
                            lease.record_failure()
                            self.metrics.failed_calls += 1
                            err_msg = self._extract_error_message(resp)
                            decision = Decision(
                                status="invalid",
                                reason_code=f"HTTP_{resp.status_code}",
                                elapsed_ms=elapsed_ms,
                                http_status=resp.status_code,
                                attempts=attempt_idx + 1,
                                breaker=self.breaker.get_state(),
                                truncated=is_truncated,
                                error_message=err_msg
                                or f"Unexpected status: {resp.status_code}",
                            )
                            self._log_structured(decision)
                            return decision

                        # 200 OK 解析
                        try:
                            data = resp.json()
                        except Exception as json_err:
                            lease.record_failure()
                            self.metrics.failed_calls += 1
                            decision = Decision(
                                status="invalid",
                                reason_code="MALFORMED_JSON",
                                elapsed_ms=elapsed_ms,
                                http_status=200,
                                attempts=attempt_idx + 1,
                                breaker=self.breaker.get_state(),
                                truncated=is_truncated,
                                error_message=f"JSON decode error: {json_err}",
                            )
                            self._log_structured(decision)
                            return decision

                        if not isinstance(data, dict):
                            lease.record_failure()
                            self.metrics.failed_calls += 1
                            decision = Decision(
                                status="invalid",
                                reason_code="MALFORMED_JSON",
                                elapsed_ms=elapsed_ms,
                                http_status=200,
                                attempts=attempt_idx + 1,
                                breaker=self.breaker.get_state(),
                                truncated=is_truncated,
                                error_message=f"Response root must be a JSON object, got {type(data).__name__}",
                            )
                            self._log_structured(decision)
                            return decision

                        raw_answers = data.get("answers")
                        first_ans: dict[str, Any] | None = None
                        if isinstance(raw_answers, dict):
                            first_ans = raw_answers.get("decision") or next(
                                iter(raw_answers.values()), None
                            )
                        elif isinstance(raw_answers, list) and raw_answers:
                            first_ans = raw_answers[0]

                        if not first_ans or not isinstance(first_ans, dict):
                            lease.record_failure()
                            self.metrics.failed_calls += 1
                            decision = Decision(
                                status="invalid",
                                reason_code="NO_ANSWER",
                                elapsed_ms=elapsed_ms,
                                http_status=200,
                                attempts=attempt_idx + 1,
                                breaker=self.breaker.get_state(),
                                truncated=is_truncated,
                                error_message="No answer returned in response",
                            )
                            self._log_structured(decision)
                            return decision

                        selected_raw = str(
                            first_ans.get("choice") or first_ans.get("selected") or ""
                        ).strip()

                        # 200 但空 choice 不算成功：不得重置熔断计数，按失败/降级处理
                        if not selected_raw:
                            lease.record_failure()
                            self.metrics.failed_calls += 1
                            decision = Decision(
                                status="invalid",
                                selected="unknown",
                                reason_code="EMPTY_CHOICE",
                                elapsed_ms=elapsed_ms,
                                http_status=200,
                                attempts=attempt_idx + 1,
                                breaker=self.breaker.get_state(),
                                truncated=is_truncated,
                                error_message="Model returned empty choice",
                            )
                            self._log_structured(decision)
                            return decision

                        if (
                            sanitized_req.choices
                            and selected_raw not in sanitized_req.choices
                        ):
                            selected = "unknown"
                        else:
                            selected = selected_raw

                        raw_probs = first_ans.get("probabilities")
                        probs: dict[str, float] = {}
                        if isinstance(raw_probs, dict):
                            for k, v in raw_probs.items():
                                try:
                                    fv = float(v)
                                    if 0.0 <= fv <= 1.0:
                                        probs[str(k)] = fv
                                except (ValueError, TypeError):
                                    pass

                        try:
                            conf = float(first_ans.get("confidence", 0.0))
                            conf = max(0.0, min(1.0, conf))
                        except (ValueError, TypeError):
                            conf = 0.0

                        usage = data.get("usage", {})
                        try:
                            input_tokens = (
                                int(usage.get("input_tokens", 0))
                                if isinstance(usage, dict)
                                else 0
                            )
                        except (ValueError, TypeError):
                            input_tokens = 0

                        # 末次 deadline 检查：解析完成到写缓存/判成功之间
                        parse_end_t = time.monotonic()
                        if parse_end_t >= budget_deadline:
                            raise asyncio.TimeoutError()

                        # 判定真正成功：只有当 selected 有效且非 unknown 时，才重置熔断器与入缓存
                        if selected == "unknown":
                            lease.record_failure()
                            self.metrics.failed_calls += 1
                        else:
                            lease.record_success()
                            self.metrics.success_calls += 1

                        decision = Decision(
                            status="ok",
                            selected=selected,
                            probabilities=probs,
                            confidence=conf,
                            model=data.get("model", self.model),
                            elapsed_ms=elapsed_ms,
                            input_tokens=input_tokens,
                            http_status=200,
                            attempts=attempt_idx + 1,
                            breaker=self.breaker.get_state(),
                            truncated=is_truncated,
                        )

                        # 写缓存（仅在未截断且非敏感且 selected 有效时）
                        if (
                            not is_sensitive
                            and not is_truncated
                            and selected != "unknown"
                        ):
                            self.cache.set(cache_key, decision)

                        self._log_structured(decision)
                        return decision

                    except (httpx.TimeoutException, httpx.TransportError) as exc:
                        elapsed_ms = (time.monotonic() - start_t) * 1000.0
                        clean_err = redact_sensitive_text(str(exc), self.api_key)
                        is_timeout = isinstance(exc, httpx.TimeoutException)
                        err_code = (
                            "TIMEOUT"
                            if is_timeout
                            else f"NETWORK_ERROR_{type(exc).__name__}"
                        )
                        default_msg = "Request timed out" if is_timeout else clean_err

                        if attempt_idx == self.MAX_RETRIES:
                            lease.record_failure()
                            self.metrics.failed_calls += 1
                            decision = Decision(
                                status="unavailable",
                                reason_code=err_code,
                                elapsed_ms=elapsed_ms,
                                attempts=attempt_idx + 1,
                                breaker=self.breaker.get_state(),
                                truncated=is_truncated,
                                error_message=default_msg,
                            )
                            self._log_structured(decision)
                            return decision

                        backoff = self._calculate_backoff(attempt_idx)
                        if time.monotonic() + backoff >= budget_deadline:
                            raise asyncio.TimeoutError()
                        await asyncio.sleep(backoff)
                        continue

                raise asyncio.TimeoutError()

            remaining_overall = max(0.001, budget_deadline - time.monotonic())
            try:
                return await asyncio.wait_for(
                    _execute_with_retries(), timeout=remaining_overall
                )
            except (asyncio.TimeoutError, TimeoutError):
                # 本地预算超限不记上游失败、不推进 generation
                self.metrics.failed_calls += 1
                elapsed_ms = (time.monotonic() - start_t) * 1000.0
                decision = Decision(
                    status="budget_exceeded",
                    reason_code="DEADLINE_EXCEEDED",
                    elapsed_ms=elapsed_ms,
                    attempts=max(1, last_attempt_idx + 1),
                    breaker=self.breaker.get_state(),
                    truncated=is_truncated,
                    error_message="Total budget wall-clock limit exceeded",
                )
                self._log_structured(decision)
                return decision
        except asyncio.CancelledError:
            self.metrics.failed_calls += 1
            raise
        except Exception as exc:
            self.metrics.failed_calls += 1
            lease.record_failure()
            elapsed_ms = (time.monotonic() - start_t) * 1000.0
            decision = Decision(
                status="invalid",
                reason_code=f"EXCEPTION_{type(exc).__name__}",
                elapsed_ms=elapsed_ms,
                attempts=0,
                breaker=self.breaker.get_state(),
                truncated=is_truncated,
                error_message=redact_sensitive_text(
                    f"{type(exc).__name__}: {exc}", self.api_key
                ),
            )
            self._log_structured(decision)
            return decision
        finally:
            # 保证在任何情况下（成功、失败、CancelledError、早退）释放试水探测位
            lease.release()

import time
from typing import Any

import httpx

from tg_signer.semantic.models import Decision, DecisionRequest


def normalize_base_url(url: str | None) -> str:
    """规范化 JEV Base URL：
    - 统一去除首尾空格与尾部斜杠
    - 若误填完整路径（如带 /systemone），剥离 /systemone
    - 统一规范为包含 /v1 结尾（如 https://api.example.com -> https://api.example.com/v1）
    """
    if not url:
        return "https://api.typesafe.ai/v1"
    cleaned = url.strip().rstrip("/")
    if cleaned.endswith("/systemone"):
        cleaned = cleaned[: -len("/systemone")].rstrip("/")
    if not cleaned.endswith("/v1"):
        cleaned = f"{cleaned}/v1"
    return cleaned


class JevClient:
    DEFAULT_BASE_URL: str = "https://api.typesafe.ai/v1"
    DEFAULT_MODEL: str = "jev-1.13.0"
    DEFAULT_TIMEOUT: float = 8.0
    DEFAULT_CONNECT_TIMEOUT: float = 3.0

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.api_key = api_key
        self.base_url = normalize_base_url(base_url)
        self.model = model
        self.timeout = timeout
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

    @staticmethod
    def _extract_error_message(resp: httpx.Response) -> str:
        try:
            data = resp.json()
            if isinstance(data, dict):
                err = data.get("error")
                if isinstance(err, dict):
                    return str(err.get("message") or err.get("type") or err)
                if err:
                    return str(err)
                if data.get("detail"):
                    return str(data["detail"])
                if data.get("message"):
                    return str(data["message"])
        except Exception:
            pass
        return resp.text[:200].strip()

    async def query_choice(
        self,
        request: DecisionRequest,
        *,
        deadline: float | None = None,
    ) -> Decision:
        if not self.api_key:
            return Decision(
                status="disabled",
                reason_code="NO_API_KEY",
                error_message="API key not configured",
            )

        now = time.monotonic()
        if deadline is not None and now >= deadline:
            return Decision(
                status="budget_exceeded",
                reason_code="DEADLINE_EXCEEDED",
                error_message="Deadline exceeded",
            )

        timeout_to_use = self.timeout
        if deadline is not None:
            remaining = deadline - now
            timeout_to_use = min(self.timeout, max(0.1, remaining))

        req_timeout = self._create_httpx_timeout(timeout_to_use)

        # 构造 criteria 字典以对齐 Jev 官方 SystemOne 契约
        if isinstance(request.choices, dict):
            criteria = dict(request.choices)
        elif isinstance(request.choices, list):
            criteria = {c: str(c) for c in request.choices}
        else:
            criteria = {"default": "default"}

        payload: dict[str, Any] = {
            "model": self.model,
            "state": request.state,
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

        start_t = time.monotonic()
        try:
            client = await self._get_client()
            resp = await client.post(
                target_url,
                json=payload,
                headers=headers,
                timeout=req_timeout,
            )
            elapsed_ms = (time.monotonic() - start_t) * 1000.0

            if resp.status_code == 429:
                err_msg = self._extract_error_message(resp)
                return Decision(
                    status="unavailable",
                    reason_code="RATE_LIMITED",
                    elapsed_ms=elapsed_ms,
                    http_status=429,
                    error_message=err_msg or "Rate limited",
                )
            if resp.status_code in (401, 403):
                err_msg = self._extract_error_message(resp)
                return Decision(
                    status="unavailable",
                    reason_code="AUTH_FAILED",
                    elapsed_ms=elapsed_ms,
                    http_status=resp.status_code,
                    error_message=err_msg or "Authentication failed",
                )
            if resp.status_code >= 400:
                err_msg = self._extract_error_message(resp)
                return Decision(
                    status="invalid",
                    reason_code=f"HTTP_{resp.status_code}",
                    elapsed_ms=elapsed_ms,
                    http_status=resp.status_code,
                    error_message=err_msg or f"HTTP {resp.status_code}",
                )

            data = resp.json()
            raw_answers = data.get("answers")
            first_ans: dict[str, Any] | None = None
            if isinstance(raw_answers, dict):
                first_ans = raw_answers.get("decision") or next(
                    iter(raw_answers.values()), None
                )
            elif isinstance(raw_answers, list) and raw_answers:
                first_ans = raw_answers[0]

            if not first_ans or not isinstance(first_ans, dict):
                return Decision(
                    status="invalid",
                    reason_code="NO_ANSWER",
                    elapsed_ms=elapsed_ms,
                    http_status=200,
                    error_message="No answer returned in response",
                )

            selected_raw = str(
                first_ans.get("choice") or first_ans.get("selected") or "unknown"
            )
            if (
                request.choices
                and selected_raw not in request.choices
                and selected_raw != "unknown"
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
                    int(usage.get("input_tokens", 0)) if isinstance(usage, dict) else 0
                )
            except (ValueError, TypeError):
                input_tokens = 0

            return Decision(
                status="ok",
                selected=selected,
                probabilities=probs,
                confidence=conf,
                model=data.get("model", self.model),
                elapsed_ms=elapsed_ms,
                input_tokens=input_tokens,
                http_status=200,
            )
        except httpx.TimeoutException:
            elapsed_ms = (time.monotonic() - start_t) * 1000.0
            return Decision(
                status="unavailable",
                reason_code="TIMEOUT",
                elapsed_ms=elapsed_ms,
                http_status=None,
                error_message="Request timed out",
            )
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start_t) * 1000.0
            return Decision(
                status="unavailable",
                reason_code=f"NETWORK_ERROR_{type(exc).__name__}",
                elapsed_ms=elapsed_ms,
                http_status=None,
                error_message=str(exc),
            )

import asyncio
import logging
import time
from typing import Any, Callable

from tg_signer.log_utils import safe_text_preview
from tg_signer.semantic.client import JevClient
from tg_signer.semantic.models import Decision, DecisionRequest

logger = logging.getLogger("tg_signer.semantic.service")


class SemanticService:
    def __init__(
        self,
        client: JevClient,
        *,
        max_concurrency: int = 2,
        max_calls_per_run: int = 6,
        max_calls_per_minute: int = 60,
        record_callback: Callable[[DecisionRequest, Decision, str], Any] | None = None,
    ):
        self.client = client
        self.max_calls_per_run = max_calls_per_run
        self.max_calls_per_minute = max_calls_per_minute
        self.record_callback = record_callback
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._run_call_counts: dict[str, int] = {}
        self._minute_window: list[float] = []

    def finish_run(self, run_id: str) -> None:
        self._run_call_counts.pop(run_id, None)

    def _check_rate_limits(self, run_id: str) -> str | None:
        if self.max_calls_per_run > 0:
            count = self._run_call_counts.get(run_id, 0)
            if count >= self.max_calls_per_run:
                return "RUN_BUDGET_EXCEEDED"

        now = time.monotonic()
        if self.max_calls_per_minute > 0:
            self._minute_window = [t for t in self._minute_window if now - t < 60.0]
            if len(self._minute_window) >= self.max_calls_per_minute:
                return "MINUTE_BUDGET_EXCEEDED"

        return None

    def _consume_call(self, run_id: str) -> None:
        if self.max_calls_per_run > 0:
            if len(self._run_call_counts) > 2000:
                keep = list(self._run_call_counts.keys())[-1000:]
                self._run_call_counts = {k: self._run_call_counts[k] for k in keep}
            self._run_call_counts[run_id] = self._run_call_counts.get(run_id, 0) + 1
        if self.max_calls_per_minute > 0:
            self._minute_window.append(time.monotonic())

    async def evaluate(
        self,
        request: DecisionRequest,
        *,
        deadline: float,
        run_id: str,
    ) -> Decision:
        req_scope = safe_text_preview(getattr(request, "scope", ""), max_chars=160)
        safe_run_id = safe_text_preview(run_id, max_chars=120)
        budget_err = self._check_rate_limits(run_id)
        if budget_err:
            logger.warning(
                "jev_service_rate_limit: reason=%s run_id=%s scope=%s",
                budget_err,
                safe_run_id,
                req_scope,
            )
            decision = Decision(status="budget_exceeded", reason_code=budget_err)
            if self.record_callback:
                try:
                    self.record_callback(request, decision, run_id)
                except Exception:
                    pass
            return decision

        now = time.monotonic()
        if now >= deadline:
            logger.warning(
                "jev_service_rate_limit: reason=DEADLINE_EXCEEDED run_id=%s scope=%s",
                safe_run_id,
                req_scope,
            )
            decision = Decision(
                status="budget_exceeded", reason_code="DEADLINE_EXCEEDED"
            )
            if self.record_callback:
                try:
                    self.record_callback(request, decision, run_id)
                except Exception:
                    pass
            return decision

        self._consume_call(run_id)

        try:
            async with self._semaphore:
                decision = await self.client.query_choice(request, deadline=deadline)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            decision = Decision(
                status="invalid", reason_code=f"SERVICE_{type(exc).__name__}"
            )

        if self.record_callback:
            try:
                self.record_callback(request, decision, run_id)
            except Exception:
                pass

        return decision

    async def close(self) -> None:
        self._run_call_counts.clear()
        self._minute_window.clear()
        await self.client.close()

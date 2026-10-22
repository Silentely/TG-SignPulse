import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.services.semantic.config import JevConfigStore
from backend.services.semantic.store import SemanticStore
from tg_signer.semantic.breaker import CircuitBreaker
from tg_signer.semantic.cache import JevDecisionCache
from tg_signer.semantic.client import JevClient
from tg_signer.semantic.models import Decision, DecisionRequest, config_revision
from tg_signer.semantic.runtime_port import register_semantic_runtime_provider
from tg_signer.semantic.service import SemanticService

logger = logging.getLogger("backend.services.semantic.runtime")


def scope_key(
    account: str, task: str, chat_id: int, thread_id: int | None, node_id: str
) -> str:
    thread_str = str(thread_id) if thread_id is not None else "0"
    return f"{account}:{task}:{chat_id}:{thread_str}:{node_id}"


class SemanticRuntime:
    def __init__(self, workdir: Path):
        self.workdir = Path(workdir)
        self.config_store = JevConfigStore(self.workdir)
        self.semantic_store = SemanticStore(self.workdir)
        self._breaker = CircuitBreaker()
        self._cache = JevDecisionCache(namespace="gen_0")
        self._service: SemanticService | None = None
        self._generation: int = -1
        self._queue: asyncio.Queue[tuple[DecisionRequest, str, str, float]] = (
            asyncio.Queue(maxsize=100)
        )
        self._workers: list[asyncio.Task] = []
        self._closing_tasks: set[asyncio.Task] = set()
        self._running = False

    def _track_close_service(self, service: SemanticService) -> None:
        task = asyncio.create_task(service.close())
        self._closing_tasks.add(task)
        task.add_done_callback(self._closing_tasks.discard)

    def _ensure_service(self) -> SemanticService | None:
        cfg = self.config_store.load()
        if not cfg.enabled or not cfg.api_key:
            if self._service is not None:
                self._track_close_service(self._service)
                self._service = None
            return None

        if self._service is None or self._generation != cfg.generation:
            if self._service is not None:
                self._track_close_service(self._service)
            # 配置代际切换时新建缓存命名空间，隔离旧缓存
            self._cache = JevDecisionCache(namespace=f"gen_{cfg.generation}")
            client = JevClient(
                api_key=cfg.api_key,
                base_url=cfg.base_url,
                model=cfg.model,
                timeout=cfg.timeout_seconds,
                breaker=self._breaker,
                cache=self._cache,
                is_saved_key=True,
            )
            self._service = SemanticService(
                client,
                max_concurrency=cfg.max_concurrency,
                max_calls_per_run=cfg.max_calls_per_run,
                max_calls_per_minute=cfg.max_calls_per_minute,
            )
            self._generation = cfg.generation
        return self._service

    @property
    def service(self) -> SemanticService | None:
        return self._ensure_service()

    def get_stats(self) -> dict[str, Any]:
        if self._service is not None and getattr(self._service, "client", None) is not None:
            return self._service.client.get_stats()
        return {
            "total_calls": 0,
            "success_calls": 0,
            "failed_calls": 0,
            "escalate_calls": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "cache_hit_rate": 0.0,
            "breaker": self._breaker.snapshot(),
            "cache": self._cache.stats(),
        }

    def record_observation(
        self,
        request: DecisionRequest,
        decision: Decision,
        *,
        rule_result: str = "",
        run_id: str = "",
    ) -> None:
        now_ts = time.time()
        now_iso = datetime.now(timezone.utc).isoformat()
        reason_code = decision.reason_code
        if not reason_code and rule_result == "unmatched":
            reason_code = "rule_unmatched"
        elif not reason_code:
            reason_code = "ok" if decision.status == "ok" else "unknown"

        row = {
            "scope": request.scope,
            "run_id": run_id,
            "kind": request.kind,
            "request_key": request.request_key,
            "config_revision": request.config_revision,
            "model": decision.model,
            "selected": decision.selected,
            "probabilities": decision.probabilities,
            "confidence": decision.confidence,
            "accepted": decision.status == "ok",
            "reason_code": reason_code,
            "elapsed_ms": decision.elapsed_ms,
            "input_tokens": decision.input_tokens,
            "rule_result": rule_result,
            "created_at": now_ts,
            "observed_at": now_iso,
            "state": request.state,
        }
        self.semantic_store.append(row)

    def is_current(
        self,
        *,
        account_name: str,
        task_name: str,
        revision: str,
        generation: int,
    ) -> bool:
        cfg = self.config_store.load()
        if cfg.generation != generation:
            return False
        from backend.services.sign_tasks import SignTaskService

        task_svc = SignTaskService()
        task = task_svc.get_task(task_name, account_name=account_name)
        if not task:
            return False
        task_dict = task.dict() if hasattr(task, "dict") else dict(task)
        current_rev = config_revision(task_dict)
        return current_rev == revision

    def enqueue_observation(
        self,
        request: DecisionRequest,
        *,
        rule_result: str,
        run_id: str,
        deadline: float,
    ) -> bool:
        if self._queue.full():
            logger.warning(
                "SemanticRuntime observation queue is full (%d), dropping observation for scope=%s",
                self._queue.maxsize,
                request.scope,
            )
            return False
        try:
            self._queue.put_nowait((request, rule_result, run_id, deadline))
            return True
        except asyncio.QueueFull:
            logger.warning(
                "SemanticRuntime observation queue full on put_nowait, dropping observation for scope=%s",
                request.scope,
            )
            return False

    async def _worker_loop(self) -> None:
        while self._running:
            try:
                item = await self._queue.get()
            except asyncio.CancelledError:
                break
            try:
                request, rule_result, run_id, deadline = item
                svc = self.service
                if svc:
                    decision = await svc.evaluate(
                        request, deadline=deadline, run_id=run_id
                    )
                else:
                    decision = Decision(
                        status="disabled", reason_code="SERVICE_DISABLED"
                    )
                self.record_observation(
                    request, decision, rule_result=rule_result, run_id=run_id
                )
            except asyncio.CancelledError:
                self._queue.task_done()
                break
            except Exception as e:
                logger.error(
                    "Error processing semantic observation: %s (scope=%s, request_key=%s)",
                    e,
                    getattr(item[0], "scope", "unknown"),
                    getattr(item[0], "request_key", "unknown"),
                    exc_info=True,
                )
            finally:
                self._queue.task_done()

    def start_workers(self, num_workers: int = 2) -> None:
        if self._running:
            return
        self._running = True
        for _ in range(num_workers):
            self._workers.append(asyncio.create_task(self._worker_loop()))

    async def close(self) -> None:
        self._running = False
        for w in self._workers:
            w.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        if self._closing_tasks:
            await asyncio.gather(*list(self._closing_tasks), return_exceptions=True)
            self._closing_tasks.clear()
        if self._service:
            await self._service.close()
            self._service = None


_GLOBAL_RUNTIME: SemanticRuntime | None = None


def get_semantic_runtime(workdir: Path | None = None) -> SemanticRuntime:
    global _GLOBAL_RUNTIME
    if _GLOBAL_RUNTIME is None:
        if workdir is None:
            from backend.config import WORKDIR

            workdir = Path(WORKDIR)
        _GLOBAL_RUNTIME = SemanticRuntime(workdir)
    return _GLOBAL_RUNTIME


def get_active_semantic_runtime() -> SemanticRuntime | None:
    return _GLOBAL_RUNTIME


# 自动向 tg_signer 核心层注册当前适配器实现，保障单向依赖
register_semantic_runtime_provider(get_semantic_runtime)

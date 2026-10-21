import asyncio
import time

import pytest

from tg_signer.semantic.client import JevClient
from tg_signer.semantic.models import Decision, DecisionRequest
from tg_signer.semantic.service import SemanticService


class MockJevClient(JevClient):
    def __init__(self, delay=0.01):
        super().__init__(api_key="mock_key")
        self.delay = delay
        self.call_count = 0

    async def query_choice(
        self, request: DecisionRequest, *, deadline: float | None = None
    ) -> Decision:
        self.call_count += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return Decision(
            status="ok",
            selected="success",
            probabilities={"success": 0.99, "failure": 0.01},
            confidence=0.99,
        )


@pytest.mark.asyncio
async def test_semantic_service_rate_limit_and_budget():
    client = MockJevClient(delay=0.0)
    service = SemanticService(
        client,
        max_concurrency=2,
        max_calls_per_run=2,
        max_calls_per_minute=5,
    )
    req = DecisionRequest(
        kind="result",
        scope="s1",
        state={},
        choices={"success": "yes", "failure": "no"},
        instructions="check",
        request_key="k1",
        config_revision="r1",
    )

    # 第一次调用
    d1 = await service.evaluate(req, deadline=time.monotonic() + 5, run_id="run_1")
    assert d1.status == "ok"
    assert client.call_count == 1

    # 第二次调用
    d2 = await service.evaluate(req, deadline=time.monotonic() + 5, run_id="run_1")
    assert d2.status == "ok"
    assert client.call_count == 2

    # 第三次调用超过每 run 限制 (2次)
    d3 = await service.evaluate(req, deadline=time.monotonic() + 5, run_id="run_1")
    assert d3.status == "budget_exceeded"
    assert d3.reason_code == "RUN_BUDGET_EXCEEDED"
    assert client.call_count == 2  # 没打到 client

    # 新 run_id 可以继续调用
    d4 = await service.evaluate(req, deadline=time.monotonic() + 5, run_id="run_2")
    assert d4.status == "ok"
    assert client.call_count == 3


@pytest.mark.asyncio
async def test_semantic_service_deadline_exceeded():
    client = MockJevClient(delay=0.0)
    service = SemanticService(client)
    req = DecisionRequest(
        kind="result",
        scope="s1",
        state={},
        choices={"success": "yes", "failure": "no"},
        instructions="check",
        request_key="k1",
        config_revision="r1",
    )
    # deadline 已经过去
    d = await service.evaluate(req, deadline=time.monotonic() - 1, run_id="run_1")
    assert d.status == "budget_exceeded"
    assert d.reason_code == "DEADLINE_EXCEEDED"

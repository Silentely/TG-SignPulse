"""SSE 鉴权回归：EventSource 先用 Bearer JWT 换一次性票据，再以 ?ticket= 建流。"""
from __future__ import annotations

from typing import Iterator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.services.stream_tickets import get_stream_ticket_store
from tests.test_api import _login, api_client, db  # noqa: F401 — fixtures re-export


@pytest.fixture
def client(api_client: TestClient) -> Iterator[TestClient]:  # noqa: F811
    yield api_client


@pytest.fixture(autouse=True)
def _clean_tickets():
    """每个用例前清空票据，避免跨用例复用导致一次性语义被掩盖。"""
    get_stream_ticket_store().clear()
    yield
    get_stream_ticket_store().clear()


class TestSignHistorySSEAuth:
    def test_missing_ticket_returns_401(self, client: TestClient, db):  # noqa: F811
        resp = client.get("/api/events/sign-history")
        assert resp.status_code == 401

    def test_invalid_ticket_returns_401(self, client: TestClient, db):  # noqa: F811
        resp = client.get(
            "/api/events/sign-history",
            params={"token": "not-a-valid-ticket"},
        )
        assert resp.status_code == 401

    def test_ticket_is_single_use(self, client: TestClient, db):  # noqa: F811
        """同一 URL 重放必须被拒：票据兑换后立即作废。"""
        token = _login(client)
        ticket = client.post(
            "/api/events/ticket",
            json={"purpose": "sign_history_sse"},
            headers={"Authorization": f"Bearer {token}"},
        ).json()["ticket"]

        with patch("backend.api.routes.events._sign_history_event_stream") as mock_stream:

            async def _empty():
                yield b"event: ready\ndata: {}\n\n"
                return

            mock_stream.return_value = _empty()
            with client.stream(
                "GET",
                "/api/events/sign-history",
                params={"ticket": ticket},
            ) as resp:
                assert resp.status_code == 200, resp.text
                for _chunk in resp.iter_bytes():
                    break

        # 重放同一票据：流已被兑换，第二次必须 401
        replay = client.get("/api/events/sign-history", params={"ticket": ticket})
        assert replay.status_code == 401

    def test_ticket_bound_to_other_purpose_is_rejected(self, client: TestClient, db):  # noqa: F811
        """为 WS 用途签发的票据不能拿来建 SSE 流。"""
        token = _login(client)
        ticket = client.post(
            "/api/events/ticket",
            json={"purpose": "task_run_ws"},
            headers={"Authorization": f"Bearer {token}"},
        ).json()["ticket"]

        resp = client.get("/api/events/sign-history", params={"ticket": ticket})
        assert resp.status_code == 401

    def test_issue_ticket_requires_auth(self, client: TestClient, db):  # noqa: F811
        resp = client.post(
            "/api/events/ticket",
            json={"purpose": "sign_history_sse"},
        )
        assert resp.status_code == 401

    def test_issue_ticket_rejects_unknown_purpose(self, client: TestClient, db):  # noqa: F811
        token = _login(client)
        resp = client.post(
            "/api/events/ticket",
            json={"purpose": "nope"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

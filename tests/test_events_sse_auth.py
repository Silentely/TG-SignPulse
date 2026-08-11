"""SSE 鉴权回归：EventSource 使用 ?token= 时必须正确校验 JWT。"""
from __future__ import annotations

from typing import Iterator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from tests.test_api import _login, api_client, db  # noqa: F401 — fixtures re-export


@pytest.fixture
def client(api_client: TestClient) -> Iterator[TestClient]:  # noqa: F811
    yield api_client


class TestSignHistorySSEAuth:
    def test_missing_token_returns_401(self, client: TestClient, db):  # noqa: F811
        resp = client.get("/api/events/sign-history")
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, client: TestClient, db):  # noqa: F811
        resp = client.get(
            "/api/events/sign-history",
            params={"token": "not-a-valid-jwt"},
        )
        assert resp.status_code == 401

    def test_valid_token_does_not_crash_with_typeerror(self, client: TestClient, db):  # noqa: F811
        """
        回归 Issue #7：verify_token 缺 db 参数导致 TypeError 500。
        鉴权通过后应进入 SSE 流（至少不 500）。
        """
        token = _login(client)
        with patch(
            "backend.api.routes.events._sign_history_event_stream",
        ) as mock_stream:
            async def _empty():
                yield b"event: ready\ndata: {}\n\n"
                return

            mock_stream.return_value = _empty()
            with client.stream(
                "GET",
                "/api/events/sign-history",
                params={"token": token},
            ) as resp:
                assert resp.status_code == 200, resp.text
                # 读取首包确认流已建立
                chunks = []
                for chunk in resp.iter_bytes():
                    chunks.append(chunk)
                    if chunks:
                        break
                assert chunks, "SSE 流应至少产出一段数据"

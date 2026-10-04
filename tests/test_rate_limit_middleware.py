from __future__ import annotations

import asyncio
import uuid
from unittest.mock import MagicMock

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.core.rate_limit import get_rate_limiter
from backend.core.rate_limit_middleware import SENSITIVE_RULES, RateLimitMiddleware
from backend.main import app


def test_login_rate_limiting_never_calls_db():
    rate_limiter = get_rate_limiter()
    rate_limiter.reset_all()

    client = TestClient(app)
    db_called_request_ids = set()

    from backend.core.database import get_db

    fake_db = MagicMock()
    fake_db.query.return_value.filter.return_value.first.return_value = None

    def spy_get_db(request: Request):
        req_id = request.headers.get("X-Request-ID")
        if req_id:
            db_called_request_ids.add(req_id)
        yield fake_db

    app.dependency_overrides[get_db] = spy_get_db
    try:
        blocked_found = False
        for _ in range(40):
            req_id = str(uuid.uuid4())
            resp = client.post(
                "/api/auth/login",
                json={"username": "fake", "password": "wrong"},
                headers={"X-Request-ID": req_id},
            )
            if resp.status_code == 429:
                blocked_found = True
                assert resp.headers.get("Retry-After") is not None
                assert req_id not in db_called_request_ids, (
                    f"Request {req_id} triggered DB session on 429!"
                )
        assert blocked_found is True
    finally:
        app.dependency_overrides.pop(get_db, None)
        rate_limiter.reset_all()


def test_totp_reset_rate_limiting_never_calls_db():
    rate_limiter = get_rate_limiter()
    rate_limiter.reset_all()

    client = TestClient(app)
    db_called_request_ids = set()

    from backend.core.database import get_db

    fake_db = MagicMock()
    fake_db.query.return_value.filter.return_value.first.return_value = None

    def spy_get_db(request: Request):
        req_id = request.headers.get("X-Request-ID")
        if req_id:
            db_called_request_ids.add(req_id)
        yield fake_db

    app.dependency_overrides[get_db] = spy_get_db
    try:
        blocked_found = False
        for _ in range(20):
            req_id = str(uuid.uuid4())
            resp = client.post(
                "/api/auth/reset-totp",
                json={"username": "fake_user", "password": "wrong_password"},
                headers={"X-Request-ID": req_id},
            )
            if resp.status_code == 429:
                blocked_found = True
                assert resp.headers.get("Retry-After") is not None
                assert req_id not in db_called_request_ids, (
                    f"Request {req_id} triggered DB session on 429!"
                )
        assert blocked_found is True
    finally:
        app.dependency_overrides.pop(get_db, None)
        rate_limiter.reset_all()


def test_options_request_bypasses_rate_limit(db_session):
    rate_limiter = get_rate_limiter()
    rate_limiter.reset_all()

    client = TestClient(app)
    # Even if we exhaust the rate limit on login
    for _ in range(6):
        client.post(
            "/api/auth/login",
            json={"username": "test_preflight", "password": "wrong"},
        )

    # An OPTIONS request (CORS preflight) must NOT be blocked with 429
    resp = client.options(
        "/api/auth/login",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.status_code != 429
    rate_limiter.reset_all()


def test_custom_general_rate_limit_middleware():
    test_app = FastAPI()
    test_app.add_middleware(RateLimitMiddleware, general_rpm=3)

    @test_app.get("/api/test-endpoint")
    def sample_endpoint():
        return {"ok": True}

    rate_limiter = get_rate_limiter()
    rate_limiter.reset_all()

    client = TestClient(test_app)
    statuses = [client.get("/api/test-endpoint").status_code for _ in range(5)]
    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 429
    assert statuses[4] == 429

    rate_limiter.reset_all()


def test_rate_limit_headers_and_body_format():
    test_app = FastAPI()
    test_app.add_middleware(RateLimitMiddleware, general_rpm=1)

    @test_app.get("/api/ping")
    def ping():
        return {"pong": True}

    rate_limiter = get_rate_limiter()
    rate_limiter.reset_all()

    client = TestClient(test_app)
    # First request succeeds
    r1 = client.get("/api/ping", headers={"X-Request-ID": "req-1"})
    assert r1.status_code == 200

    # Second request is rate limited
    r2 = client.get("/api/ping", headers={"X-Request-ID": "req-2"})
    assert r2.status_code == 429
    assert r2.headers.get("Content-Type") == "application/json"
    retry_after = r2.headers.get("Retry-After")
    assert retry_after is not None
    assert int(retry_after) > 0
    assert r2.headers.get("X-Request-ID") == "req-2"
    data = r2.json()
    assert "detail" in data
    assert isinstance(data["detail"], str)

    rate_limiter.reset_all()


def test_account_login_rule_uses_same_composite_key_as_route():
    rule = next(
        rule for rule in SENSITIVE_RULES if rule.scope == "accounts.login.start"
    )
    assert rule.key_fields == ("account_name", "phone_number")


def test_qr_password_rule_uses_login_id_field():
    rule = next(
        rule for rule in SENSITIVE_RULES if rule.scope == "accounts.qr.password"
    )
    assert rule.key_fields == ("login_id",)


def test_sensitive_middleware_replays_body_and_stores_composite_key():
    captured = {}
    sent = []

    async def app(scope, receive, send):
        captured["state"] = scope["state"]
        captured["body"] = (await receive())["body"]
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [],
            }
        )
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = RateLimitMiddleware(app)
    body = b'{"account_name":"acc-a","phone_number":"+8613800000000"}'
    received = False

    async def receive():
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/accounts/login/start",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 1234),
        "query_string": b"",
        "state": {},
    }
    get_rate_limiter().reset_all()
    asyncio.run(middleware(scope, receive, send))

    assert captured["body"] == body
    assert captured["state"]["rate_limit_checked_accounts.login.start"] is True
    assert captured["state"]["rate_limit_key_accounts.login.start"]
    assert sent[0]["status"] == 200
    get_rate_limiter().reset_all()


def test_sensitive_middleware_rejects_oversized_body_before_app():
    called = False
    sent = []

    async def app(scope, receive, send):
        nonlocal called
        called = True

    middleware = RateLimitMiddleware(app)

    async def receive():
        return {
            "type": "http.request",
            "body": b"x" * (middleware.MAX_BODY_BYTES + 1),
            "more_body": False,
        }

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/accounts/login/start",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "query_string": b"",
        "state": {},
    }
    asyncio.run(middleware(scope, receive, send))

    assert called is False
    assert sent[0]["status"] == 413

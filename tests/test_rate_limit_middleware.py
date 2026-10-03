from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.core.rate_limit import get_rate_limiter
from backend.core.rate_limit_middleware import RateLimitMiddleware
from backend.main import app


def test_login_rate_limiting_never_calls_db():
    rate_limiter = get_rate_limiter()
    rate_limiter.reset_all()

    client = TestClient(app)
    db_called_request_ids = set()

    from backend.core.database import get_db

    def spy_get_db(request: Request):
        req_id = request.headers.get("X-Request-ID")
        if req_id:
            db_called_request_ids.add(req_id)
        yield

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
                assert (
                    req_id not in db_called_request_ids
                ), f"Request {req_id} triggered DB session on 429!"
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

    def spy_get_db(request: Request):
        req_id = request.headers.get("X-Request-ID")
        if req_id:
            db_called_request_ids.add(req_id)
        yield

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
                assert (
                    req_id not in db_called_request_ids
                ), f"Request {req_id} triggered DB session on 429!"
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


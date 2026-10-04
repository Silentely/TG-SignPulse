from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.core.rate_limit import (
    compose_rate_limit_key,
    get_rate_limiter,
)

logger = logging.getLogger("backend.rate_limit_middleware")


@dataclass(frozen=True)
class SensitiveRouteRule:
    method: str
    path: str
    scope: str
    max_attempts: int
    window_seconds: int
    block_seconds: int
    detail: str
    key_fields: tuple[str, ...] = ()


SENSITIVE_RULES: tuple[SensitiveRouteRule, ...] = (
    SensitiveRouteRule(
        method="POST",
        path="/api/auth/login",
        scope="auth.login",
        max_attempts=5,
        window_seconds=300,
        block_seconds=900,
        detail="Too many login attempts. Please try again later.",
        key_fields=("username",),
    ),
    SensitiveRouteRule(
        method="POST",
        path="/api/auth/reset-totp",
        scope="auth.reset_totp",
        max_attempts=5,
        window_seconds=600,
        block_seconds=1800,
        detail="Too many TOTP reset attempts. Please try again later.",
        key_fields=("username",),
    ),
    SensitiveRouteRule(
        method="POST",
        path="/api/accounts/login/start",
        scope="accounts.login.start",
        max_attempts=6,
        window_seconds=600,
        block_seconds=900,
        detail="Too many requests. Please try again later.",
        key_fields=("account_name", "phone_number"),
    ),
    SensitiveRouteRule(
        method="POST",
        path="/api/accounts/login/verify",
        scope="accounts.login.verify",
        max_attempts=8,
        window_seconds=600,
        block_seconds=900,
        detail="Too many requests. Please try again later.",
        key_fields=("account_name", "phone_number"),
    ),
    SensitiveRouteRule(
        method="POST",
        path="/api/accounts/qr/start",
        scope="accounts.qr.start",
        max_attempts=8,
        window_seconds=600,
        block_seconds=900,
        detail="Too many requests. Please try again later.",
        key_fields=("account_name",),
    ),
    SensitiveRouteRule(
        method="POST",
        path="/api/accounts/qr/password",
        scope="accounts.qr.password",
        max_attempts=5,
        window_seconds=600,
        block_seconds=900,
        detail="Too many requests. Please try again later.",
        key_fields=("login_id",),
    ),
)


class RateLimitMiddleware:
    """Upfront ASGI Rate-Limiting Middleware.

    Intercepts requests at the ASGI level before route dependencies,
    DB sessions, or handler execution. Over-limit requests are immediately
    rejected with HTTP 429 and a Retry-After header.
    """

    MAX_BODY_BYTES = 256 * 1024

    def __init__(
        self,
        app: ASGIApp,
        rules: Optional[tuple[SensitiveRouteRule, ...]] = None,
        general_rpm: Optional[int] = None,
    ) -> None:
        self.app = app
        self.rules = rules if rules is not None else SENSITIVE_RULES
        self._rules_by_method_path = {
            (r.method, r.path): r for r in self.rules
        }

        # Optional general API rate limit (requests per minute per client)
        if general_rpm is None:
            raw_rpm = os.getenv("RATE_LIMIT_GENERAL_RPM", "").strip()
            self.general_rpm = int(raw_rpm) if raw_rpm.isdigit() else None
        else:
            self.general_rpm = general_rpm

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET").upper()
        if method == "OPTIONS":
            # Bypass CORS preflight requests
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        # Match sensitive endpoint rule
        rule = self._rules_by_method_path.get((method, path))
        if rule is None and path.endswith("/"):
            rule = self._rules_by_method_path.get((method, path.rstrip("/")))

        rate_limiter = get_rate_limiter()

        if rule is not None:
            # Sensitive route matched
            body = b""
            cached_receive = receive
            field_values: list[str] = []

            if rule.key_fields and method in ("POST", "PUT", "PATCH"):
                content_length = Headers(scope=scope).get("content-length")
                try:
                    if content_length and int(content_length) > self.MAX_BODY_BYTES:
                        await self._send_error(
                            send,
                            status_code=413,
                            detail="Request body is too large.",
                        )
                        return
                except ValueError:
                    pass

                body_chunks = []
                body_size = 0
                while True:
                    message = await receive()
                    if message["type"] == "http.request":
                        chunk = message.get("body", b"")
                        body_size += len(chunk)
                        if body_size > self.MAX_BODY_BYTES:
                            await self._send_error(
                                send,
                                status_code=413,
                                detail="Request body is too large.",
                            )
                            return
                        body_chunks.append(chunk)
                        if not message.get("more_body", False):
                            break
                    elif message["type"] == "http.disconnect":
                        return
                body = b"".join(body_chunks)

                if body:
                    try:
                        data = json.loads(body)
                        if isinstance(data, dict):
                            for field_name in rule.key_fields:
                                val = data.get(field_name)
                                field_values.append(
                                    str(val).strip() if val is not None else ""
                                )
                    except (ValueError, TypeError, UnicodeDecodeError):
                        pass

                body_delivered = False

                async def _cached_receive() -> Message:
                    nonlocal body_delivered
                    if not body_delivered:
                        body_delivered = True
                        return {
                            "type": "http.request",
                            "body": body,
                            "more_body": False,
                        }
                    return await receive()

                cached_receive = _cached_receive

            request = Request(scope)
            key = compose_rate_limit_key(request, *field_values)

            try:
                rate_limiter.hit(
                    scope=rule.scope,
                    key=key,
                    max_attempts=rule.max_attempts,
                    window_seconds=rule.window_seconds,
                    block_seconds=rule.block_seconds,
                    detail=rule.detail,
                )
            except HTTPException as exc:
                if exc.status_code == 429:
                    logger.warning(
                        "Upfront ASGI rate limit blocked request: path=%s method=%s key=%s detail=%s",
                        path,
                        method,
                        key,
                        exc.detail,
                    )
                    await self._send_429(scope, send, exc)
                    return
                raise

            # Under limit: flag request state to prevent double-counting in downstream dependencies
            state = scope.setdefault("state", {})
            state[f"rate_limit_checked_{rule.scope}"] = True
            state[f"rate_limit_key_{rule.scope}"] = key
            await self.app(scope, cached_receive, send)
            return

        # General API rate limiting (if enabled and matches /api/)
        if self.general_rpm and path.startswith("/api/"):
            request = Request(scope)
            key = compose_rate_limit_key(request)
            try:
                rate_limiter.hit(
                    scope="api.general",
                    key=key,
                    max_attempts=self.general_rpm,
                    window_seconds=60,
                    block_seconds=60,
                    detail="Too many requests. Please slow down.",
                )
            except HTTPException as exc:
                if exc.status_code == 429:
                    logger.warning(
                        "General API rate limit blocked request: path=%s key=%s",
                        path,
                        key,
                    )
                    await self._send_429(scope, send, exc)
                    return
                raise

        await self.app(scope, receive, send)

    async def _send_429(
        self, scope: Scope, send: Send, exc: HTTPException
    ) -> None:
        retry_after = "60"
        if exc.headers and "Retry-After" in exc.headers:
            retry_after = str(exc.headers["Retry-After"])

        detail = exc.detail if isinstance(exc.detail, str) else "Too Many Requests"
        body = json.dumps({"detail": detail}).encode("utf-8")

        headers = [
            (b"content-type", b"application/json"),
            (b"retry-after", retry_after.encode("ascii")),
            (b"content-length", str(len(body)).encode("ascii")),
        ]

        headers_obj = Headers(scope=scope)
        req_id = headers_obj.get("x-request-id")
        if req_id:
            headers.append((b"x-request-id", req_id.encode("latin-1")))

        await send({
            "type": "http.response.start",
            "status": 429,
            "headers": headers,
        })
        await send({
            "type": "http.response.body",
            "body": body,
            "more_body": False,
        })

    async def _send_error(self, send: Send, *, status_code: int, detail: str) -> None:
        body = json.dumps({"detail": detail}).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({
            "type": "http.response.body",
            "body": body,
            "more_body": False,
        })

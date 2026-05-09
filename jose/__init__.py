from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, Iterable


class JWTError(Exception):
    pass


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp())
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


class _JWTModule:
    def encode(self, claims: dict[str, Any], key: str, algorithm: str = "HS256") -> str:
        if algorithm != "HS256":
            raise JWTError(f"Unsupported algorithm: {algorithm}")

        header = {"alg": algorithm, "typ": "JWT"}
        segments = [
            _b64url_encode(
                json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
            ),
            _b64url_encode(
                json.dumps(
                    claims,
                    separators=(",", ":"),
                    sort_keys=True,
                    default=_json_default,
                ).encode("utf-8")
            ),
        ]
        signing_input = ".".join(segments).encode("ascii")
        signature = hmac.new(
            str(key).encode("utf-8"),
            signing_input,
            hashlib.sha256,
        ).digest()
        segments.append(_b64url_encode(signature))
        return ".".join(segments)

    def decode(
        self,
        token: str,
        key: str,
        algorithms: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        allowed = set(algorithms or {"HS256"})
        if "HS256" not in allowed:
            raise JWTError("HS256 is required")

        try:
            header_b64, payload_b64, signature_b64 = str(token).split(".", 2)
        except ValueError as exc:
            raise JWTError("Invalid token format") from exc

        try:
            header = json.loads(_b64url_decode(header_b64).decode("utf-8"))
            payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
            signature = _b64url_decode(signature_b64)
        except Exception as exc:
            raise JWTError("Invalid token encoding") from exc

        if header.get("alg") != "HS256":
            raise JWTError("Unsupported token algorithm")

        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected = hmac.new(
            str(key).encode("utf-8"),
            signing_input,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(signature, expected):
            raise JWTError("Signature verification failed")

        exp = payload.get("exp")
        if exp is not None:
            try:
                exp_ts = float(exp)
            except (TypeError, ValueError) as exc:
                raise JWTError("Invalid exp claim") from exc
            if exp_ts < datetime.now(timezone.utc).timestamp():
                raise JWTError("Signature has expired")

        return payload


jwt = _JWTModule()

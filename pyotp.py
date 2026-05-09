from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from urllib.parse import quote


def random_base32(length: int = 32) -> str:
    if length <= 0:
        raise ValueError("length must be positive")
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
    return "".join(secrets.choice(alphabet) for _ in range(length))


class TOTP:
    def __init__(
        self,
        secret: str,
        digits: int = 6,
        interval: int = 30,
        digest=hashlib.sha1,
    ) -> None:
        self.secret = str(secret or "").strip().replace(" ", "").upper()
        self.digits = int(digits)
        self.interval = int(interval)
        self.digest = digest

    def _byte_secret(self) -> bytes:
        padded = self.secret + "=" * ((8 - len(self.secret) % 8) % 8)
        return base64.b32decode(padded, casefold=True)

    def at(self, for_time: int | float) -> str:
        counter = int(float(for_time) // self.interval)
        counter_bytes = counter.to_bytes(8, "big")
        digest = hmac.new(
            self._byte_secret(),
            counter_bytes,
            self.digest,
        ).digest()
        offset = digest[-1] & 0x0F
        code_int = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
        code = code_int % (10**self.digits)
        return str(code).zfill(self.digits)

    def now(self) -> str:
        return self.at(time.time())

    def verify(
        self,
        otp: str,
        for_time: int | float | None = None,
        valid_window: int = 0,
    ) -> bool:
        code = str(otp or "").strip().replace(" ", "")
        if not code:
            return False

        base_time = float(time.time() if for_time is None else for_time)
        window = max(int(valid_window), 0)
        for offset in range(-window, window + 1):
            candidate_time = base_time + offset * self.interval
            if hmac.compare_digest(self.at(candidate_time), code):
                return True
        return False

    def provisioning_uri(self, name: str, issuer_name: str | None = None) -> str:
        label = quote(str(name or "user"))
        params = [f"secret={quote(self.secret)}"]
        if issuer_name:
            issuer = quote(str(issuer_name))
            label = f"{issuer}:{label}"
            params.append(f"issuer={issuer}")
        if self.digits != 6:
            params.append(f"digits={self.digits}")
        if self.interval != 30:
            params.append(f"period={self.interval}")
        return f"otpauth://totp/{label}?{'&'.join(params)}"

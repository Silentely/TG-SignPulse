from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_now_naive() -> datetime:
    return utc_now().replace(tzinfo=None)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def utc_now_iso_z() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def utc_from_timestamp(timestamp: int | float) -> datetime:
    return datetime.fromtimestamp(timestamp, UTC)


def utc_from_timestamp_iso_z(timestamp: int | float) -> str:
    return utc_from_timestamp(timestamp).isoformat().replace("+00:00", "Z")

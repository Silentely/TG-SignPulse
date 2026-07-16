"""
关键词监听账号分片

用于多实例部署时按账号拆分监听负载，避免多进程挂同一 session。

环境变量：
- APP_MONITOR_ACCOUNT_ALLOWLIST: 逗号分隔账号白名单（优先）
- APP_MONITOR_SHARD: 形如 ``i/n``，对账号名 CRC32 取模，仅处理余数为 i 的账号
"""
from __future__ import annotations

import os
import zlib
from typing import Optional


def parse_monitor_shard(raw: Optional[str] = None) -> Optional[tuple[int, int]]:
    value = (raw if raw is not None else os.getenv("APP_MONITOR_SHARD", "")).strip()
    if not value or "/" not in value:
        return None
    left, right = value.split("/", 1)
    try:
        index = int(left)
        total = int(right)
    except ValueError:
        return None
    if total < 1 or index < 0 or index >= total:
        return None
    return index, total


def parse_account_allowlist(raw: Optional[str] = None) -> Optional[set[str]]:
    value = (
        raw
        if raw is not None
        else os.getenv("APP_MONITOR_ACCOUNT_ALLOWLIST", "")
    ).strip()
    if not value:
        return None
    items = {part.strip() for part in value.split(",") if part.strip()}
    return items or None


def account_in_monitor_scope(
    account_name: str,
    *,
    allowlist: Optional[set[str]] = None,
    shard: Optional[tuple[int, int]] = None,
) -> bool:
    """判断账号是否应由当前实例监听。"""
    name = str(account_name or "").strip()
    if not name or name == "*":
        return False

    allowed = allowlist if allowlist is not None else parse_account_allowlist()
    if allowed is not None and name not in allowed:
        return False

    shard_spec = shard if shard is not None else parse_monitor_shard()
    if shard_spec is not None:
        index, total = shard_spec
        bucket = zlib.crc32(name.encode("utf-8")) % total
        if bucket != index:
            return False
    return True

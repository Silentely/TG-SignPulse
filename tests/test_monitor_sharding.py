"""关键词监听账号分片单元测试。"""
from __future__ import annotations

from backend.services.keyword_monitor.sharding import (
    account_in_monitor_scope,
    parse_account_allowlist,
    parse_monitor_shard,
)


def test_parse_shard_valid():
    assert parse_monitor_shard("0/3") == (0, 3)
    assert parse_monitor_shard("2/3") == (2, 3)


def test_parse_shard_invalid():
    assert parse_monitor_shard("") is None
    assert parse_monitor_shard("3/3") is None
    assert parse_monitor_shard("a/b") is None


def test_allowlist():
    assert parse_account_allowlist("a, b ,c") == {"a", "b", "c"}
    assert account_in_monitor_scope("a", allowlist={"a", "b"}) is True
    assert account_in_monitor_scope("c", allowlist={"a", "b"}) is False


def test_shard_partition_covers_all():
    names = [f"acc{i}" for i in range(30)]
    total = 3
    buckets = {0: [], 1: [], 2: []}
    for name in names:
        for idx in range(total):
            if account_in_monitor_scope(name, shard=(idx, total)):
                buckets[idx].append(name)
                break
    # 每个账号恰好落入一个分片
    merged = buckets[0] + buckets[1] + buckets[2]
    assert sorted(merged) == sorted(names)
    assert all(len(v) > 0 for v in buckets.values())


def test_allowlist_and_shard_combined():
    # 白名单优先过滤
    assert (
        account_in_monitor_scope(
            "x",
            allowlist={"y"},
            shard=(0, 2),
        )
        is False
    )

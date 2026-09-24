"""stream_tickets 票据存储单测：一次性、按用途/资源隔离、过期清理。"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from backend.services.stream_tickets import (
    PURPOSE_SIGN_HISTORY_SSE,
    PURPOSE_TASK_RUN_WS,
    StreamTicketStore,
)


class TestStreamTicketStore:
    def test_issue_and_consume_roundtrip(self):
        store = StreamTicketStore()
        ticket = store.issue(
            user_id=42, username="admin", purpose=PURPOSE_SIGN_HISTORY_SSE
        )
        principal = store.consume(ticket, PURPOSE_SIGN_HISTORY_SSE)
        assert principal is not None
        assert principal.user_id == 42
        assert principal.username == "admin"

    def test_ticket_is_single_use(self):
        store = StreamTicketStore()
        ticket = store.issue(user_id=1, username="u", purpose=PURPOSE_SIGN_HISTORY_SSE)
        assert store.consume(ticket, PURPOSE_SIGN_HISTORY_SSE) is not None
        # 第二次兑换同一票据必须失败：URL 重放失去意义
        assert store.consume(ticket, PURPOSE_SIGN_HISTORY_SSE) is None

    def test_concurrent_consume_yields_exactly_one_winner(self):
        """并发兑换同一张票只能有一个成功。

        读取与删除若不在同一把锁内完成，多个线程会同时读到同一张票，
        「仅可兑换一次」的保证失效，同一票据可开出多条流。
        """
        store = StreamTicketStore()
        ticket = store.issue(user_id=7, username="u", purpose=PURPOSE_SIGN_HISTORY_SSE)

        workers = 16
        barrier = threading.Barrier(workers)

        def consume_once(_index: int) -> object:
            barrier.wait()
            return store.consume(ticket, PURPOSE_SIGN_HISTORY_SSE)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(consume_once, range(workers)))

        winners = [r for r in results if r is not None]
        assert len(winners) == 1
        assert winners[0].user_id == 7

    def test_purpose_mismatch_rejected(self):
        store = StreamTicketStore()
        ticket = store.issue(user_id=1, username="u", purpose=PURPOSE_SIGN_HISTORY_SSE)
        assert store.consume(ticket, PURPOSE_TASK_RUN_WS) is None

    def test_resource_mismatch_rejected(self):
        """绑定资源的票据不能被挪到同一用途的其它资源上。"""
        store = StreamTicketStore()
        ticket = store.issue(
            user_id=1, username="u", purpose=PURPOSE_TASK_RUN_WS, resource="task-a"
        )
        assert store.consume(ticket, PURPOSE_TASK_RUN_WS, "task-a") is not None
        other = store.issue(
            user_id=1, username="u", purpose=PURPOSE_TASK_RUN_WS, resource="task-b"
        )
        assert store.consume(other, PURPOSE_TASK_RUN_WS, "task-a") is None

    def test_blank_ticket_rejected(self):
        store = StreamTicketStore()
        assert store.consume("", PURPOSE_SIGN_HISTORY_SSE) is None
        assert store.consume("   ", PURPOSE_SIGN_HISTORY_SSE) is None

    def test_unknown_ticket_rejected(self):
        store = StreamTicketStore()
        assert store.consume("never-issued", PURPOSE_SIGN_HISTORY_SSE) is None

    def test_expired_ticket_rejected(self):
        store = StreamTicketStore(ttl=0.05)
        ticket = store.issue(user_id=1, username="u", purpose=PURPOSE_SIGN_HISTORY_SSE)
        time.sleep(0.08)
        assert store.consume(ticket, PURPOSE_SIGN_HISTORY_SSE) is None

    def test_tickets_are_opaque_and_unique(self):
        """票据是随机串，不含可解码的用户信息，且不重复。"""
        store = StreamTicketStore()
        seen = {
            store.issue(user_id=i, username=f"u{i}", purpose=PURPOSE_SIGN_HISTORY_SSE)
            for i in range(50)
        }
        assert len(seen) == 50
        for ticket in seen:
            assert "." not in ticket
            assert len(ticket) >= 32

    def test_overflow_evicts_oldest(self):
        store = StreamTicketStore(max_entries=2)
        first = store.issue(user_id=1, username="u", purpose=PURPOSE_SIGN_HISTORY_SSE)
        store.issue(user_id=2, username="u", purpose=PURPOSE_SIGN_HISTORY_SSE)
        store.issue(user_id=3, username="u", purpose=PURPOSE_SIGN_HISTORY_SSE)
        # 最旧的一张被 LRU 驱逐，兑换失败
        assert store.consume(first, PURPOSE_SIGN_HISTORY_SSE) is None

    def test_clear(self):
        store = StreamTicketStore()
        for i in range(3):
            store.issue(user_id=i, username="u", purpose=PURPOSE_SIGN_HISTORY_SSE)
        assert store.clear() == 3
        assert store.clear() == 0

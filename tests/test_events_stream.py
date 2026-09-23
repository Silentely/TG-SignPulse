"""events 路由内部逻辑测试：SSE 字节编码、去重键、令牌校验与签到历史事件流。"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.api.routes import events
from backend.services import sign_history_events as she_mod
from backend.services import sign_tasks as sign_tasks_mod


class TestSignLogSseBytes:
    def test_created_at_fallback_and_message_fallback(self):
        item = {
            "account_name": "a",
            "task_name": "t",
            "success": 1,
            "message": "兜底文案",
            "time": "2026-07-31 10:00:00",
        }
        chunk = events._sign_log_sse_bytes(item)
        assert chunk.startswith(b"event: sign_log\n")
        assert chunk.endswith(b"\n\n")
        payload = json.loads(chunk.decode("utf-8").split("data: ", 1)[1])
        assert payload["created_at"] == "2026-07-31 10:00:00"
        assert payload["message"] == "兜底文案"
        assert payload["success"] is True
        assert payload["failure_category"] is None

    def test_bot_message_takes_precedence(self):
        item = {
            "account_name": "a",
            "task_name": "t",
            "success": False,
            "bot_message": "bot 回复",
            "message": "普通文案",
            "created_at": "x",
        }
        payload = json.loads(
            events._sign_log_sse_bytes(item).decode("utf-8").split("data: ", 1)[1]
        )
        assert payload["message"] == "bot 回复"
        assert payload["success"] is False

    def test_message_defaults_to_empty(self):
        payload = json.loads(
            events._sign_log_sse_bytes({}).decode("utf-8").split("data: ", 1)[1]
        )
        assert payload["message"] == ""
        assert payload["account_name"] is None


class TestEntryDedupeKey:
    def test_key_composition(self):
        item = {
            "account_name": "a",
            "task_name": "t",
            "created_at": "c",
            "success": True,
        }
        assert events._entry_dedupe_key(item) == "a|t|c|True"

    def test_time_field_used_when_created_at_missing(self):
        item = {"account_name": "a", "task_name": "t", "time": "x", "success": False}
        assert events._entry_dedupe_key(item) == "a|t|x|False"


class TestConsumeStreamTicket:

    def test_none_ticket_401(self, monkeypatch):
        monkeypatch.setattr(
            events.get_stream_ticket_store(), "consume", lambda *a, **k: None
        )
        with pytest.raises(HTTPException) as exc:
            events._consume_stream_ticket(None)
        assert exc.value.status_code == 401
        assert exc.value.detail == "Not authenticated"

    def test_blank_ticket_401(self, monkeypatch):
        monkeypatch.setattr(
            events.get_stream_ticket_store(), "consume", lambda *a, **k: None
        )
        with pytest.raises(HTTPException) as exc:
            events._consume_stream_ticket("   ")
        assert exc.value.status_code == 401
        assert exc.value.detail == "Not authenticated"

    def test_invalid_ticket_401(self, monkeypatch):
        monkeypatch.setattr(
            events.get_stream_ticket_store(), "consume", lambda *a, **k: None
        )
        with pytest.raises(HTTPException) as exc:
            events._consume_stream_ticket("bad-ticket")
        assert exc.value.status_code == 401
        assert exc.value.detail == "Invalid ticket"

    def test_valid_ticket_maps_principal_to_user(self, monkeypatch):
        principal = SimpleNamespace(user_id=7, username="admin")
        monkeypatch.setattr(
            events.get_stream_ticket_store(), "consume", lambda *a, **k: principal
        )
        user = events._consume_stream_ticket("good-ticket")
        assert user.id == 7
        assert user.username == "admin"

    def test_ticket_consumed_with_sse_purpose(self, monkeypatch):
        """兑换时必须以 SSE 用途校验，避免 WS 票据被挪用到 SSE 流上。"""
        seen: dict = {}
        principal = SimpleNamespace(user_id=1, username="u")

        def _consume(ticket, purpose, resource=""):
            seen["ticket"] = ticket
            seen["purpose"] = purpose
            seen["resource"] = resource
            return principal

        monkeypatch.setattr(events.get_stream_ticket_store(), "consume", _consume)
        events._consume_stream_ticket("  spaced-ticket  ")
        assert seen["ticket"] == "spaced-ticket"
        assert seen["purpose"] == events.PURPOSE_SIGN_HISTORY_SSE


class _FakeBus:
    """进程内事件总线替身：可控队列 + 退订记录。"""

    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.unsubscribed: list = []

    def subscribe(self):
        return self.queue

    def unsubscribe(self, q):
        self.unsubscribed.append(q)


@pytest.fixture()
def stream_env(monkeypatch):
    bus = _FakeBus()
    monkeypatch.setattr(she_mod, "subscribe", bus.subscribe)
    monkeypatch.setattr(she_mod, "unsubscribe", bus.unsubscribe)
    svc_calls: list[int] = []
    svc_results: list[list[dict]] = [[]]

    class _Svc:
        def get_recent_history_logs(self, limit):
            svc_calls.append(limit)
            if svc_results:
                return svc_results.pop(0)
            return []

    monkeypatch.setattr(sign_tasks_mod, "get_sign_task_service", lambda: _Svc())
    return SimpleNamespace(bus=bus, svc_calls=svc_calls, svc_results=svc_results)


class TestSignHistoryEventStream:
    @pytest.mark.asyncio()
    async def test_ready_first_seed_dedupe_and_push(self, stream_env):
        seed = {
            "account_name": "a",
            "task_name": "t1",
            "created_at": "2026-07-31 00:00:00",
            "success": True,
        }
        # 第一次调用（冷启动种子）返回种子条目；其后无兜底（真实时钟 30s 未到）
        stream_env.svc_results[:] = [[seed]]
        gen = events._sign_history_event_stream()
        try:
            first = await asyncio.wait_for(gen.__anext__(), 1.0)
            assert first == b"event: ready\ndata: {}\n\n"
            # 与种子同键的条目被去重，只有新条目产出 sign_log
            stream_env.bus.queue.put_nowait(dict(seed))
            stream_env.bus.queue.put_nowait(
                {
                    "account_name": "a",
                    "task_name": "t2",
                    "created_at": "2026-07-31 00:01:00",
                    "success": False,
                    "message": "失败原因",
                }
            )
            second = await asyncio.wait_for(gen.__anext__(), 1.0)
            assert b"t2" in second
            assert b"t1" not in second
        finally:
            await gen.aclose()
        assert stream_env.bus.unsubscribed == [stream_env.bus.queue]

    @pytest.mark.asyncio()
    async def test_seed_failure_still_emits_ready(self, stream_env, monkeypatch):
        def _boom():
            raise RuntimeError("service down")

        monkeypatch.setattr(sign_tasks_mod, "get_sign_task_service", _boom)
        gen = events._sign_history_event_stream()
        try:
            first = await asyncio.wait_for(gen.__anext__(), 1.0)
            assert first == b"event: ready\ndata: {}\n\n"
        finally:
            await gen.aclose()

    @pytest.mark.asyncio()
    async def test_fallback_scan_error_tolerated(self, stream_env, monkeypatch):
        # 时钟放大触发兜底扫描；服务抛错时仅记 debug，不中断流
        clock = {"t": 0.0}

        def _monotonic():
            clock["t"] += 20.0
            return clock["t"]

        monkeypatch.setattr(events, "time", SimpleNamespace(monotonic=_monotonic))

        class _BoomSvc:
            def get_recent_history_logs(self, limit):
                raise RuntimeError("index broken")

        monkeypatch.setattr(
            sign_tasks_mod, "get_sign_task_service", lambda: _BoomSvc()
        )
        gen = events._sign_history_event_stream()
        try:
            ready = await asyncio.wait_for(gen.__anext__(), 1.0)
            assert ready.startswith(b"event: ready")
            stream_env.bus.queue.put_nowait(
                {
                    "account_name": "a",
                    "task_name": "t1",
                    "time": "2026-07-31 00:01:00",
                    "success": True,
                }
            )
            pushed = await asyncio.wait_for(gen.__anext__(), 1.0)
            assert b"t1" in pushed
            # 兜底扫描异常被吞掉，心跳照常
            keepalive = await asyncio.wait_for(gen.__anext__(), 1.0)
            assert keepalive == b": keep-alive\n\n"
        finally:
            await gen.aclose()

    @pytest.mark.asyncio()
    async def test_fallback_scan_and_keepalive(self, stream_env, monkeypatch):
        # 人为放大时钟：每调用一次 monotonic 前进 20 秒，立即触发兜底扫描与心跳
        clock = {"t": 0.0}

        def _monotonic():
            clock["t"] += 20.0
            return clock["t"]

        monkeypatch.setattr(events, "time", SimpleNamespace(monotonic=_monotonic))
        fallback_entry = {
            "account_name": "b",
            "task_name": "t-fallback",
            "time": "2026-07-31 00:02:00",
            "success": True,
            "message": "兜底补推",
        }
        # 养子首次为空，第二次（兜底扫描）返回补推条目
        stream_env.svc_results[:] = [[], [fallback_entry]]
        gen = events._sign_history_event_stream()
        try:
            ready = await asyncio.wait_for(gen.__anext__(), 1.0)
            assert ready.startswith(b"event: ready")
            stream_env.bus.queue.put_nowait(
                {
                    "account_name": "a",
                    "task_name": "t1",
                    "time": "2026-07-31 00:01:00",
                    "success": True,
                }
            )
            pushed = await asyncio.wait_for(gen.__anext__(), 1.0)
            assert b"t1" in pushed
            fallback = await asyncio.wait_for(gen.__anext__(), 1.0)
            assert b"t-fallback" in fallback
            keepalive = await asyncio.wait_for(gen.__anext__(), 1.0)
            assert keepalive == b": keep-alive\n\n"
        finally:
            await gen.aclose()

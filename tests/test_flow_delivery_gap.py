import asyncio
import time

import pytest

from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_engine import PulseFlowEngine
from tg_signer.core.flow_event_bus import TelegramEventBus, TelegramMessageEvent
from tg_signer.core.flow_models import NodeStatus, WaitEventNode
from tg_signer.core.signer_runner import SignerRunnerMixin


def event(message_id, *, chat_id=1, occurred_at=None, text="success"):
    return TelegramMessageEvent(
        event_id="",
        chat_id=chat_id,
        message_thread_id=None,
        message_id=message_id,
        sender_id=2,
        event_type="NEW_MESSAGE",
        text=text,
        occurred_at=time.time() if occurred_at is None else occurred_at,
    )


@pytest.mark.asyncio
async def test_live_overflow_records_count_and_time_range():
    bus = TelegramEventBus(queue_size=1)
    queue = bus.subscribe(1)
    events = [event(i) for i in range(3)]
    for item in events:
        await bus.publish(item)
    stats = bus.get_delivery_stats(queue)
    assert stats.dropped_events == 2
    assert stats.oldest_dropped_at == events[1].occurred_at
    assert stats.newest_dropped_at == events[2].occurred_at
    assert queue.get_nowait() == events[0]


@pytest.mark.asyncio
async def test_backfill_overflow_prevents_false_success():
    bus = TelegramEventBus(queue_size=1)
    for i in range(3):
        await bus.publish(event(i + 1))
    node = WaitEventNode(
        id="wait",
        metadata={"chat_id": 1, "min_message_id": 0},
        success_patterns=["success"],
        timeout_seconds=0.01,
    )
    result = await PulseFlowEngine(event_bus=bus)._run_wait_event_node(
        node, ScopedFlowContext(), bus
    )
    assert result.status == NodeStatus.FAILED
    assert result.details["failure_category"] == "event_gap"
    assert result.details["event_gap"]["dropped_events"] == 2


@pytest.mark.asyncio
async def test_live_gap_is_distinct_from_timeout():
    bus = TelegramEventBus(queue_size=1)
    node = WaitEventNode(id="wait", metadata={"chat_id": 1}, timeout_seconds=0.1)
    waiter = asyncio.create_task(
        PulseFlowEngine()._run_wait_event_node(node, ScopedFlowContext(), bus)
    )
    await asyncio.sleep(0)
    await bus.publish(event(1, text="success"))
    await bus.publish(event(2, text="failure"))
    result = await waiter
    assert result.status == NodeStatus.FAILED
    assert result.details["failure_category"] == "event_gap"


@pytest.mark.asyncio
async def test_histories_are_bounded_and_active_scope_is_preserved():
    bus = TelegramEventBus(max_history_keys=2, buffer_ttl_seconds=10)
    queue = bus.subscribe(1)
    for chat in range(1, 6):
        await bus.publish(event(1, chat_id=chat))
    assert len(bus._history_buffers) <= 2
    assert (1, None) in bus._history_buffers
    assert bus.evict_inactive_histories(now=time.time() + 20) == 1
    assert list(bus._history_buffers) == [(1, None)]
    bus.unsubscribe(1, None, queue)
    assert bus.evict_inactive_histories(now=time.time() + 20) == 1


@pytest.mark.asyncio
async def test_publish_task_drain_completes_or_cancels_pending_tasks():
    runner = SignerRunnerMixin()
    completed = []

    async def publish():
        await asyncio.sleep(0)
        completed.append(True)

    runner._track_event_publish(publish())
    await runner._drain_event_publish_tasks(timeout=0.1)
    assert completed == [True]
    assert not runner._event_publish_tasks
    task = runner._track_event_publish(asyncio.sleep(60))
    await runner._drain_event_publish_tasks(timeout=0.001)
    assert task.cancelled()
    assert not runner._event_publish_tasks

"""签到历史进程内事件总线测试。"""

from __future__ import annotations

import asyncio

import pytest

from backend.services.sign_history_events import (
    publish_sign_history,
    reset_for_tests,
    subscribe,
    subscriber_count,
    unsubscribe,
)
from backend.services.sign_task_history_index import (
    append_index_entry,
    build_index_entry,
    clear_memory_cache,
)


@pytest.fixture(autouse=True)
def _clean_bus():
    reset_for_tests()
    clear_memory_cache()
    yield
    reset_for_tests()
    clear_memory_cache()


@pytest.mark.asyncio
async def test_publish_reaches_subscriber():
    q = subscribe()
    assert subscriber_count() == 1
    publish_sign_history(
        {
            "time": "2026-07-26T12:00:00",
            "account_name": "a1",
            "task_name": "t1",
            "success": True,
            "message": "ok",
            "failure_category": "",
        }
    )
    item = await asyncio.wait_for(q.get(), timeout=1.0)
    assert item["account_name"] == "a1"
    assert item["task_name"] == "t1"
    assert item["success"] is True
    unsubscribe(q)
    assert subscriber_count() == 0


@pytest.mark.asyncio
async def test_append_index_publishes_event(tmp_path):
    q = subscribe()
    entry = build_index_entry(
        time="2026-07-26T13:00:00",
        account_name="acc",
        task_name="daily",
        success=False,
        message="fail",
        failure_category="network",
    )
    append_index_entry(tmp_path, entry)
    item = await asyncio.wait_for(q.get(), timeout=1.0)
    assert item["task_name"] == "daily"
    assert item["failure_category"] == "network"
    unsubscribe(q)


@pytest.mark.asyncio
async def test_no_subscribers_publish_is_noop():
    assert subscriber_count() == 0
    publish_sign_history(
        {"time": "t", "account_name": "a", "task_name": "x", "success": True}
    )


@pytest.mark.asyncio
async def test_bounded_queue_overflow_drop_oldest():
    """测试队列达到 maxsize 上限时，触发 drop-oldest 丢弃最老条目而不阻塞发布者。"""
    q = subscribe()
    total_messages = 80
    for i in range(total_messages):
        publish_sign_history(
            {
                "time": f"2026-07-26T12:00:{i:02d}",
                "account_name": "acc",
                "task_name": f"task_{i}",
                "success": True,
                "message": f"msg_{i}",
            }
        )

    # 调度让 loop.call_soon_threadsafe 回调执行
    await asyncio.sleep(0.02)

    # 队列长度必须受到严格有界约束（64）
    assert q.qsize() == 64

    # 弹出的首个元素应当是最旧但未被挤压丢弃的元素（即第 80 - 64 = 16 号）
    first_item = await asyncio.wait_for(q.get(), timeout=1.0)
    assert first_item["task_name"] == "task_16"

    # 清理注销
    unsubscribe(q)
    assert subscriber_count() == 0

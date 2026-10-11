# tests/test_flow_event_bus.py
import asyncio
import time

import pytest

from tg_signer.core.flow_event_bus import TelegramEventBus, TelegramMessageEvent


@pytest.mark.asyncio
async def test_event_bus_thread_isolation_and_watermark():
    bus = TelegramEventBus(buffer_size=10, buffer_ttl_seconds=300)

    # 模拟先回包（Bot 秒回在订阅前到达）
    ev_early = TelegramMessageEvent(
        event_id="ev_1",
        chat_id=1001,
        message_thread_id=5,
        message_id=201,
        sender_id=888,
        event_type="NEW_MESSAGE",
        text="打卡成功！",
        occurred_at=time.time(),
    )
    await bus.publish(ev_early)

    # 订阅带 min_message_id=200 的水位线回补
    queue = bus.subscribe(chat_id=1001, message_thread_id=5, min_message_id=200)

    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event.text == "打卡成功！"
    assert event.message_id == 201

    # 验证不同 thread 隔离
    queue_other_thread = bus.subscribe(chat_id=1001, message_thread_id=9)
    assert queue_other_thread.empty()


@pytest.mark.asyncio
async def test_event_bus_clear_and_get_history():
    bus = TelegramEventBus(buffer_size=5, buffer_ttl_seconds=300)

    ev1 = TelegramMessageEvent(
        event_id="ev_1",
        chat_id=2001,
        message_thread_id=None,
        message_id=10,
        sender_id=999,
        event_type="NEW_MESSAGE",
        text="msg 1",
        occurred_at=time.time(),
    )
    ev2 = TelegramMessageEvent(
        event_id="ev_2",
        chat_id=2001,
        message_thread_id=None,
        message_id=20,
        sender_id=999,
        event_type="NEW_MESSAGE",
        text="msg 2",
        occurred_at=time.time(),
    )
    await bus.publish(ev1)
    await bus.publish(ev2)

    history = bus.get_history(chat_id=2001)
    assert len(history) == 2
    assert history[0].text == "msg 1"
    assert history[1].text == "msg 2"

    filtered_history = bus.get_history(chat_id=2001, min_message_id=15)
    assert len(filtered_history) == 1
    assert filtered_history[0].text == "msg 2"

    # 清空特定会话
    bus.clear(chat_id=2001)
    assert len(bus.get_history(chat_id=2001)) == 0

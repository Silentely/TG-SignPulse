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

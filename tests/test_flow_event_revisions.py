import time
from types import SimpleNamespace

import pytest

from tg_signer.core.flow_compat import FlowCompatibilityBridge
from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_event_bus import TelegramEventBus, TelegramMessageEvent


def make_event(text, buttons=(), thread_id=1):
    return TelegramMessageEvent(
        event_id="same-message",
        chat_id=123,
        message_thread_id=thread_id,
        message_id=10,
        sender_id=7,
        event_type="EDITED_MESSAGE",
        text=text,
        occurred_at=time.time(),
        button_snapshot=buttons,
    )


@pytest.mark.asyncio
async def test_same_message_edits_have_distinct_revisions_and_event_ids():
    bus = TelegramEventBus()
    await bus.publish(make_event("A", (("Continue", "a"),)))
    await bus.publish(make_event("A", (("Continue", "b"),)))
    await bus.publish(make_event("B", (("Continue", "b"),)))

    events = bus.get_history(123, 1, limit=10)
    assert len({event.message_revision for event in events}) == 3
    assert len({event.event_id for event in events}) == 3


class _FakeBridgeChat:
    chat_id = 123


def test_compatibility_bridge_reads_and_writes_topic_scoped_state():
    runner = SimpleNamespace(
        context=SimpleNamespace(
            chat_messages={(123, 1): {10: "thread one"}, (123, 2): {10: "thread two"}},
            topic_last_output={},
            last_output="legacy",
            last_received_text="legacy",
        )
    )
    bridge = FlowCompatibilityBridge(runner, _FakeBridgeChat())

    assert bridge.get_chat_messages(123, thread_id=1) == {10: "thread one"}
    assert bridge.get_chat_messages(123, thread_id=2) == {10: "thread two"}
    bridge.set_last_output("one", chat_id=123, thread_id=1)
    bridge.set_last_output("two", chat_id=123, thread_id=2)
    assert runner.context.topic_last_output[(123, 1)] == "one"
    assert runner.context.topic_last_output[(123, 2)] == "two"
    assert bridge.get_chat_messages(123) == {}


def test_scoped_flow_context_keeps_topic_outputs_separate_and_legacy_compatible():
    context = ScopedFlowContext()
    context.set_last_output("one", chat_id=123, thread_id=1)
    context.set_last_output("two", chat_id=123, thread_id=2)
    assert context.topic_last_outputs == {(123, 1): "one", (123, 2): "two"}
    assert context.last_output == ""

    context.set_last_output("legacy")
    restored = ScopedFlowContext.from_dict(context.to_dict())
    assert restored.last_output == "legacy"
    assert restored.topic_last_outputs == {(123, 1): "one", (123, 2): "two"}

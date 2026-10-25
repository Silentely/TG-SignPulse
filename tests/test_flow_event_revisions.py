import asyncio
import time
from types import SimpleNamespace

import pytest

from tg_signer.config import ReplyByCalculationProblemAction, SendTextAction, SignChatV3
from tg_signer.core.context import UserSignerWorkerContext
from tg_signer.core.flow_compat import FlowCompatibilityBridge
from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_engine import PulseFlowEngine
from tg_signer.core.flow_event_bus import TelegramEventBus, TelegramMessageEvent
from tg_signer.core.flow_models import NodeStatus, WaitEventNode
from tg_signer.core.signer_matchers import SignerMatchersMixin
from tg_signer.core.signer_runner import SignerRunnerMixin
from tg_signer.semantic import runtime_port
from tg_signer.semantic.models import Decision


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


@pytest.mark.asyncio
async def test_identical_message_revision_is_published_once():
    bus = TelegramEventBus()
    first = make_event("A", (("Continue", "a"),))
    repeat = make_event("A", (("Continue", "a"),))
    queue = bus.subscribe(123, 1, event_type="ANY")

    await bus.publish(first)
    await bus.publish(repeat)

    assert first.event_id == repeat.event_id
    assert [item.event_id for item in bus.get_history(123, 1)] == [first.event_id]
    assert queue.qsize() == 1


@pytest.mark.asyncio
async def test_restored_message_content_after_an_edit_is_delivered_again():
    bus = TelegramEventBus()
    events = [make_event(text) for text in ("A", "B", "A")]
    queue = bus.subscribe(123, 1, event_type="ANY")
    for event in events:
        await bus.publish(event)

    assert len(bus.get_history(123, 1)) == 3
    assert queue.qsize() == 3
    assert events[0].event_id == events[2].event_id


@pytest.mark.asyncio
async def test_runner_keeps_same_message_id_in_two_topics_separate():
    bus = TelegramEventBus()
    runner = SimpleNamespace(
        context=SimpleNamespace(
            sign_chats={
                123: [
                    SimpleNamespace(message_thread_id=1),
                    SimpleNamespace(message_thread_id=2),
                ]
            },
            chat_messages={},
            topic_last_received_text={},
            last_received_text="",
        ),
        _event_bus=bus,
        log=lambda *args, **kwargs: None,
    )
    for thread_id, content in ((1, "first"), (2, "second")):
        message = SimpleNamespace(
            chat=SimpleNamespace(id=123),
            id=10,
            message_thread_id=thread_id,
            text=content,
            caption=None,
            from_user=SimpleNamespace(id=7),
            reply_markup=None,
        )
        await SignerRunnerMixin._on_message(runner, None, message)
    await asyncio.sleep(0)

    assert runner.context.chat_messages[(123, 1)][10].text == "first"
    assert runner.context.chat_messages[(123, 2)][10].text == "second"
    assert 123 not in runner.context.chat_messages
    assert runner.context.topic_last_received_text == {
        (123, 1): "first",
        (123, 2): "second",
    }
    assert len(bus.get_history(123, 1)) == 1
    assert len(bus.get_history(123, 2)) == 1


@pytest.mark.asyncio
async def test_matcher_snapshot_reads_only_selected_topic_cache():
    async def empty_history(*args, **kwargs):
        if False:
            yield None

    matcher = SignerMatchersMixin()
    matcher.app = SimpleNamespace(get_chat_history=empty_history)
    matcher.log = lambda *args, **kwargs: None
    first = SimpleNamespace(
        id=10,
        message_thread_id=1,
        text="one",
        caption=None,
        edit_date=None,
        reply_markup=None,
    )
    second = SimpleNamespace(
        id=20,
        message_thread_id=2,
        text="two",
        caption=None,
        edit_date=None,
        reply_markup=None,
    )
    plain = SimpleNamespace(
        id=30,
        message_thread_id=None,
        text="plain",
        caption=None,
        edit_date=None,
        reply_markup=None,
    )
    matcher.context = SimpleNamespace(
        chat_messages={(123, 1): {10: first}, (123, 2): {20: second}, 123: {30: plain}}
    )

    topic_state = await matcher._chat_state_snapshot(
        SimpleNamespace(chat_id=123, message_thread_id=2), history_limit=5
    )
    plain_state = await matcher._chat_state_snapshot(
        SimpleNamespace(chat_id=123, message_thread_id=None), history_limit=5
    )

    assert set(topic_state) == {20}
    assert set(plain_state) == {30}


@pytest.mark.asyncio
async def test_matcher_candidate_and_waiters_read_topic_cache():
    async def empty_history(*args, **kwargs):
        if False:
            yield None

    matcher = SignerMatchersMixin()
    matcher.app = SimpleNamespace(get_chat_history=empty_history)
    matcher.log = lambda *args, **kwargs: None
    matcher.context = SimpleNamespace(
        chat_messages={
            (123, 2): {
                20: SimpleNamespace(
                    id=20,
                    message_thread_id=2,
                    text="签到成功",
                    caption=None,
                    edit_date=None,
                    reply_markup=None,
                )
            }
        },
        stop_reason=None,
    )
    chat = SimpleNamespace(chat_id=123, message_thread_id=2)
    action = ReplyByCalculationProblemAction()

    assert await matcher._chat_has_action_candidate(chat, action, history_limit=5)
    assert await matcher._wait_for_next_action_candidate(
        chat, action, {}, history_limit=5, timeout=0.01
    )
    assert await matcher._wait_for_terminal_success(
        chat, {}, history_limit=5, timeout=0.01
    )
    assert matcher.context.stop_reason == "签到成功"


@pytest.mark.asyncio
async def test_unthreaded_config_receives_topic_reply_in_legacy_cache():
    bus = TelegramEventBus()
    legacy_queue = bus.subscribe(123, None, event_type="ANY")
    topic_queue = bus.subscribe(123, 2, event_type="ANY")
    runner = SimpleNamespace(
        context=SimpleNamespace(
            sign_chats={123: [SimpleNamespace(message_thread_id=None)]},
            chat_messages={},
            topic_last_received_text={},
            last_received_text="",
        ),
        _event_bus=bus,
        log=lambda *args, **kwargs: None,
    )
    message = SimpleNamespace(
        chat=SimpleNamespace(id=123),
        id=10,
        message_thread_id=2,
        text="topic reply",
        caption=None,
        from_user=SimpleNamespace(id=7),
        reply_markup=None,
    )

    await SignerRunnerMixin._on_message(runner, None, message)
    await asyncio.sleep(0)

    assert runner.context.chat_messages[123][10] is message
    assert runner.context.chat_messages[(123, 2)][10] is message
    assert runner.context.last_received_text == "topic reply"
    assert legacy_queue.get_nowait().text == "topic reply"
    assert topic_queue.get_nowait().text == "topic reply"
    context = ScopedFlowContext()
    context.system["chat_id"] = 123
    outcome = await PulseFlowEngine(bus)._run_wait_event_node(
        WaitEventNode(
            id="wait",
            event_type="NEW_MESSAGE",
            success_patterns=["topic reply"],
            timeout_seconds=1,
            metadata={"chat_id": 123},
        ),
        context,
        bus,
    )
    assert outcome.status == NodeStatus.SUCCESS


@pytest.mark.asyncio
async def test_topic_only_config_does_not_publish_to_legacy_subscription():
    bus = TelegramEventBus()
    legacy_queue = bus.subscribe(123, None, event_type="ANY")
    runner = SimpleNamespace(
        context=SimpleNamespace(
            sign_chats={123: [SimpleNamespace(message_thread_id=2)]},
            chat_messages={},
            topic_last_received_text={},
            last_received_text="",
        ),
        _event_bus=bus,
        log=lambda *args, **kwargs: None,
    )
    message = SimpleNamespace(
        chat=SimpleNamespace(id=123),
        id=11,
        message_thread_id=2,
        text="scoped",
        caption=None,
        from_user=SimpleNamespace(id=7),
        reply_markup=None,
    )

    await SignerRunnerMixin._on_message(runner, None, message)
    await asyncio.sleep(0)

    assert legacy_queue.empty()
    assert bus.get_history(123) == []
    assert len(bus.get_history(123, 2)) == 1


@pytest.mark.asyncio
async def test_observe_request_key_changes_for_message_edits(monkeypatch):
    requests = []
    runtime = SimpleNamespace(
        enqueue_observation=lambda request, **kwargs: requests.append(request)
    )
    monkeypatch.setattr(runtime_port, "_SEMANTIC_RUNTIME_PROVIDER", lambda: runtime)
    node = WaitEventNode(
        id="wait",
        event_type="EDITED_MESSAGE",
        success_patterns=["ok"],
        semantic_result={"mode": "observe", "goal": "confirmed"},
        timeout_seconds=1,
        metadata={"chat_id": 123, "message_thread_id": 1},
    )

    for text in ("ok first", "ok second"):
        bus = TelegramEventBus()
        event = make_event(text)
        await bus.publish(event)
        context = ScopedFlowContext(account={"name": "account"})
        context.system["chat_id"] = 123
        outcome = await PulseFlowEngine(bus)._run_wait_event_node(node, context, bus)
        assert outcome.status == NodeStatus.SUCCESS
        assert requests[-1].request_key.endswith(
            f":{event.event_type}:{event.message_id}:{event.message_revision}"
        )

    assert requests[0].request_key != requests[1].request_key


@pytest.mark.asyncio
async def test_assist_request_key_changes_for_message_edits(monkeypatch):
    requests = []

    async def evaluate(request, **kwargs):
        requests.append(request)
        return Decision(
            status="ok",
            selected="success",
            probabilities={"success": 0.99, "failure": 0.01},
        )

    runtime = SimpleNamespace(
        service=SimpleNamespace(evaluate=evaluate),
        record_observation=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(runtime_port, "_SEMANTIC_RUNTIME_PROVIDER", lambda: runtime)
    node = WaitEventNode(
        id="wait",
        event_type="EDITED_MESSAGE",
        success_patterns=["never matches"],
        semantic_result={"mode": "assist", "goal": "confirmed"},
        timeout_seconds=1,
        metadata={"chat_id": 123, "message_thread_id": 1},
    )

    for text in ("edited first", "edited second"):
        bus = TelegramEventBus()
        event = make_event(text)
        await bus.publish(event)
        context = ScopedFlowContext(account={"name": "account"})
        context.system["chat_id"] = 123
        outcome = await PulseFlowEngine(bus)._run_wait_event_node(node, context, bus)
        assert outcome.status == NodeStatus.SUCCESS
        assert requests[-1].request_key.endswith(
            f":{event.event_type}:{event.message_id}:{event.message_revision}"
        )

    assert requests[0].request_key != requests[1].request_key


@pytest.mark.asyncio
async def test_pulseflow_failure_keeps_topic_received_text_scoped(monkeypatch):
    async def failed_run(self, graph, context, executor, **kwargs):
        context.last_output = "topic failure"
        return {"status": "failed", "error": "reply did not match", "steps": 1}

    monkeypatch.setattr(PulseFlowEngine, "run", failed_run)
    runner = SignerRunnerMixin()
    runner.context = UserSignerWorkerContext(sign_chats={}, chat_messages={})
    runner.context.last_output = "legacy"
    runner.context.last_received_text = "legacy"
    runner.log = lambda *args, **kwargs: None
    chat = SignChatV3(
        chat_id=123, message_thread_id=1, actions=[SendTextAction(text="/checkin")]
    )

    with pytest.raises(RuntimeError, match="reply did not match"):
        await runner._run_pulseflow_chat(chat, engine_source="task")

    assert runner.context.topic_last_output[(123, 1)] == "topic failure"
    assert runner.context.topic_last_received_text[(123, 1)] == "topic failure"
    assert runner.context.last_output == "legacy"
    assert runner.context.last_received_text == "legacy"


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

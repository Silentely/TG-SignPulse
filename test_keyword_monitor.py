import sys
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(
    sys.version_info >= (3, 14),
    reason="pyrogram is not importable on Python 3.14 in the local test env",
)


def test_keyword_action_accepts_forward_and_continue_actions():
    from tg_signer.config import KeywordNotifyAction

    action = KeywordNotifyAction.parse_obj(
        {
            "action": 8,
            "keywords": ["code"],
            "push_channel": "continue",
            "continue_chat_id": -100456,
            "continue_actions": [{"action": 1, "text": "{keyword}"}],
        }
    )

    assert action.push_channel == "continue"
    assert action.continue_actions == [{"action": 1, "text": "{keyword}"}]


def test_keyword_action_requires_update_enabled_client():
    from backend.services.sign_tasks import SignTaskService
    from tg_signer.config import KeywordNotifyAction, SignChatV3, SignConfigV3

    action = KeywordNotifyAction.parse_obj({"action": 8, "keywords": ["code"]})
    chat = SignChatV3(chat_id=-100123, actions=[action])
    config = SignConfigV3(chats=[chat], sign_at="0 0 * * *")

    assert chat.requires_updates is True
    assert config.requires_updates is True
    assert (
        SignTaskService._task_requires_updates(
            {"chats": [{"actions": [{"action": 8, "keywords": ["code"]}]}]}
        )
        is True
    )


def test_keyword_continue_action_template_rendering():
    from backend.services.keyword_monitor import _render_action_templates

    rendered = _render_action_templates(
        {"action": 1, "text": "hit={keyword}; from=${sender}; raw={message}"},
        {"keyword": "ABC", "sender": "tester", "message": "ABC 123"},
    )

    assert rendered["text"] == "hit=ABC; from=tester; raw=ABC 123"


def test_message_matches_thread_uses_reply_to_message_id_fallback():
    from backend.services.keyword_monitor import _message_matches_thread

    message = SimpleNamespace(
        message_thread_id=None,
        direct_messages_chat_topic_id=None,
        reply_to_top_message_id=None,
        reply_to_message_id=67,
        topic=None,
    )

    assert _message_matches_thread(message, 67) is True
    assert _message_matches_thread(message, 68) is False


def test_message_matches_thread_uses_direct_messages_topic_id():
    from backend.services.keyword_monitor import _message_matches_thread

    message = SimpleNamespace(
        message_thread_id=None,
        direct_messages_chat_topic_id=67,
        reply_to_top_message_id=None,
        reply_to_message_id=None,
        topic=None,
    )

    assert _message_matches_thread(message, 67) is True
    assert _message_matches_thread(message, 68) is False


def test_keyword_continue_action_supports_reply_keyboard_ai_choice():
    from backend.services.keyword_monitor import (
        ReplyKeyboardMarkup,
        _message_supports_continue_action,
    )

    message = SimpleNamespace(
        photo=object(),
        reply_markup=ReplyKeyboardMarkup([["院", "因"], ["外", "里"]]),
    )

    assert _message_supports_continue_action(message, {"action": 4}) is True


@pytest.mark.asyncio
async def test_keyword_continue_click_does_not_send_button_text(monkeypatch):
    from backend.services import keyword_monitor

    async def fast_sleep(_seconds):
        return None

    class FakeClient:
        def __init__(self):
            self.sent_messages = []

        async def send_message(self, chat_id, text, **kwargs):
            self.sent_messages.append((chat_id, text, kwargs))

        async def get_chat_history(self, chat_id, limit):
            if False:
                yield None

    monkeypatch.setattr(keyword_monitor.asyncio, "sleep", fast_sleep)

    client = FakeClient()
    service = keyword_monitor.KeywordMonitorService()
    result = await service._execute_continue_action(
        client,
        -100123,
        None,
        {"action": 3, "text": "签到"},
        timeout=0.01,
    )

    assert result is False
    assert client.sent_messages == []


@pytest.mark.asyncio
async def test_keyword_continue_actions_wait_before_delayed_step(monkeypatch):
    from backend.services import keyword_monitor

    sleep_calls = []
    executed_actions = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
        return None

    async def fake_execute_continue_action(
        client,
        target_chat_id,
        target_thread_id,
        action,
        timeout=None,
        next_action=None,
    ):
        executed_actions.append((target_chat_id, target_thread_id, action.get("text")))
        return True

    async def fake_warm_chat(_client, _chat_id):
        return None

    monkeypatch.setattr(keyword_monitor.asyncio, "sleep", fake_sleep)

    service = keyword_monitor.KeywordMonitorService()
    monkeypatch.setattr(service, "_execute_continue_action", fake_execute_continue_action)
    monkeypatch.setattr(service, "_warm_chat", fake_warm_chat)

    rule = keyword_monitor.KeywordMonitorRule(
        account_name="acct",
        task_name="delay-demo",
        chat_id=-100123,
        chat_name="Demo",
        message_thread_id=None,
        action={
            "push_channel": "continue",
            "continue_action_interval": 1,
            "continue_actions": [
                {"action": 1, "text": "first"},
                {"action": 1, "text": "second", "delay": "5"},
            ],
        },
    )
    message = SimpleNamespace(
        chat=SimpleNamespace(id=-100123),
        message_thread_id=None,
        direct_messages_chat_topic_id=None,
        reply_to_top_message_id=None,
        reply_to_message_id=None,
        topic=None,
    )

    await service._execute_continue_actions(
        account_name="acct",
        client=object(),
        rule=rule,
        message=message,
        variables={},
    )

    assert executed_actions == [
        (-100123, None, "first"),
        (-100123, None, "second"),
    ]
    assert sleep_calls == [5.0]
    monitor_logs = service.get_task_logs("delay-demo", "acct")
    assert any("等待 5 秒后执行" in line for line in monitor_logs)

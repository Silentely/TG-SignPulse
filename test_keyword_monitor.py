import sys

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

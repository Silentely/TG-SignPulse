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


def test_keyword_continue_action_template_rendering():
    from backend.services.keyword_monitor import _render_action_templates

    rendered = _render_action_templates(
        {"action": 1, "text": "hit={keyword}; from=${sender}; raw={message}"},
        {"keyword": "ABC", "sender": "tester", "message": "ABC 123"},
    )

    assert rendered["text"] == "hit=ABC; from=tester; raw=ABC 123"

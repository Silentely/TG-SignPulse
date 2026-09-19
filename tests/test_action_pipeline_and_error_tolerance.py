from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_signer.config import (
    SendTextAction,
    SignChatV3,
    SupportAction,
)
from tg_signer.core.context import UserSignerWorkerContext
from tg_signer.core.signer_runner import SignerRunnerMixin


class DummySigner(SignerRunnerMixin):
    def __init__(self):
        self.app = MagicMock()
        self.app.get_chat = AsyncMock()
        self.me = MagicMock()
        self.me.phone_number = "+123456789"
        self.me.username = "test_user"
        self.me.first_name = "Test"
        self._account = "account_demo"
        self.tasks_dir = MagicMock()
        self.context = UserSignerWorkerContext(
            sign_chats={},
            chat_messages={},
        )
        self.logs = []

    def log(self, msg, level="INFO"):
        self.logs.append((level, msg))

    def _describe_chat_run(self, chat):
        return f"Running chat {chat.chat_id}"

    def _set_current_action_context(self, index, total, action):
        return f"Action {index}/{total}: {action.action.desc if hasattr(action.action, 'desc') else action.action}"

    def _current_action_step_label(self):
        return "[Step]"

    def _resolve_action_delay(self, action, interval):
        return 0.0

    def _clear_current_action_context(self):
        pass

    def _is_transient_step_error(self, exc):
        return False

    async def wait_for(self, chat, action, next_action=None):
        return True


@pytest.mark.asyncio
async def test_action_dynamic_template_render():
    signer = DummySigner()
    chat = SignChatV3(
        chat_id=12345,
        name="test_group",
        actions=[
            SendTextAction(
                action=SupportAction.SEND_TEXT,
                text="Hello {{ account.name }}, today is {{ date }}",
            )
        ],
    )

    executed_actions = []

    async def mock_wait_for(c, a, next_action=None):
        executed_actions.append(a)
        return True

    signer.wait_for = mock_wait_for
    await signer.sign_a_chat(chat)

    assert len(executed_actions) == 1
    assert "Hello account_demo, today is" in executed_actions[0].text
    assert signer.context.last_output.startswith("Hello account_demo")


@pytest.mark.asyncio
async def test_action_skip_if_matched():
    signer = DummySigner()
    # 第一步输出包含 SIGNED_IN
    # 第二步配置 skip_if_matched="SIGNED_IN"
    # 第三步正常执行
    chat = SignChatV3(
        chat_id=12345,
        name="test_group",
        actions=[
            SendTextAction(action=SupportAction.SEND_TEXT, text="Already SIGNED_IN"),
            SendTextAction(
                action=SupportAction.SEND_TEXT,
                text="Should be skipped",
                skip_if_matched="SIGNED_IN",
            ),
            SendTextAction(action=SupportAction.SEND_TEXT, text="Final step"),
        ],
    )

    executed_actions = []

    async def mock_wait_for(c, a, next_action=None):
        executed_actions.append(a)
        return True

    signer.wait_for = mock_wait_for
    await signer.sign_a_chat(chat)

    # 第 2 步应被跳过，最终只执行了第 1 步和第 3 步
    assert len(executed_actions) == 2
    assert executed_actions[0].text.startswith("Already SIGNED_IN")
    assert executed_actions[1].text == "Final step"
    assert any("满足跳过条件" in log[1] for log in signer.logs)


@pytest.mark.asyncio
async def test_action_skip_if_matched_supports_regex_fallback():
    signer = DummySigner()
    chat = SignChatV3(
        chat_id=12345,
        name="test_group",
        actions=[
            SendTextAction(action=SupportAction.SEND_TEXT, text="Result: CODE_123"),
            SendTextAction(
                action=SupportAction.SEND_TEXT,
                text="Should be skipped",
                skip_if_matched=r"CODE_\d+",
            ),
        ],
    )

    executed_actions = []

    async def mock_wait_for(c, a, next_action=None):
        executed_actions.append(a)
        return True

    signer.wait_for = mock_wait_for
    await signer.sign_a_chat(chat)

    assert [action.text for action in executed_actions] == ["Result: CODE_123"]


@pytest.mark.asyncio
async def test_action_continue_on_error():
    signer = DummySigner()
    # 第一步失败，但 continue_on_error=True
    # 第二步成功
    chat = SignChatV3(
        chat_id=12345,
        name="test_group",
        actions=[
            SendTextAction(
                action=SupportAction.SEND_TEXT,
                text="Will fail but continue",
                continue_on_error=True,
            ),
            SendTextAction(action=SupportAction.SEND_TEXT, text="Should execute next"),
        ],
    )

    executed_actions = []

    async def mock_wait_for(c, a, next_action=None):
        executed_actions.append(a)
        if "Will fail" in a.text:
            raise RuntimeError("Temporary error")
        return True

    signer.wait_for = mock_wait_for
    await signer.sign_a_chat(chat)

    assert len(executed_actions) == 2
    assert executed_actions[1].text == "Should execute next"
    assert any("容错继续" in log[1] for log in signer.logs)

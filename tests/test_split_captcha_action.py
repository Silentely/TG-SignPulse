from __future__ import annotations

import io
from collections import defaultdict
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_signer.compat import InlineKeyboardMarkup
from tg_signer.config import ChooseOptionByImageAction
from tg_signer.core.context import UserSignerWorkerContext
from tg_signer.core.signer_actions import SignerActionsMixin


class MockButton:
    def __init__(self, text: str, callback_data: str | None = None):
        self.text = text
        self.callback_data = callback_data or text


class DummySigner(SignerActionsMixin):
    def __init__(self):
        self.app = MagicMock()
        self.app.download_media = AsyncMock()
        self.context = UserSignerWorkerContext(
            sign_chats={},
            chat_messages=defaultdict(dict),
        )
        self.ai_tools = MagicMock()
        self.ai_tools.default_model = "test-ai-model"
        self.logs: list[tuple[str, str]] = []
        self._click_inline_button = AsyncMock(return_value=True)

    def get_ai_tools(self):
        return self.ai_tools

    def log(self, msg: str, level: str = "INFO"):
        self.logs.append((level, msg))

    def _log_received_target_message(self, message):
        pass

    def _resolve_message_thread_id(self, message):
        return None


def test_find_previous_photo_message_returns_nearest_same_chat_photo():
    signer = DummySigner()
    bot_sender = SimpleNamespace(id=1001)

    photo_msg_1 = SimpleNamespace(
        id=101,
        chat=SimpleNamespace(id=-100123),
        photo=SimpleNamespace(file_id="photo_file_1"),
        date=datetime(2026, 9, 19, 10, 0, 0),
        from_user=bot_sender,
        sender_chat=None,
    )
    photo_msg_2 = SimpleNamespace(
        id=102,
        chat=SimpleNamespace(id=-100123),
        photo=SimpleNamespace(file_id="photo_file_2"),
        date=datetime(2026, 9, 19, 10, 0, 10),
        from_user=bot_sender,
        sender_chat=None,
    )
    button_msg = SimpleNamespace(
        id=103,
        chat=SimpleNamespace(id=-100123),
        photo=None,
        date=datetime(2026, 9, 19, 10, 0, 15),
        from_user=bot_sender,
        sender_chat=None,
    )

    messages = [photo_msg_1, None, photo_msg_2, button_msg]
    found = signer._find_previous_photo_message(messages, button_msg)
    assert found is not None
    assert found.id == 102
    assert found.photo.file_id == "photo_file_2"


def test_find_previous_photo_skips_other_sender_images():
    signer = DummySigner()
    bot_sender = SimpleNamespace(id=1001)
    spammer_sender = SimpleNamespace(id=9999)

    bot_photo_msg = SimpleNamespace(
        id=201,
        chat=SimpleNamespace(id=-100123),
        photo=SimpleNamespace(file_id="bot_photo_1"),
        date=datetime(2026, 9, 19, 10, 0, 0),
        from_user=bot_sender,
        sender_chat=None,
    )
    spammer_photo_msg = SimpleNamespace(
        id=202,
        chat=SimpleNamespace(id=-100123),
        photo=SimpleNamespace(file_id="spam_sticker"),
        date=datetime(2026, 9, 19, 10, 0, 5),
        from_user=spammer_sender,
        sender_chat=None,
    )
    button_msg = SimpleNamespace(
        id=203,
        chat=SimpleNamespace(id=-100123),
        photo=None,
        date=datetime(2026, 9, 19, 10, 0, 10),
        from_user=bot_sender,
        sender_chat=None,
    )

    messages = [bot_photo_msg, spammer_photo_msg, button_msg]
    found = signer._find_previous_photo_message(messages, button_msg)
    assert found is not None
    assert found.id == 201
    assert found.photo.file_id == "bot_photo_1"

    # Test sender_chat fallback
    chat_sender = SimpleNamespace(id=-100555)
    channel_photo_msg = SimpleNamespace(
        id=204,
        chat=SimpleNamespace(id=-100123),
        photo=SimpleNamespace(file_id="channel_photo"),
        date=datetime(2026, 9, 19, 10, 0, 0),
        from_user=None,
        sender_chat=chat_sender,
    )
    channel_btn_msg = SimpleNamespace(
        id=205,
        chat=SimpleNamespace(id=-100123),
        photo=None,
        date=datetime(2026, 9, 19, 10, 0, 5),
        from_user=None,
        sender_chat=chat_sender,
    )
    found_channel = signer._find_previous_photo_message([channel_photo_msg, channel_btn_msg], channel_btn_msg)
    assert found_channel is not None
    assert found_channel.id == 204

    # Test anonymous scenario (both None) logs warning and matches
    anon_photo_msg = SimpleNamespace(
        id=206,
        chat=SimpleNamespace(id=-100123),
        photo=SimpleNamespace(file_id="anon_photo"),
        date=datetime(2026, 9, 19, 10, 0, 0),
        from_user=None,
        sender_chat=None,
    )
    anon_btn_msg = SimpleNamespace(
        id=207,
        chat=SimpleNamespace(id=-100123),
        photo=None,
        date=datetime(2026, 9, 19, 10, 0, 5),
        from_user=None,
        sender_chat=None,
    )
    signer.logs.clear()
    found_anon = signer._find_previous_photo_message([anon_photo_msg, anon_btn_msg], anon_btn_msg)
    assert found_anon is not None
    assert found_anon.id == 206
    assert any("WARNING" == level for level, _ in signer.logs)


def test_find_previous_photo_skips_expired_images():
    signer = DummySigner()
    bot_sender = SimpleNamespace(id=1001)

    # Time expiration > 120s
    expired_photo = SimpleNamespace(
        id=301,
        chat=SimpleNamespace(id=-100123),
        photo=SimpleNamespace(file_id="expired_photo"),
        date=datetime(2026, 9, 19, 10, 0, 0),
        from_user=bot_sender,
        sender_chat=None,
    )
    button_msg = SimpleNamespace(
        id=302,
        chat=SimpleNamespace(id=-100123),
        photo=None,
        date=datetime(2026, 9, 19, 10, 3, 0),  # 180s later
        from_user=bot_sender,
        sender_chat=None,
    )

    found = signer._find_previous_photo_message([expired_photo, button_msg], button_msg, max_age_seconds=120.0)
    assert found is None

    # Max backtrack span exceeded
    valid_photo = SimpleNamespace(
        id=400,
        chat=SimpleNamespace(id=-100123),
        photo=SimpleNamespace(file_id="backtrack_photo"),
        date=datetime(2026, 9, 19, 10, 0, 0),
        from_user=bot_sender,
        sender_chat=None,
    )
    intervening_msgs = [
        SimpleNamespace(
            id=400 + i,
            chat=SimpleNamespace(id=-100123),
            photo=None,
            date=datetime(2026, 9, 19, 10, 0, i),
            from_user=bot_sender,
            sender_chat=None,
        )
        for i in range(1, 25)
    ]
    latest_button = SimpleNamespace(
        id=430,
        chat=SimpleNamespace(id=-100123),
        photo=None,
        date=datetime(2026, 9, 19, 10, 0, 25),
        from_user=bot_sender,
        sender_chat=None,
    )
    found_bt = signer._find_previous_photo_message(
        [valid_photo] + intervening_msgs + [latest_button],
        latest_button,
        max_backtrack=20,
    )
    assert found_bt is None


@pytest.mark.asyncio
async def test_choose_option_by_image_uses_previous_photo_and_current_buttons():
    signer = DummySigner()
    chat_id = -100123
    bot_sender = SimpleNamespace(id=888)

    photo_msg = SimpleNamespace(
        id=501,
        chat=SimpleNamespace(id=chat_id),
        photo=SimpleNamespace(file_id="split_captcha_photo_id"),
        date=datetime(2026, 9, 19, 10, 0, 0),
        from_user=bot_sender,
        sender_chat=None,
        text=None,
        caption=None,
    )
    button_msg = SimpleNamespace(
        id=502,
        chat=SimpleNamespace(id=chat_id),
        photo=None,
        date=datetime(2026, 9, 19, 10, 0, 5),
        from_user=bot_sender,
        sender_chat=None,
        text="请点击图中的猫咪",
        caption=None,
        reply_markup=InlineKeyboardMarkup(
            [[MockButton("猫咪", callback_data="cat"), MockButton("狗狗", callback_data="dog")]]
        ),
    )

    signer.context.chat_messages[chat_id] = {
        501: photo_msg,
        502: button_msg,
    }

    fake_stream = io.BytesIO(b"fake_image_bytes")
    signer.app.download_media.return_value = fake_stream
    signer.ai_tools.choose_options_by_image = AsyncMock(return_value=[1])

    action = ChooseOptionByImageAction()
    ok = await signer._choose_option_by_image(action, button_msg)

    assert ok is True
    signer.app.download_media.assert_awaited_once_with("split_captcha_photo_id", in_memory=True)
    signer._click_inline_button.assert_awaited_once()
    called_msg, called_btn = signer._click_inline_button.call_args[0]
    assert called_msg is button_msg
    assert called_btn.text == "猫咪"


@pytest.mark.asyncio
async def test_choose_option_by_image_returns_false_without_photo_candidate():
    signer = DummySigner()
    chat_id = -100123
    bot_sender = SimpleNamespace(id=888)

    button_msg = SimpleNamespace(
        id=601,
        chat=SimpleNamespace(id=chat_id),
        photo=None,
        date=datetime(2026, 9, 19, 10, 0, 0),
        from_user=bot_sender,
        sender_chat=None,
        text="请点击图中的选项",
        caption=None,
        reply_markup=InlineKeyboardMarkup([[MockButton("选项1"), MockButton("选项2")]]),
    )

    signer.context.chat_messages[chat_id] = {
        601: button_msg,
    }

    action = ChooseOptionByImageAction()
    ok = await signer._choose_option_by_image(action, button_msg)

    assert ok is False
    signer.app.download_media.assert_not_called()
    assert any("WARNING" == level for level, _ in signer.logs)

import io
from types import SimpleNamespace

import pytest

from tg_signer.config import ChooseOptionByImageAction
from tg_signer.core import ReplyKeyboardMarkup, UserSigner


def test_terminal_success_text_detects_already_signed_variants():
    signer = object.__new__(UserSigner)

    assert signer._text_has_terminal_success_text("⭕ 您今天已经签到过了！签到是无聊的活动哦。") is True
    assert signer._text_has_terminal_success_text("今日已签到，请明天再来") is True
    assert signer._text_has_terminal_success_text("签到失败，请稍后再试") is False


def test_terminal_success_text_does_not_treat_verification_prompts_as_success():
    signer = object.__new__(UserSigner)

    assert signer._text_has_terminal_success_text("请完成诗句填空进行验证") is False
    assert signer._text_has_terminal_success_text("请先回答问题后再签到") is False
    assert signer._callback_text_has_terminal_success_text("请完成诗句填空进行验证") is False


def test_terminal_success_text_keeps_task_completion_messages():
    signer = object.__new__(UserSigner)

    assert signer._text_has_terminal_success_text("任务完成，奖励已发放") is True
    assert signer._callback_text_has_terminal_success_text("操作完成") is True


def test_choose_option_action_supports_reply_keyboard():
    signer = object.__new__(UserSigner)
    message = SimpleNamespace(
        photo=object(),
        reply_markup=ReplyKeyboardMarkup([["院", "因"], ["外", "里"]]),
    )

    assert signer._message_supports_next_action(ChooseOptionByImageAction(), message) is True


@pytest.mark.asyncio
async def test_choose_option_by_image_can_click_reply_keyboard():
    signer = object.__new__(UserSigner)
    ai_calls = {}
    sent_messages = []

    class FakeAITools:
        async def choose_options_by_image(self, image, query, options, system_prompt=None):
            ai_calls["image"] = image
            ai_calls["query"] = query
            ai_calls["options"] = options
            ai_calls["system_prompt"] = system_prompt
            return [6, 7]

    async def fake_download_media(_file_id, in_memory=True):
        assert in_memory is True
        return io.BytesIO(b"image-bytes")

    async def fake_send_message(chat_id, text, **kwargs):
        sent_messages.append((chat_id, text, kwargs))
        return True

    signer.app = SimpleNamespace(download_media=fake_download_media)
    signer.get_ai_tools = lambda: FakeAITools()
    signer.send_message = fake_send_message
    signer.log = lambda *_args, **_kwargs: None
    signer._log_received_target_message = lambda *_args, **_kwargs: None

    message = SimpleNamespace(
        photo=SimpleNamespace(file_id="photo-1"),
        reply_markup=ReplyKeyboardMarkup(
            [["院", "因", "董", "简"], ["日", "外", "里", "闲"]]
        ),
        caption="请依次点击下方按钮补全诗句：墙外行人，墙里佳人笑。",
        text=None,
        chat=SimpleNamespace(id=8476074387),
        message_thread_id=321,
        reply_to_top_message_id=None,
    )

    ok = await signer._choose_option_by_image(
        ChooseOptionByImageAction(ai_prompt="custom vision prompt"),
        message,
    )

    assert ok is True
    assert ai_calls["image"] == b"image-bytes"
    assert ai_calls["query"] == "请依次点击下方按钮补全诗句：墙\\行人，墙\\佳人笑。"
    assert ai_calls["options"] == [
        (1, "院"),
        (2, "因"),
        (3, "董"),
        (4, "简"),
        (5, "日"),
        (6, "外"),
        (7, "里"),
        (8, "闲"),
    ]
    assert ai_calls["system_prompt"] == "custom vision prompt"
    assert sent_messages == [
        (8476074387, "外", {"message_thread_id": 321}),
        (8476074387, "里", {"message_thread_id": 321}),
    ]

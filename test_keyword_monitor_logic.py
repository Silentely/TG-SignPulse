import importlib
import sys
import types

import pytest


def load_keyword_monitor(monkeypatch):
    for name in list(sys.modules):
        if name == "backend.services.keyword_monitor" or name.startswith("pyrogram"):
            monkeypatch.delitem(sys.modules, name, raising=False)

    class FakeFilter:
        def __and__(self, _other):
            return self

        def __or__(self, _other):
            return self

    class FakeFloodWait(Exception):
        value = 1

    class FakeMessageHandler:
        def __init__(self, callback, filters=None):
            self.callback = callback
            self.filters = filters

    class FakeInlineKeyboardMarkup:
        def __init__(self, inline_keyboard):
            self.inline_keyboard = inline_keyboard

    class FakeReplyKeyboardMarkup:
        def __init__(self, keyboard):
            self.keyboard = keyboard

    pyrogram_mod = types.ModuleType("pyrogram")
    handlers_mod = types.ModuleType("pyrogram.handlers")
    types_mod = types.ModuleType("pyrogram.types")

    filters = types.SimpleNamespace(
        chat=lambda _chat_ids: FakeFilter(),
        text=FakeFilter(),
        caption=FakeFilter(),
    )
    errors = types.SimpleNamespace(FloodWait=FakeFloodWait)

    pyrogram_mod.errors = errors
    pyrogram_mod.filters = filters
    handlers_mod.MessageHandler = FakeMessageHandler
    types_mod.InlineKeyboardMarkup = FakeInlineKeyboardMarkup
    types_mod.ReplyKeyboardMarkup = FakeReplyKeyboardMarkup
    types_mod.Message = object

    monkeypatch.setitem(sys.modules, "pyrogram", pyrogram_mod)
    monkeypatch.setitem(sys.modules, "pyrogram.handlers", handlers_mod)
    monkeypatch.setitem(sys.modules, "pyrogram.types", types_mod)

    return importlib.import_module("backend.services.keyword_monitor")


class FakeChat:
    def __init__(self, chat_id=-100123, title="Source"):
        self.id = chat_id
        self.title = title
        self.username = None


class FakeButton:
    def __init__(self, text, callback_data=b"bad"):
        self.text = text
        self.callback_data = callback_data


class FakeMessage:
    def __init__(self, message_id, chat, text="", reply_markup=None):
        self.id = message_id
        self.chat = chat
        self.text = text
        self.caption = None
        self.reply_markup = reply_markup
        self.photo = None
        self.from_user = None
        self.message_thread_id = None
        self.reply_to_top_message_id = None
        self.edit_date = None


def test_regex_keyword_uses_first_capture_group(monkeypatch):
    keyword_monitor = load_keyword_monitor(monkeypatch)
    service = keyword_monitor.KeywordMonitorService()
    text = """📢 Broadcast Message

gift code : ABC123ABC

----
I am selling source code for this bot telegram.
Interested? @heloyusa
100% Open Source"""

    assert (
        service._match_keyword(
            {
                "keywords": [r"gift code\s*:\s*([A-Za-z0-9-]+)"],
                "match_mode": "regex",
                "ignore_case": True,
            },
            text,
        )
        == "ABC123ABC"
    )


def test_regex_keyword_input_does_not_split_commas(monkeypatch):
    keyword_monitor = load_keyword_monitor(monkeypatch)

    assert keyword_monitor._parse_keywords(
        r"gift code\s*:\s*([A-Z0-9]{8,12})",
        split_commas=False,
    ) == [r"gift code\s*:\s*([A-Z0-9]{8,12})"]


@pytest.mark.asyncio
async def test_keyword_continue_redeem_flow_click_then_sends_captured_code(monkeypatch):
    keyword_monitor = load_keyword_monitor(monkeypatch)

    async def fast_sleep(_seconds):
        return None

    monkeypatch.setattr(keyword_monitor.asyncio, "sleep", fast_sleep)

    chat = FakeChat()
    button_message = FakeMessage(
        10,
        chat,
        text="gift code : ABC123ABC",
        reply_markup=keyword_monitor.InlineKeyboardMarkup(
            [[FakeButton("Redeem Code")]]
        ),
    )
    prompt_message = FakeMessage(11, chat, text="Please send redeem code")
    source_message = FakeMessage(9, chat, text="gift code : ABC123ABC")

    class FakeClient:
        def __init__(self):
            self.history_calls = 0
            self.sent_messages = []

        async def get_chat(self, _chat_id):
            return None

        async def request_callback_answer(self, *_args, **_kwargs):
            raise Exception(
                'Telegram says: [400 DATA_INVALID] - The encrypted data is invalid.'
            )

        async def get_chat_history(self, _chat_id, limit):
            self.history_calls += 1
            messages = (
                [button_message]
                if self.history_calls == 1
                else [prompt_message, button_message]
            )
            for message in messages[:limit]:
                yield message

        async def send_message(self, chat_id, text, **kwargs):
            self.sent_messages.append((chat_id, text, kwargs))

    service = keyword_monitor.KeywordMonitorService()
    client = FakeClient()
    rule = keyword_monitor.KeywordMonitorRule(
        account_name="acct",
        task_name="redeem",
        chat_id=chat.id,
        chat_name=chat.title,
        message_thread_id=None,
        action={
            "push_channel": "continue",
            "continue_action_interval": 0,
            "continue_actions": [
                {"action": 3, "text": "Redeem Code"},
                {"action": 1, "text": "{keyword}"},
            ],
        },
    )

    await service._execute_continue_actions(
        account_name="acct",
        client=client,
        rule=rule,
        message=source_message,
        variables={"keyword": "ABC123ABC"},
    )

    assert client.sent_messages == [(chat.id, "ABC123ABC", {})]
    monitor_logs = service.get_task_logs("redeem", "acct")
    assert any("开始执行关键词命中后续动作" in line for line in monitor_logs)
    assert any("后续动作 1/2 开始：点击按钮: Redeem Code" in line for line in monitor_logs)
    assert any("后续动作 2/2 执行成功：发送文本: ABC123ABC" in line for line in monitor_logs)
    history_entry = service.get_task_history_entry("redeem", "acct")
    assert history_entry
    assert history_entry["flow_logs"] == monitor_logs


@pytest.mark.asyncio
async def test_keyword_monitor_handles_repeated_matching_messages(monkeypatch):
    keyword_monitor = load_keyword_monitor(monkeypatch)

    class FakeConfigService:
        def get_global_settings(self):
            return {}

    import backend.services.config as config_service

    monkeypatch.setattr(
        config_service,
        "get_config_service",
        lambda: FakeConfigService(),
    )

    chat = FakeChat()
    service = keyword_monitor.KeywordMonitorService()
    service._rules = [
        keyword_monitor.KeywordMonitorRule(
            account_name="acct",
            task_name="redeem",
            chat_id=chat.id,
            chat_name=chat.title,
            message_thread_id=None,
            action={
                "keywords": [r"gift code\s*:\s*([A-Za-z0-9-]+)"],
                "match_mode": "regex",
                "ignore_case": True,
                "push_channel": "continue",
                "continue_actions": [{"action": 1, "text": "{keyword}"}],
            },
        )
    ]
    matched_codes = []

    async def fake_execute_continue_actions(**kwargs):
        matched_codes.append(kwargs["variables"]["keyword"])

    monkeypatch.setattr(service, "_execute_continue_actions", fake_execute_continue_actions)

    await service._on_message(
        "acct",
        object(),
        FakeMessage(1, chat, text="gift code : ABC123ABC"),
    )
    await service._on_message(
        "acct",
        object(),
        FakeMessage(2, chat, text="gift code : XYZ789XYZ"),
    )

    assert matched_codes == ["ABC123ABC", "XYZ789XYZ"]
    monitor_logs = service.get_task_logs("redeem", "acct")
    assert any("关键词命中" in line and "捕获值=ABC123ABC" in line for line in monitor_logs)
    assert any("关键词命中" in line and "捕获值=XYZ789XYZ" in line for line in monitor_logs)

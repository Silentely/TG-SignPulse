import datetime
from unittest.mock import MagicMock
from tg_signer.core.plugin_ipc import (
    serialize_message_for_worker,
    ProxyChat,
    ProxyUser,
    ProxyButton,
    ProxyMessage,
    encode_ipc_payload,
    decode_ipc_payload,
)


def test_serialize_none_message():
    assert serialize_message_for_worker(None) is None


def test_serialize_full_message_and_proxy_access():
    raw_msg = MagicMock()
    raw_msg.id = 9527
    raw_msg.text = "请点击正确答案"
    raw_msg.caption = None
    raw_msg.date = datetime.datetime.fromtimestamp(1710000000, tz=datetime.timezone.utc)
    raw_msg.reply_to_message_id = 1001

    # 用户信息
    raw_user = MagicMock()
    raw_user.id = 777
    raw_user.username = "test_bot"
    raw_user.first_name = "Bot"
    raw_user.last_name = None
    raw_msg.from_user = raw_user

    # 会话信息
    raw_msg.chat = MagicMock(id=8888, title="Test Group", type="supergroup")

    # 内联按钮
    btn1 = MagicMock(text="选项A", callback_data=b"opt_a")
    btn2 = MagicMock(text="选项B", callback_data="opt_b")
    btn3 = MagicMock(text="选项C", callback_data=None)
    raw_msg.reply_markup = MagicMock(inline_keyboard=[[btn1, btn2, btn3]])

    serialized = serialize_message_for_worker(raw_msg)
    assert serialized["id"] == 9527
    assert serialized["text"] == "请点击正确答案"
    assert serialized["date"] == 1710000000
    assert serialized["from_user"]["username"] == "test_bot"
    assert serialized["chat"]["id"] == 8888
    assert len(serialized["buttons"]) == 1
    assert serialized["buttons"][0][0]["text"] == "选项A"
    assert serialized["buttons"][0][0]["data"] == "opt_a"
    assert serialized["buttons"][0][1]["data"] == "opt_b"
    assert serialized["buttons"][0][2]["data"] == ""

    proxy = ProxyMessage(serialized)
    assert proxy.id == 9527
    assert proxy.text == "请点击正确答案"
    assert proxy.date == 1710000000
    assert proxy.from_user is not None
    assert proxy.from_user.id == 777
    assert proxy.from_user.username == "test_bot"
    assert proxy.chat.id == 8888
    assert proxy.chat.title == "Test Group"
    assert proxy.chat.type == "supergroup"
    assert bool(proxy.chat) is True
    assert proxy.reply_to_message_id == 1001
    assert proxy.buttons[0][0].text == "选项A"
    assert proxy.buttons[0][0].data == "opt_a"

    # Verify __repr__ representations
    assert "9527" in repr(proxy)
    assert "8888" in repr(proxy.chat)
    assert "test_bot" in repr(proxy.from_user)
    assert "选项A" in repr(proxy.buttons[0][0])


def test_serialize_date_variations():
    msg1 = MagicMock(id=1, text="t", date=1710001234, chat=None, from_user=None, reply_markup=None)
    assert serialize_message_for_worker(msg1)["date"] == 1710001234

    bad_date_obj = MagicMock()
    bad_date_obj.timestamp.side_effect = OverflowError("overflow")
    msg2 = MagicMock(id=2, text="t", date=bad_date_obj, chat=None, from_user=None, reply_markup=None)
    assert isinstance(serialize_message_for_worker(msg2)["date"], str)

    msg3 = MagicMock(id=3, text="t", date="2026-09-09", chat=None, from_user=None, reply_markup=None)
    assert serialize_message_for_worker(msg3)["date"] == "2026-09-09"


def test_serialize_minimal_message_with_chat_id_fallback():
    raw_msg = MagicMock(spec=["id", "text", "caption", "date", "reply_to_message_id", "chat_id"])
    raw_msg.id = 123
    raw_msg.text = "hello"
    raw_msg.caption = "cap"
    raw_msg.date = 100
    raw_msg.reply_to_message_id = None
    raw_msg.chat_id = 9999

    serialized = serialize_message_for_worker(raw_msg)
    assert serialized["id"] == 123
    assert serialized["chat"]["id"] == 9999
    assert serialized["from_user"] is None
    assert serialized["buttons"] == []

    proxy = ProxyMessage(serialized)
    assert proxy.id == 123
    assert proxy.from_user is None
    assert proxy.chat.id == 9999
    assert bool(proxy.chat) is True
    assert proxy.buttons == []


def test_serialize_message_without_chat_or_user():
    raw_msg = MagicMock(spec=["id", "text"])
    raw_msg.id = 456
    raw_msg.text = "isolated"

    serialized = serialize_message_for_worker(raw_msg)
    assert serialized["id"] == 456
    assert serialized["chat"] is None
    assert serialized["from_user"] is None
    assert serialized["buttons"] == []

    proxy = ProxyMessage(serialized)
    assert proxy.id == 456
    assert proxy.chat.id is None
    assert bool(proxy.chat) is False


def test_proxy_empty_initialization():
    proxy = ProxyMessage(None)
    assert proxy.id is None
    assert proxy.text is None
    assert proxy.from_user is None
    assert proxy.chat.id is None
    assert bool(proxy.chat) is False
    assert proxy.buttons == []

    chat = ProxyChat(None)
    assert chat.id is None
    assert bool(chat) is False

    user = ProxyUser(None)
    assert user.id is None

    btn = ProxyButton({})
    assert btn.text == ""
    assert btn.data == ""


def test_encode_and_decode_ipc_with_truncation():
    payload = {"type": "log", "message": "A" * 20000}
    encoded = encode_ipc_payload(payload, max_len=1000)
    assert len(encoded) <= 1200
    decoded = decode_ipc_payload(encoded.strip())
    assert decoded["type"] == "log"
    assert len(decoded["message"]) < 20000


def test_encode_and_decode_ipc_no_truncation():
    payload = {"type": "event", "event": "sign_complete", "data": {"status": "ok"}}
    encoded = encode_ipc_payload(payload)
    assert encoded.endswith("\n")
    decoded = decode_ipc_payload(encoded)
    assert decoded == payload


def test_encode_ipc_payload_default_str_fallback():
    payload = {
        "type": "error",
        "exception": ValueError("test value error"),
        "time": datetime.datetime(2026, 9, 9, 12, 0, 0),
    }
    encoded = encode_ipc_payload(payload)
    decoded = decode_ipc_payload(encoded)
    assert decoded["type"] == "error"
    assert "test value error" in decoded["exception"]
    assert "2026-09-09" in decoded["time"]

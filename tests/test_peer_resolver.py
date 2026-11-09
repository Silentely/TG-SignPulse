"""peer_resolver 的单元测试。

验证多级 peer 解析、get_dialogs 增量预热、_WARM_FLAG 幂等守卫、
候选 ID 转换以及 signer runner 中 handler 注册时序。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tg_signer.config import ClickKeyboardByTextAction, SignChatV3, SignConfigV3
from tg_signer.core.peer_resolver import (
    _WARM_FLAG,
    PeerResolveError,
    candidate_ids,
    resolve_peer_id,
    warm_peer_cache,
)
from tg_signer.core.signer_runner import SignerRunnerMixin


class FakeRPCError(Exception):
    """模拟 pyrogram.errors.RPCError。"""


class FakeClient:
    """最小化的 pyrogram Client 替身。

    storage 相当于 pyrogram 的 peer 存储：只有在这里出现的 id 才能 get_chat。
    dialog_ids 相当于账号最近会话列表；get_dialogs 会把它们写进 storage，
    这正是真实 pyrogram 内部 fetch_peers 的行为。
    """

    def __init__(self, storage=None, dialogs=None, username_index=None):
        self.storage = dict(storage or {})
        self.dialog_ids = list(dialogs or [])
        self.username_index = {k.lower(): v for k, v in (username_index or {}).items()}
        self.calls = []
        self.is_connected = True
        self.in_memory = False
        self.session_string = None

    async def get_chat(self, chat_id):
        self.calls.append(("get_chat", chat_id))
        if isinstance(chat_id, str):
            key = chat_id.lower().lstrip("@").replace("https://t.me/", "")
            cid = self.username_index.get(key)
            if cid is None:
                raise FakeRPCError("USERNAME_NOT_OCCUPIED")
            return SimpleNamespace(id=cid, title=f"chat-{cid}")
        if chat_id in self.storage:
            return SimpleNamespace(id=chat_id, title=self.storage[chat_id])
        raise FakeRPCError(
            "CHANNEL_INVALID" if str(chat_id).startswith("-100") else "PEER_ID_INVALID"
        )

    async def get_users(self, chat_id):
        self.calls.append(("get_users", chat_id))
        if chat_id in self.storage:
            return [SimpleNamespace(id=chat_id)]
        raise FakeRPCError("USER_ID_INVALID")

    async def get_dialogs(self, limit=None):
        self.calls.append(("get_dialogs", limit))
        for chat_id in self.dialog_ids[: limit or None]:
            self.storage.setdefault(chat_id, f"dialog-{chat_id}")
            yield SimpleNamespace(chat=SimpleNamespace(id=chat_id))

    async def start(self):
        self.calls.append(("start",))
        self.is_connected = True

    async def stop(self):
        self.calls.append(("stop",))
        self.is_connected = False


USER_ID = 8104413787
CHANNEL_ID = -1008104413787


def test_direct_hit():
    """peer 已在存储里时不应触发 get_dialogs。"""
    client = FakeClient(storage={USER_ID: "DirectChat"})

    result = asyncio.run(resolve_peer_id(client, USER_ID))

    assert result.chat_id == USER_ID
    assert result.method == "direct"
    assert result.dialogs_scanned == 0
    assert not any(
        isinstance(call, tuple) and call[0] == "get_dialogs" for call in client.calls
    )


def test_warmup_on_channel_invalid_with_dialogs():
    """string session 丢 peer 时，get_dialogs 应补回 access_hash。"""
    client = FakeClient(dialogs=[USER_ID, -1001111111111])

    result = asyncio.run(resolve_peer_id(client, USER_ID))

    assert result.chat_id == USER_ID
    assert result.method == "dialog-warm"
    assert USER_ID in client.storage
    assert result.dialogs_scanned == 2


def test_warmup_flag_prevents_rescanning():
    """_WARM_FLAG 应阻止同一 Client 重复扫描 dialogs。"""
    client = FakeClient(dialogs=[USER_ID])

    scanned_first = asyncio.run(warm_peer_cache(client, limit=500))
    assert scanned_first == 1
    assert getattr(client, _WARM_FLAG) is True

    # 第二次调用 warm_peer_cache 应立即返回 0，不再次触发 get_dialogs
    scanned_second = asyncio.run(warm_peer_cache(client, limit=500))
    assert scanned_second == 0

    dialog_calls = [c for c in client.calls if c[0] == "get_dialogs"]
    assert len(dialog_calls) == 1


def test_candidate_ids_applied_after_warmup():
    """候选 ID 变换（缺失 -100 前缀）必须在预热之后生效。"""
    client = FakeClient(dialogs=[CHANNEL_ID])
    raw_id = abs(CHANNEL_ID) - 10**12  # 8104413787

    result = asyncio.run(resolve_peer_id(client, raw_id))

    assert result.chat_id == CHANNEL_ID
    assert result.method == f"id-variant:{CHANNEL_ID}"
    assert result.dialogs_scanned == 1


def test_candidate_ids_logic():
    assert candidate_ids(USER_ID) == [int(f"-100{USER_ID}"), -USER_ID]
    assert candidate_ids(CHANNEL_ID) == []
    assert candidate_ids(-8104413787) == [CHANNEL_ID]


def test_cached_username_fallback():
    client = FakeClient(username_index={"sample_bot": USER_ID})

    def cache_lookup(chat_id, name):
        assert chat_id == USER_ID
        return {"id": USER_ID, "username": "sample_bot"}

    result = asyncio.run(resolve_peer_id(client, USER_ID, cache_lookup=cache_lookup))
    assert result.chat_id == USER_ID
    assert result.method == "username-hint"


def test_string_chat_id():
    client = FakeClient(username_index={"sample_bot": USER_ID})
    result = asyncio.run(resolve_peer_id(client, "@Sample_Bot"))
    assert result.chat_id == USER_ID
    assert result.method == "username"


def test_peer_resolve_error_actionable():
    client = FakeClient()
    with pytest.raises(PeerResolveError) as exc_info:
        asyncio.run(resolve_peer_id(client, USER_ID))
    msg = str(exc_info.value)
    assert str(USER_ID) in msg
    assert "刷新" in msg
    assert "username" in msg


@pytest.mark.asyncio
async def test_handler_registration_ordering_and_updated_ids(monkeypatch, tmp_path):
    """验证 SignerRunner preheat_chats 必须在 add_handler 之前执行，

    且 add_handler 注册的 filters.chat 中必须包含修正后的 peer ID。
    """
    raw_id = abs(CHANNEL_ID) - 10**12  # 8104413787
    fake_client = FakeClient(dialogs=[CHANNEL_ID])

    added_handlers = []

    def mock_add_handler(handler):
        fake_client.calls.append(("add_handler", handler))
        added_handlers.append(handler)
        return handler

    fake_client.add_handler = mock_add_handler
    fake_client.remove_handler = MagicMock()

    captured_filters_chats = []
    from tg_signer.compat import filters

    orig_chat_filter = filters.chat

    def spy_chat_filter(*args, **kwargs):
        captured_filters_chats.append(args[0] if args else kwargs.get("chats"))
        return orig_chat_filter(*args, **kwargs)

    monkeypatch.setattr("tg_signer.core.signer_runner.filters.chat", spy_chat_filter)

    class TestRunner(SignerRunnerMixin):
        def __init__(self, client):
            self.app = client
            self.user = SimpleNamespace(id=123)  # Skip login()
            self.logs = []
            self.tasks_dir = tmp_path
            self._account = "test_acc"
            self.cfg_cls = SignConfigV3
            self.sign_record_file = tmp_path / "sign_record.json"
            self.config = None

        def log(self, msg, level="INFO"):
            self.logs.append((level, msg))

        def load_config(self, cls):
            if self.config is None:
                self.config = SignConfigV3(
                    chats=[
                        SignChatV3(
                            chat_id=raw_id,
                            name="TestChannel",
                            actions=[ClickKeyboardByTextAction(text="签到")],
                        ),
                    ],
                    sign_at="00:00:00",
                    requires_ai=False,
                    random_seconds=0,
                )
            return self.config

        def load_sign_record(self):
            return {}

        def ensure_ctx(self):
            return SimpleNamespace(
                business_status="completed",
                last_chat_error=None,
                chat_messages={},
                sign_chats={CHANNEL_ID: []},
            )

        def _validate_sign_at(self, s):
            return "0 0 * * *"

        def _find_cached_chat(self, chat_id, name):
            return None

        async def _run_config_chats(self, cfg):
            return [
                {
                    "account_name": "test_acc",
                    "chat_id": str(cfg.chats[0].chat_id),
                    "thread_id": None,
                    "execution_status": "completed",
                    "business_status": "confirmed",
                }
            ]

    runner = TestRunner(fake_client)

    # 运行 normal_run(only_once=True)
    await runner.normal_run(only_once=True, force_rerun=True)

    # 验证 preheat_chats 将 chat_id 从 raw_id 纠正为 CHANNEL_ID
    assert runner.config.chats[0].chat_id == CHANNEL_ID

    # 验证 filters.chat 收到的是修正后的 CHANNEL_ID
    assert len(captured_filters_chats) > 0
    passed_ids = captured_filters_chats[0]
    assert CHANNEL_ID in passed_ids
    assert str(CHANNEL_ID) in passed_ids

    # 验证 calls 时序：get_dialogs 发生在 add_handler 之前
    call_names = [c[0] for c in fake_client.calls]
    assert "get_dialogs" in call_names
    assert "add_handler" in call_names
    assert call_names.index("get_dialogs") < call_names.index("add_handler")


@pytest.mark.asyncio
async def test_single_chat_warmup_failure_does_not_abort_preheat():
    """验证当某个会话预热失败时，仅记录 WARNING，不阻塞后续会话与 runner。"""
    fake_client = FakeClient(storage={11111: "ValidChat"})

    class TestRunner(SignerRunnerMixin):
        def __init__(self, client):
            self.app = client
            self.logs = []

        def log(self, msg, level="INFO"):
            self.logs.append((level, msg))

        def _find_cached_chat(self, chat_id, name):
            return None

    runner = TestRunner(fake_client)
    broken_chat = SignChatV3(chat_id=999999999, name="Broken", actions=[])
    valid_chat = SignChatV3(chat_id=11111, name="Valid", actions=[])

    # 批量预热应能平稳完成，不抛出异常
    await runner.preheat_chats([broken_chat, valid_chat])

    # broken_chat 未被修正，valid_chat 正常解析
    assert broken_chat.chat_id == 999999999
    assert valid_chat.chat_id == 11111

    # 检查日志中有针对坏会话的 WARNING 记录
    warnings = [msg for lvl, msg in runner.logs if lvl == "WARNING"]
    assert any("peer 预热" in w for w in warnings)

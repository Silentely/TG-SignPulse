"""peer_resolver 的自测脚本。

不依赖 pyrogram，可直接运行：
    python tests/test_peer_resolver.py
或：
    uv run pytest tests/test_peer_resolver.py --no-cov -v
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tg_signer.config import (  # noqa: E402
    ClickKeyboardByTextAction,
    SignChatV3,
    SignConfigV3,
)
from tg_signer.core.peer_resolver import (  # noqa: E402
    _WARM_FLAG,
    PeerResolveError,
    _verify_candidate_identity,
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
        self.raise_on_dialogs = False
        self.dialog_delay = 0

    async def get_chat(self, chat_id):
        self.calls.append(("get_chat", chat_id))
        if isinstance(chat_id, str):
            key = chat_id.lower().lstrip("@").replace("https://t.me/", "")
            cid = self.username_index.get(key)
            if cid is None:
                raise FakeRPCError("USERNAME_NOT_OCCUPIED")
            return SimpleNamespace(id=cid, title=f"chat-{cid}", username=key)
        if chat_id in self.storage:
            val = self.storage[chat_id]
            if isinstance(val, dict):
                return SimpleNamespace(id=chat_id, **val)
            return SimpleNamespace(id=chat_id, title=val)
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
        if self.raise_on_dialogs:
            raise RuntimeError("Network timeout while fetching dialogs")
        if self.dialog_delay > 0:
            await asyncio.sleep(self.dialog_delay)
        for chat_id in self.dialog_ids[: limit or None]:
            self.storage.setdefault(
                chat_id,
                {"title": f"dialog-{chat_id}", "username": f"user_{abs(chat_id)}"},
            )
            yield SimpleNamespace(
                chat=SimpleNamespace(
                    id=chat_id,
                    username=f"user_{abs(chat_id)}",
                    title=f"dialog-{chat_id}",
                )
            )

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


def test_warmup_failure_allows_subsequent_retry():
    """B1 验收：预热抛出异常时，不置位 _WARM_FLAG，第二次调用仍然会重试。"""
    client = FakeClient(dialogs=[USER_ID])
    client.raise_on_dialogs = True

    # 第一次调用：预热抛出异常
    res1 = asyncio.run(warm_peer_cache(client, limit=500))
    assert res1 == 0
    assert getattr(client, _WARM_FLAG, False) is False

    # 恢复网络
    client.raise_on_dialogs = False

    # 第二次调用：必须能再次触发 get_dialogs，并成功完成预热与置位
    res2 = asyncio.run(warm_peer_cache(client, limit=500))
    assert res2 == 1
    assert getattr(client, _WARM_FLAG) is True

    # 底层 get_dialogs 确实被调用了 2 次（第一次失败，第二次重试成功）
    dialog_calls = [c for c in client.calls if c[0] == "get_dialogs"]
    assert len(dialog_calls) == 2


@pytest.mark.asyncio
async def test_warmup_concurrent_calls_executed_only_once():
    """B1 验收：并发调用 warm_peer_cache 时，异步锁保证底层只真正执行一次。"""
    client = FakeClient(dialogs=[USER_ID, CHANNEL_ID])
    client.dialog_delay = 0.05  # 模拟网络延迟让协程并发重叠

    # 并发发起两个预热请求
    results = await asyncio.gather(
        warm_peer_cache(client, limit=500),
        warm_peer_cache(client, limit=500),
    )

    # 一个执行拉取得到 2，另一个在 lock 内发现已置位直接返回 0
    assert sum(results) == 2
    assert getattr(client, _WARM_FLAG) is True

    # 底层 get_dialogs 严格只执行了 1 次
    dialog_calls = [c for c in client.calls if c[0] == "get_dialogs"]
    assert len(dialog_calls) == 1


def test_candidate_ids_applied_after_warmup():
    """候选 ID 变换（缺失 -100 前缀）必须在预热之后生效（需核对目标身份）。"""
    client = FakeClient(
        dialogs=[CHANNEL_ID],
        storage={
            CHANNEL_ID: {
                "title": "ChannelBot",
                "username": "channel_bot",
            }
        },
    )
    raw_id = abs(CHANNEL_ID) - 10**12  # 8104413787

    result = asyncio.run(
        resolve_peer_id(
            client,
            raw_id,
            name="channel_bot",
            expected_name="channel_bot",
        )
    )

    assert result.chat_id == CHANNEL_ID
    assert result.method == f"id-variant:{CHANNEL_ID}"
    assert result.dialogs_scanned == 1


def test_candidate_ids_rejects_identity_mismatch():
    """C1 验收：构造 ID 命中但用户名不符的假候选，必须被拒绝并报错无法确认目标身份。"""
    raw_id = abs(CHANNEL_ID) - 10**12  # 8104413787

    # 存储中存在该候选 ID，但属于另一个用户名（例如冒充群 attacker_bot）
    client = FakeClient(
        storage={
            CHANNEL_ID: {
                "title": "Attacker Imposter Channel",
                "username": "attacker_bot",
            }
        }
    )

    # 任务明确要求目标用户名是 @correct_bot
    with pytest.raises(PeerResolveError) as exc_info:
        asyncio.run(
            resolve_peer_id(
                client,
                raw_id,
                username="correct_bot",
            )
        )

    err_msg = str(exc_info.value)
    assert "无法确认目标身份" in err_msg or "无法解析" in err_msg


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
    fake_client = FakeClient(
        dialogs=[CHANNEL_ID],
        storage={
            CHANNEL_ID: {
                "title": "TestChannel",
                "username": "test_channel",
            }
        },
    )

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
                            name="test_channel",
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


@pytest.mark.asyncio
async def test_candidate_ids_rejects_when_only_id_without_username():
    """① 只有 ID 无 username → 必须拒绝（严禁仅凭数学变体 ID 放行）。"""
    raw_id = 123456789
    candidate_channel_id = -100123456789
    client = FakeClient(
        storage={
            candidate_channel_id: {
                "title": "NoUsernameGroup",
                "username": None,
            }
        }
    )
    with pytest.raises(PeerResolveError) as exc_info:
        await resolve_peer_id(client, raw_id)
    assert f"无法解析 chat_id={raw_id}" in str(exc_info.value)


@pytest.mark.asyncio
async def test_candidate_ids_rejects_when_expected_name_mismatched():
    """② expected_name 与 candidate 身份不符 → 必须拒绝。"""
    raw_id = 123456789
    candidate_channel_id = -100123456789
    client = FakeClient(
        storage={
            candidate_channel_id: {
                "title": "真实群组",
                "username": "real_group",
            }
        }
    )
    with pytest.raises(PeerResolveError) as exc_info:
        await resolve_peer_id(
            client,
            raw_id,
            name="恶意伪装群",
            expected_name="恶意伪装群",
        )
    assert f"无法解析 chat_id={raw_id}" in str(exc_info.value)


@pytest.mark.asyncio
async def test_resolve_peer_cancelled_error_propagates_upward():
    """③ 取消信号（asyncio.CancelledError） → 必须向上抛，绝不被吞。"""
    raw_id = 123456789
    client = FakeClient()

    async def cancel_get_chat(chat_id):
        raise asyncio.CancelledError("Task was cancelled")

    client.get_chat = cancel_get_chat

    with pytest.raises(asyncio.CancelledError):
        await resolve_peer_id(client, raw_id)


def test_verify_candidate_identity_rejects_when_title_contains_name_but_username_differs():
    """A1 ① 标题包含目标名但 username 不符 → 必须拒绝（标题不参与身份判定，严禁冒充）。"""
    cand = SimpleNamespace(
        id=-1008104413787,
        title="target_bot official group",
        username="attacker_imposter_bot",
    )
    # expected_username 为 target_bot，而 cand.username 为 attacker_imposter_bot
    # 虽然 title 包含 "target_bot"，但 username 不符，必须拒绝
    assert not _verify_candidate_identity(
        cand,
        original_chat_id=8104413787,
        expected_username="target_bot",
    )
    # 传入 expected_name 也必须严格只对 username 进行精确核对，标题不得用于放行
    assert not _verify_candidate_identity(
        cand,
        original_chat_id=8104413787,
        expected_name="target_bot",
    )


def test_verify_candidate_identity_case_insensitive_username_matches():
    """A1 ② username 大小写不同 → 按归一后精确相等处理。"""
    cand = SimpleNamespace(
        id=-1008104413787,
        title="Random Title",
        username="Target_Bot_Official",
    )
    assert _verify_candidate_identity(
        cand,
        original_chat_id=8104413787,
        expected_username="target_bot_official",
    )
    assert _verify_candidate_identity(
        cand,
        original_chat_id=8104413787,
        expected_name="@TARGET_BOT_OFFICIAL",
    )


def test_verify_candidate_identity_exact_match_passes():
    """A1 ③ 完全匹配 → 通过。"""
    cand = SimpleNamespace(
        id=-1008104413787,
        title="Official Channel",
        username="target_bot",
    )
    assert _verify_candidate_identity(
        cand,
        original_chat_id=8104413787,
        expected_username="target_bot",
    )

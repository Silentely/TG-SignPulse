"""_fetch_last_target_message_from_chat_history 候选选择逻辑测试。

覆盖：跨 chat 聚合取最新非自己消息、历史降序下不误取最旧候选、
全自己消息回退、非自己优先、无候选返回空串（回归测试）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.services.sign_tasks import SignTaskService


class _FakeHistory:
    """可异步迭代的历史消息序列（get_chat_history 返回 newest-first）。"""

    def __init__(self, messages):
        self._messages = messages

    def __aiter__(self):
        self._it = iter(self._messages)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _FakeApp:
    def __init__(self, history_by_chat):
        self.history_by_chat = history_by_chat
        self.is_connected = True
        self.is_initialized = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    def get_chat_history(self, chat_id, limit=None):
        return _FakeHistory(self.history_by_chat.get(chat_id, [])[: limit or None])


class _FakeSigner:
    def __init__(self, history_by_chat):
        self.app = _FakeApp(history_by_chat)


def _msg(text, is_self=False, when=None, msg_id=0):
    """构造最小可匹配消息：text 非空、from_user.is_self 可控。"""
    return SimpleNamespace(
        id=msg_id,
        text=text,
        caption=None,
        message_thread_id=None,
        date=when or datetime(2026, 8, 4, tzinfo=timezone.utc),
        from_user=SimpleNamespace(is_self=is_self),
    )


def _make_svc():
    return SignTaskService.__new__(SignTaskService)


def _chats(*chat_ids):
    return [{"chat_id": cid} for cid in chat_ids]


async def _fetch(svc, signer, chats):
    return await svc._fetch_last_target_message_from_chat_history(
        signer, {"chats": chats}
    )


@pytest.mark.asyncio
async def test_picks_newest_non_self_across_chats():
    """跨 chat 聚合：应返回时间最新的非自己消息，而非首个 chat 的候选。"""
    svc = _make_svc()
    base = datetime(2026, 8, 4, tzinfo=timezone.utc)
    # chat 1 只有较旧的非自己消息；chat 2 有较新的非自己消息
    signer = _FakeSigner(
        {
            1: [_msg("旧目标", when=base)],
            2: [_msg("新目标", when=base + timedelta(minutes=5))],
        }
    )
    result = await _fetch(svc, signer, _chats(1, 2))
    assert result == "新目标"


@pytest.mark.asyncio
async def test_newest_win_not_oldest_within_chat():
    """回归：历史降序（newest-first）下应取最新候选，而非窗口内最旧一条。"""
    svc = _make_svc()
    base = datetime(2026, 8, 4, tzinfo=timezone.utc)
    signer = _FakeSigner(
        {
            1: [
                _msg("新目标", when=base),
                _msg("旧目标", when=base - timedelta(hours=1)),
            ]
        }
    )
    result = await _fetch(svc, signer, _chats(1))
    assert result == "新目标"


@pytest.mark.asyncio
async def test_falls_back_to_newest_self_message():
    """全部为自己消息时，返回最新自己消息。"""
    svc = _make_svc()
    base = datetime(2026, 8, 4, tzinfo=timezone.utc)
    signer = _FakeSigner(
        {
            1: [
                _msg("自己新", is_self=True, when=base),
                _msg("自己旧", is_self=True, when=base - timedelta(minutes=1)),
            ]
        }
    )
    result = await _fetch(svc, signer, _chats(1))
    assert result == "自己新"


@pytest.mark.asyncio
async def test_non_self_wins_over_self_fallback():
    """同一 chat 中非自己消息优先于自己消息。"""
    svc = _make_svc()
    base = datetime(2026, 8, 4, tzinfo=timezone.utc)
    signer = _FakeSigner(
        {
            1: [
                _msg("自己回复", is_self=True, when=base),
                _msg("目标消息", when=base - timedelta(seconds=30)),
            ]
        }
    )
    result = await _fetch(svc, signer, _chats(1))
    assert result == "目标消息"


@pytest.mark.asyncio
async def test_returns_empty_when_no_matching_candidate():
    """历史内无任何可摘要候选时返回空串（不得抛 UnboundLocalError）。"""
    svc = _make_svc()
    # text/caption 均为空、无媒体/按钮/投票 → 摘要为空，全部跳过
    signer = _FakeSigner(
        {
            1: [
                SimpleNamespace(
                    id=1,
                    text=None,
                    caption=None,
                    message_thread_id=None,
                    from_user=SimpleNamespace(is_self=False),
                )
            ]
        }
    )
    result = await _fetch(svc, signer, _chats(1))
    assert result == ""


@pytest.mark.asyncio
async def test_empty_chats_returns_empty():
    """chats 缺失或为空时直接返回空串。"""
    svc = _make_svc()
    assert await _fetch(svc, _FakeSigner({}), []) == ""
    assert await _fetch(svc, _FakeSigner({}), [{"chat_id": None}]) == ""


@pytest.mark.asyncio
async def test_thread_mismatch_skipped():
    """配置了 message_thread_id 时，不匹配线程的消息被跳过。"""
    svc = _make_svc()
    signer = _FakeSigner(
        {
            1: [
                SimpleNamespace(
                    id=2,
                    text="线程消息",
                    caption=None,
                    message_thread_id=99,
                    date=datetime(2026, 8, 4, tzinfo=timezone.utc),
                    from_user=SimpleNamespace(is_self=False),
                )
            ]
        }
    )
    result = await _fetch(svc, signer, [{"chat_id": 1, "message_thread_id": 7}])
    assert result == ""

"""Chat Folders 与 Forum Topics 发现测试套件。"""
from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pyrogram import raw

from backend.services.telegram.dialog_discovery import (
    TelegramDialogDiscoveryMixin,
    parse_dialog_filters,
)
from backend.utils.account_locks import AccountLockTimeout
from tests.test_api import _auth, _login, api_client, db  # noqa: F401


def _make_mock_forum_topic(**kwargs):
    sig = inspect.signature(raw.types.ForumTopic.__init__)
    defaults = {
        "id": 42,
        "date": 1700000000,
        "title": "签到专用话题",
        "icon_color": 0xFFFFFF,
        "top_message": 999,
        "read_inbox_max_id": 999,
        "read_outbox_max_id": 999,
        "unread_count": 0,
        "unread_mentions_count": 0,
        "unread_reactions_count": 0,
        "from_id": raw.types.PeerUser(user_id=1001),
        "notify_settings": raw.types.PeerNotifySettings(),
    }
    if "peer" in sig.parameters:
        defaults["peer"] = raw.types.PeerChannel(channel_id=123)
    if "unread_poll_votes_count" in sig.parameters:
        defaults["unread_poll_votes_count"] = 0
    defaults.update(kwargs)
    filtered = {k: v for k, v in defaults.items() if k in sig.parameters}
    return raw.types.ForumTopic(**filtered)


class DummyDiscoveryService(TelegramDialogDiscoveryMixin):
    def __init__(self):
        self.session_dir = MagicMock()
        self._accounts_cache = None

    def _normalize_account_name(self, name: str) -> str:
        return name.strip()

    def account_exists(self, name: str) -> bool:
        return True

    def _build_account_client(self, account_name: str, no_updates: bool = True):
        client = MagicMock()
        client.is_connected = False
        client.connect = AsyncMock()
        client.disconnect = AsyncMock()
        client.invoke = AsyncMock()
        return client, None

    async def verify_account_proxy(self, account_name: str, proxy_dict=None):
        pass


def test_parse_dialog_filters_returns_safe_summary():
    """测试各类 DialogFilter 变体解析与防御容错。"""
    # 1. DialogFilterDefault
    default_filter = raw.types.DialogFilterDefault()

    # 2. DialogFilterChatlist
    chatlist_filter = raw.types.DialogFilterChatlist(
        id=2,
        title=raw.types.TextWithEntities(text="工作群", entities=[]),
        pinned_peers=[raw.types.InputPeerChannel(channel_id=12345, access_hash=0)],
        include_peers=[raw.types.InputPeerUser(user_id=67890, access_hash=0)],
        emoticon="💼",
    )

    # 3. DialogFilter
    regular_filter = raw.types.DialogFilter(
        id=3,
        title="加密货币",
        pinned_peers=[],
        include_peers=[raw.types.InputPeerChat(chat_id=9876)],
        exclude_peers=[raw.types.InputPeerUser(user_id=11111, access_hash=0)],
        emoticon="💰",
    )

    # 4. 损坏的/异常的过滤器对象
    corrupted_filter = MagicMock()
    corrupted_filter.id = "bad"
    type(corrupted_filter).title = property(lambda self: (_ for _ in ()).throw(RuntimeError("corrupted")))

    results = parse_dialog_filters([default_filter, chatlist_filter, regular_filter, corrupted_filter])
    assert len(results) == 3

    # 验证 default
    assert results[0]["id"] == "all"
    assert results[0]["title"] == "全部"
    assert results[0]["include_peers"] == []
    assert results[0]["pinned_peers"] == []
    assert results[0]["exclude_peers"] == []

    # 验证 chatlist
    assert results[1]["id"] == 2
    assert results[1]["title"] == "工作群"
    assert results[1]["emoticon"] == "💼"
    assert results[1]["pinned_peers"] == [-1000000012345]
    assert results[1]["include_peers"] == [67890]
    assert results[1]["exclude_peers"] == []

    # 验证 normal filter
    assert results[2]["id"] == 3
    assert results[2]["title"] == "加密货币"
    assert results[2]["emoticon"] == "💰"
    assert results[2]["include_peers"] == [-9876]
    assert results[2]["exclude_peers"] == [11111]


@pytest.mark.asyncio
async def test_list_account_folders_uses_account_lock():
    """测试获取文件夹列表时进行前置代理校验并在账号锁保护下调用。"""
    service = DummyDiscoveryService()
    service.verify_account_proxy = AsyncMock()

    mock_client = MagicMock()
    mock_client.is_connected = False
    mock_client.connect = AsyncMock()
    mock_client.disconnect = AsyncMock()

    filter1 = raw.types.DialogFilterDefault()
    filter2 = raw.types.DialogFilter(
        id=10,
        title="测试文件夹",
        pinned_peers=[],
        include_peers=[],
        exclude_peers=[],
    )
    mock_response = raw.types.messages.DialogFilters(filters=[filter1, filter2])
    mock_client.invoke = AsyncMock(return_value=mock_response)

    service._build_account_client = MagicMock(return_value=(mock_client, {"scheme": "socks5"}))

    lock_acquired = False

    class MockLockContext:
        async def __aenter__(self):
            nonlocal lock_acquired
            lock_acquired = True
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            nonlocal lock_acquired
            lock_acquired = False

    with patch(
        "backend.services.telegram.dialog_discovery.acquire_account_lock_with_timeout",
        return_value=MockLockContext(),
    ) as mock_acquire_lock:
        folders = await service.list_account_folders("my_acc", timeout_seconds=8.0)

        service.verify_account_proxy.assert_awaited_once_with("my_acc", {"scheme": "socks5"})
        mock_acquire_lock.assert_called_once_with("my_acc", timeout=8.0)
        assert mock_client.connect.await_count == 1
        assert mock_client.disconnect.await_count == 1
        assert len(folders) == 2
        assert folders[0]["id"] == "all"
        assert folders[1]["id"] == 10
        assert folders[1]["title"] == "测试文件夹"


@pytest.mark.asyncio
async def test_list_forum_topics_returns_empty_for_non_forum():
    """测试当目标群组非 forum 或发生 RPC 限制时，优雅返回空列表而不是 500。"""
    service = DummyDiscoveryService()
    service.verify_account_proxy = AsyncMock()

    mock_client = MagicMock()
    mock_client.is_connected = True
    service._build_account_client = MagicMock(return_value=(mock_client, None))

    class MockLockContext:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch(
        "backend.services.telegram.dialog_discovery.acquire_account_lock_with_timeout",
        return_value=MockLockContext(),
    ):
        # 1. safe_get_forum_topics 返回空
        with patch(
            "backend.services.telegram.dialog_discovery.safe_get_forum_topics",
            new_callable=AsyncMock,
        ) as mock_safe_topics:
            mock_safe_topics.return_value = []
            topics = await service.list_forum_topics("my_acc", chat_id=-100123456789)
            assert topics == []

        # 2. safe_get_forum_topics 抛出各种非 Forum / 权限异常
        with patch(
            "backend.services.telegram.dialog_discovery.safe_get_forum_topics",
            new_callable=AsyncMock,
        ) as mock_safe_topics:
            mock_safe_topics.side_effect = RuntimeError("ChannelInvalid: The channel is invalid or not a forum")
            topics = await service.list_forum_topics("my_acc", chat_id=-100123456789)
            assert topics == []

        # 3. 正常返回 ForumTopic 列表
        with patch(
            "backend.services.telegram.dialog_discovery.safe_get_forum_topics",
            new_callable=AsyncMock,
        ) as mock_safe_topics:
            mock_topic = _make_mock_forum_topic(
                id=42,
                date=1700000000,
                title="签到专用话题",
                icon_color=0xFFFFFF,
                top_message=999,
                read_inbox_max_id=999,
                read_outbox_max_id=999,
                unread_count=0,
                unread_mentions_count=0,
                unread_reactions_count=0,
                from_id=raw.types.PeerUser(user_id=1001),
                notify_settings=raw.types.PeerNotifySettings(),
            )
            mock_safe_topics.return_value = [mock_topic]
            topics = await service.list_forum_topics("my_acc", chat_id=-100123456789)
            assert len(topics) == 1
            assert topics[0]["id"] == 42
            assert topics[0]["title"] == "签到专用话题"
            assert topics[0]["top_message"] == 999


def test_folders_route_success(api_client, db):  # noqa: F811
    """测试 GET /api/accounts/{account_name}/folders 成功与锁超时 409。"""
    token = _login(api_client)

    svc = MagicMock()
    svc.account_exists.return_value = True
    svc.list_account_folders = AsyncMock(
        return_value=[
            {"id": "all", "title": "全部", "include_peers": [], "pinned_peers": [], "exclude_peers": []},
            {"id": 1, "title": "重要", "include_peers": [-100123], "pinned_peers": [], "exclude_peers": []},
        ]
    )

    with patch("backend.api.routes.accounts.get_telegram_service", return_value=svc):
        resp = api_client.get(
            "/api/accounts/acc1/folders",
            headers=_auth(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["id"] == "all"
        assert data[0]["title"] == "全部"
        assert data[1]["id"] == 1
        assert data[1]["include_peers"] == [-100123]

        # 锁超时 -> 409 ACCOUNT_BUSY
        svc.list_account_folders.side_effect = AccountLockTimeout("busy")
        busy_resp = api_client.get(
            "/api/accounts/acc1/folders",
            headers=_auth(token),
        )
        assert busy_resp.status_code == 409
        assert busy_resp.json()["detail"] == "ACCOUNT_BUSY"


def test_topics_route_success(api_client, db):  # noqa: F811
    """测试 GET /api/accounts/{account_name}/chats/{chat_id}/topics 成功与锁超时 409。"""
    token = _login(api_client)

    svc = MagicMock()
    svc.account_exists.return_value = True
    svc.list_forum_topics = AsyncMock(
        return_value=[
            {"id": 101, "title": "日常讨论", "top_message": 50, "closed": False, "pinned": True},
            {"id": 102, "title": "归档打卡", "top_message": 80, "closed": True, "pinned": False},
        ]
    )

    with patch("backend.api.routes.accounts.get_telegram_service", return_value=svc):
        resp = api_client.get(
            "/api/accounts/acc1/chats/-100123456789/topics",
            headers=_auth(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["id"] == 101
        assert data[0]["title"] == "日常讨论"
        assert data[0]["pinned"] is True
        assert data[1]["id"] == 102
        assert data[1]["closed"] is True

        # 锁超时 -> 409 ACCOUNT_BUSY
        svc.list_forum_topics.side_effect = AccountLockTimeout("busy")
        busy_resp = api_client.get(
            "/api/accounts/acc1/chats/-100123456789/topics",
            headers=_auth(token),
        )
        assert busy_resp.status_code == 409
        assert busy_resp.json()["detail"] == "ACCOUNT_BUSY"

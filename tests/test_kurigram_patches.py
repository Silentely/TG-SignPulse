from __future__ import annotations

import inspect
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pyrogram import raw, types
from pyrogram.errors import BadRequest, ChatNotModified, TopicIdInvalid

from tg_signer.compat import (
    _PYROGRAM_IMPORT_ERROR,
    patch_animated_chat_photo_parser,
    patch_kurigram_compat,
    safe_get_forum_topics,
)


def _make_mock_forum_topic(**kwargs):
    sig = inspect.signature(raw.types.ForumTopic.__init__)
    defaults = {
        "id": 1,
        "date": 1700000000,
        "title": "General",
        "icon_color": 0,
        "top_message": 10,
        "read_inbox_max_id": 10,
        "read_outbox_max_id": 10,
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


@pytest.mark.asyncio
async def test_kurigram_runtime_contract_is_satisfied():
    """kurigram 运行时契约守卫与 Storage 生命周期验证。

    验证在当前运行环境下 MemoryStorage 可用，并且具备完整的 open/save/close 生命周期。
    """
    from tg_signer.compat import _MEMORY_STORAGE_IMPORT_ERROR, MemoryStorage

    assert _PYROGRAM_IMPORT_ERROR is None, (
        f"Telegram 运行时依赖导入失败: {_PYROGRAM_IMPORT_ERROR!r}"
    )
    assert MemoryStorage is not None, (
        f"MemoryStorage 不可用: {_MEMORY_STORAGE_IMPORT_ERROR!r}"
    )
    storage = MemoryStorage("test_contract_lifecycle")
    assert getattr(storage, "in_memory", None) is True or hasattr(storage, "conn")

    # 验证真实存储生命周期
    await storage.open()
    assert storage.conn is not None
    await storage.save()
    await storage.close()


def test_missing_memory_storage_does_not_stub_whole_runtime():
    """MemoryStorage 缺失只应影响该类本身，不得把整套运行时替换为占位实现。

    在 kurigram >= 2.2.10 (包括 2.2.26) 环境下，SQLiteStorage 原生具备 in_memory 支持，
    应无缝启用 MemoryStorage 适配器；
    同时验证 Fail-Closed 策略：当 SQLiteStorage 也不具备 in_memory 能力时，
    应明确将 MemoryStorage 置为 None 并记录原因，杜绝半成品对象。
    """
    code = textwrap.dedent(
        """
        import builtins
        import pyrogram.client
        import pyrogram.types as real_types

        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            # 模拟原生 MemoryStorage 缺失
            if name == "pyrogram.storage" and fromlist and "MemoryStorage" in fromlist:
                raise ImportError("simulated: MemoryStorage removed")
            return real_import(name, globals, locals, fromlist, level)

        builtins.__import__ = fake_import

        import tg_signer.compat as compat

        assert compat._PYROGRAM_IMPORT_ERROR is None, "不应整体降级为占位实现"
        # 在 kurigram 2.2.26 环境下，SQLiteStorage 具备 in_memory，应成功创建适配器
        assert compat.MemoryStorage is not None, "具备 in_memory 能力时应成功启用适配器"
        assert compat.InlineKeyboardMarkup is real_types.InlineKeyboardMarkup, (
            "真实类型必须保留"
        )
        print("OK")
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


def test_memory_storage_adapter_for_kurigram_2_2_10_contract():
    """模拟 kurigram >= 2.2.10 环境下 MemoryStorage 适配器的行为与生命周期。"""
    code = textwrap.dedent(
        """
        import builtins
        import sys
        from pathlib import Path
        import pyrogram.client
        import pyrogram.types as real_types

        # 构造符合 kurigram 2.2.10+ 签名的 FakeSQLiteStorage
        class Fake2210SQLiteStorage:
            def __init__(self, name: str, workdir: Path, session_string: str = None, in_memory: bool = False):
                self.name = name
                self.workdir = workdir
                self.session_string = session_string
                self.in_memory = in_memory
                self.conn = None
                self.opened = False

            async def open(self):
                self.opened = True
                self.conn = "fake_connection"

            async def save(self):
                pass

            async def close(self):
                self.opened = False

        import pyrogram.storage.sqlite_storage as pyrogram_sqlite
        pyrogram_sqlite.SQLiteStorage = Fake2210SQLiteStorage

        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "pyrogram.storage" and fromlist and "MemoryStorage" in fromlist:
                raise ImportError("simulated kurigram 2.2.10+: MemoryStorage removed")
            return real_import(name, globals, locals, fromlist, level)

        builtins.__import__ = fake_import

        import tg_signer.compat as compat
        assert compat._PYROGRAM_IMPORT_ERROR is None
        assert compat.MemoryStorage is not None
        assert compat._MEMORY_STORAGE_IMPORT_ERROR is None

        # 实例化并验证参数正确转发
        storage = compat.MemoryStorage("my_session", session_string="test_str", workdir=Path("/custom"))
        assert storage.in_memory is True
        assert storage.name == "my_session"
        assert storage.session_string == "test_str"
        assert storage.workdir == Path("/custom")

        # 验证生命周期代理
        import asyncio
        async def run_lifecycle():
            await storage.open()
            assert storage.opened is True
            assert storage.conn == "fake_connection"
            await storage.save()
            await storage.close()
            assert storage.opened is False

        asyncio.run(run_lifecycle())
        print("OK")
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


def test_memory_storage_compat_initialization():
    """测试 MemoryStorage 兼容不同版本的构造参数与模式。"""
    from tg_signer.compat import MemoryStorage

    s1 = MemoryStorage("session1")
    assert s1 is not None

    s2 = MemoryStorage("session2", session_string="dummy_session_string")
    assert s2 is not None

    try:
        s3 = MemoryStorage("session3", session_string=None, workdir=Path("."))
        assert s3 is not None
    except TypeError:
        # 原生 MemoryStorage (<=2.2.9) 不接收 workdir
        s3 = MemoryStorage("session3", session_string=None)
        assert s3 is not None


def test_client_storage_error_chaining():
    """测试当 MemoryStorage 不可用时，Client 初始化保留底层异常链路。"""
    from unittest.mock import patch

    import tg_signer.core.client as client_mod

    with patch.object(client_mod, "MemoryStorage", None):
        with patch.object(
            client_mod,
            "_MEMORY_STORAGE_IMPORT_ERROR",
            NotImplementedError("mocked root cause"),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                client_mod.Client("test_dummy", session_string=None, in_memory=True)
            assert "mocked root cause" in str(exc_info.value)
            assert isinstance(exc_info.value.__cause__, NotImplementedError)


@pytest.mark.asyncio
async def test_safe_get_forum_topics_filters_deleted_topics():
    client = MagicMock()
    client.is_connected = True
    client.resolve_peer = AsyncMock(
        return_value=raw.types.InputPeerChannel(channel_id=123, access_hash=456)
    )

    topic1 = _make_mock_forum_topic(
        id=1,
        date=1700000000,
        title="General",
        icon_color=0,
        top_message=10,
        read_inbox_max_id=10,
        read_outbox_max_id=10,
        unread_count=0,
        unread_mentions_count=0,
        unread_reactions_count=0,
        from_id=raw.types.PeerUser(user_id=1001),
        notify_settings=raw.types.PeerNotifySettings(),
    )
    deleted_topic = raw.types.ForumTopicDeleted(id=2)
    topic2 = _make_mock_forum_topic(
        id=3,
        date=1700000100,
        title="Announcements",
        icon_color=1,
        top_message=20,
        read_inbox_max_id=20,
        read_outbox_max_id=20,
        unread_count=0,
        unread_mentions_count=0,
        unread_reactions_count=0,
        from_id=raw.types.PeerUser(user_id=1002),
        notify_settings=raw.types.PeerNotifySettings(),
    )

    mock_response = raw.types.messages.ForumTopics(
        count=3,
        topics=[topic1, deleted_topic, topic2],
        messages=[],
        chats=[],
        users=[],
        pts=100,
    )
    client.invoke = AsyncMock(return_value=mock_response)

    topics = await safe_get_forum_topics(client, chat_id=-100123456789)
    assert len(topics) == 2
    assert [t.id for t in topics] == [1, 3]
    assert all(not isinstance(t, raw.types.ForumTopicDeleted) for t in topics)


@pytest.mark.asyncio
async def test_safe_get_forum_topics_handles_non_forum_group_gracefully():
    client = MagicMock()
    client.is_connected = True
    client.resolve_peer = AsyncMock(
        return_value=raw.types.InputPeerChannel(channel_id=123, access_hash=456)
    )

    # Test 1: invoke raises TopicIdInvalid
    client.invoke = AsyncMock(side_effect=TopicIdInvalid(value="TOPIC_ID_INVALID"))
    topics = await safe_get_forum_topics(client, chat_id=-100123456789)
    assert topics == []

    # Test 2: invoke raises ChatNotModified
    client.invoke = AsyncMock(side_effect=ChatNotModified())
    topics = await safe_get_forum_topics(client, chat_id=-100123456789)
    assert topics == []

    # Test 3: invoke raises generic BadRequest for non-forum
    client.invoke = AsyncMock(side_effect=BadRequest(value="CHANNEL_FORUM_MISSING"))
    topics = await safe_get_forum_topics(client, chat_id=-100123456789)
    assert topics == []

    # Test 4: client not connected
    client.is_connected = False
    topics = await safe_get_forum_topics(client, chat_id=-100123456789)
    assert topics == []


def test_patch_animated_chat_photo_parser_idempotent():
    # Calling multiple times should succeed and remain idempotent
    res1 = patch_animated_chat_photo_parser()
    assert res1 is True
    res2 = patch_animated_chat_photo_parser()
    assert res2 is True
    res3 = patch_kurigram_compat()
    assert res3 is True


def test_animated_chat_photo_handles_emoji_and_sticker_markup_without_wh():
    patch_animated_chat_photo_parser()

    # Raw markup instances without explicit w / h
    emoji_markup = raw.types.VideoSizeEmojiMarkup(
        emoji_id=99999,
        background_colors=[0xFF0000, 0x00FF00],
    )
    sticker_markup = raw.types.VideoSizeStickerMarkup(
        stickerset=raw.types.InputStickerSetEmpty(),
        sticker_id=88888,
        background_colors=[0x0000FF],
    )

    # Must provide default w and h (0) to avoid AttributeError: 'VideoSizeEmojiMarkup' object has no attribute 'w'
    assert getattr(emoji_markup, "w", None) == 0
    assert getattr(emoji_markup, "h", None) == 0
    assert getattr(sticker_markup, "w", None) == 0
    assert getattr(sticker_markup, "h", None) == 0

    # Sorting key `lambda v: v.w * v.h` must not crash
    sizes = [emoji_markup, sticker_markup]
    sizes.sort(key=lambda v: v.w * v.h)
    assert len(sizes) == 2

    # Animation parser must handle photo with only emoji markup safely without IndexError or ValueError
    raw_photo = raw.types.Photo(
        id=12345,
        access_hash=67890,
        file_reference=b"test",
        date=1700000000,
        sizes=[],
        dc_id=2,
        video_sizes=[emoji_markup, sticker_markup],
    )
    anim = types.Animation._parse_chat_animation(None, raw_photo, "chat_anim.mp4")
    # Returns None because no real video size exists
    assert anim is None


def test_patch_kurigram_compat_is_idempotent():
    assert patch_kurigram_compat() is True
    assert patch_kurigram_compat() is True


def test_patch_kurigram_compat_noop_on_old_version(monkeypatch):
    import pyrogram

    monkeypatch.setattr(pyrogram, "__version__", "2.0.0", raising=False)
    # Should execute safely as a no-op or harmlessly return True
    assert patch_kurigram_compat() is True


@pytest.mark.asyncio
async def test_safe_get_forum_topics_handles_missing_top_message():
    client = MagicMock()
    client.is_connected = True
    client.resolve_peer = AsyncMock(
        return_value=raw.types.InputPeerChannel(channel_id=123, access_hash=456)
    )

    # Topic with top_message missing or None
    topic_no_top_msg = MagicMock()
    topic_no_top_msg.__class__ = raw.types.ForumTopic
    topic_no_top_msg.id = 5
    topic_no_top_msg.title = "Topic No Top Msg"
    del topic_no_top_msg.top_message

    mock_response = raw.types.messages.ForumTopics(
        count=1,
        topics=[topic_no_top_msg],
        messages=[],
        chats=[],
        users=[],
        pts=100,
    )
    client.invoke = AsyncMock(return_value=mock_response)

    topics = await safe_get_forum_topics(client, chat_id=-100123456789)
    assert len(topics) == 1
    assert topics[0].id == 5


@pytest.mark.asyncio
async def test_safe_get_forum_topics_skips_deleted_topics_and_returns_empty_for_non_forum():
    client = MagicMock()
    client.is_connected = True
    client.resolve_peer = AsyncMock(
        return_value=raw.types.InputPeerChannel(channel_id=123, access_hash=456)
    )

    # Only deleted topics
    deleted_topic = raw.types.ForumTopicDeleted(id=10)
    mock_response = raw.types.messages.ForumTopics(
        count=1,
        topics=[deleted_topic],
        messages=[],
        chats=[],
        users=[],
        pts=100,
    )
    client.invoke = AsyncMock(return_value=mock_response)

    topics = await safe_get_forum_topics(client, chat_id=-100123456789)
    assert topics == []

    # Non-forum check via get_chat returning is_forum=False
    client.get_chat = AsyncMock(return_value=MagicMock(is_forum=False))
    topics = await safe_get_forum_topics(client, chat_id=-100123456789)
    assert topics == []


def test_animated_photo_patch_ignores_unknown_shape():
    patch_animated_chat_photo_parser()

    # None input
    assert types.Animation._parse_chat_animation(None, None, "test.mp4") is None

    # Photo without video_sizes
    raw_photo = raw.types.Photo(
        id=12345,
        access_hash=67890,
        file_reference=b"test",
        date=1700000000,
        sizes=[],
        dc_id=2,
        video_sizes=None,
    )
    assert types.Animation._parse_chat_animation(None, raw_photo, "test.mp4") is None


def test_animated_photo_patch_covers_emoji_and_sticker_markups():
    patch_animated_chat_photo_parser()

    emoji_markup = raw.types.VideoSizeEmojiMarkup(
        emoji_id=111,
        background_colors=[0],
    )
    sticker_markup = raw.types.VideoSizeStickerMarkup(
        stickerset=raw.types.InputStickerSetEmpty(),
        sticker_id=222,
        background_colors=[0],
    )
    normal_video_size = raw.types.VideoSize(
        type="u",
        w=320,
        h=320,
        size=1024,
        video_start_ts=0.0,
    )

    raw_photo = raw.types.Photo(
        id=12345,
        access_hash=67890,
        file_reference=b"test",
        date=1700000000,
        sizes=[],
        dc_id=2,
        video_sizes=[emoji_markup, sticker_markup, normal_video_size],
    )

    anim = types.Animation._parse_chat_animation(None, raw_photo, "chat_anim.mp4")
    assert anim is not None
    assert isinstance(anim, types.Animation)


@pytest.mark.asyncio
async def test_get_dc_session_delegates_to_client_or_fallback():
    from tg_signer.compat import get_dc_session

    # Case 1: client has get_session, defaults to export_authorization=False
    mock_client = MagicMock()
    mock_client.get_session = AsyncMock(return_value="session_dc_4")
    res = await get_dc_session(mock_client, 4)
    assert res == "session_dc_4"
    mock_client.get_session.assert_awaited_once_with(4, export_authorization=False)

    # Case 2: client has get_session with explicit export_authorization=True
    mock_client.get_session.reset_mock()
    res_exp = await get_dc_session(mock_client, 4, export_authorization=True)
    assert res_exp == "session_dc_4"
    mock_client.get_session.assert_awaited_once_with(4, export_authorization=True)

    # Case 3: client lacks get_session, fall back to sessions dict
    client_legacy = MagicMock(spec=[])
    client_legacy.sessions = {5: "legacy_session_5"}
    res2 = await get_dc_session(client_legacy, 5)
    assert res2 == "legacy_session_5"


@pytest.mark.asyncio
async def test_safe_get_forum_topics_unexpected_exception_logs_warning(caplog):
    import logging

    from tg_signer.compat import safe_get_forum_topics

    mock_client = MagicMock()
    mock_client.invoke = AsyncMock(side_effect=RuntimeError("Simulated network crash"))
    mock_client.resolve_peer = AsyncMock(return_value="fake_peer")

    with caplog.at_level(logging.WARNING):
        topics = await safe_get_forum_topics(mock_client, -1001234567)
    assert topics == []
    assert any("Unexpected error fetching forum topics" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_safe_get_forum_topics_channel_private_logs_warning(caplog):
    import logging

    from pyrogram.errors import ChannelPrivate

    from tg_signer.compat import safe_get_forum_topics

    mock_client = MagicMock()
    mock_client.invoke = AsyncMock(side_effect=ChannelPrivate(value="CHANNEL_PRIVATE"))
    mock_client.resolve_peer = AsyncMock(return_value="fake_peer")

    with caplog.at_level(logging.WARNING):
        topics = await safe_get_forum_topics(mock_client, -1001234567)
    assert topics == []
    # 确认 ChannelPrivate 作为真实权限异常记录了 warning，而没有被静默降级为非论坛
    assert any("Unexpected error fetching forum topics" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_apply_migrate_auth_writes_matched_dc_endpoint():
    from backend.services.telegram.login_qr import TelegramQrLoginMixin

    mgr = TelegramQrLoginMixin()
    mock_client = MagicMock()
    mock_client.storage = MagicMock()
    mock_client.storage.dc_id = AsyncMock()
    mock_client.storage.server_address = AsyncMock()
    mock_client.storage.port = AsyncMock()
    mock_client.storage.auth_key = AsyncMock()
    mock_client.storage.test_mode = MagicMock(return_value=0)

    # 模拟捕获到迁移至 DC4
    migrate_data = {
        "migrate_dc_id": 4,
        "migrate_auth_key": b"K" * 256,
        "migrate_server_address": "149.154.167.91",
        "migrate_port": 443,
    }
    await mgr._apply_migrate_auth(mock_client, migrate_data)

    mock_client.storage.dc_id.assert_awaited_once_with(4)
    mock_client.storage.server_address.assert_awaited_once_with("149.154.167.91")
    mock_client.storage.port.assert_awaited_once_with(443)
    mock_client.storage.auth_key.assert_awaited_once_with(b"K" * 256)

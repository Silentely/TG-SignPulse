from __future__ import annotations

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


def test_kurigram_runtime_contract_is_satisfied():
    """kurigram 运行时契约守卫。

    kurigram 2.2.10 起移除了 pyrogram.storage.MemoryStorage，而 string 会话模式依赖它。
    若依赖解析到该版本，tg_signer.compat 会整体导入失败并静默降级为占位实现，
    表现为大量误导性的「X() takes no arguments」报错。此用例把该契约显式固化：
    缺失时直接失败并指出应使用的版本区间，而不是让下游用例报出难以定位的错误。
    """
    from tg_signer.compat import MemoryStorage

    assert _PYROGRAM_IMPORT_ERROR is None, (
        f"Telegram 运行时依赖导入失败: {_PYROGRAM_IMPORT_ERROR!r}"
    )
    assert MemoryStorage is not None, (
        "当前 kurigram 版本不提供 pyrogram.storage.MemoryStorage（2.2.10 起已移除），"
        "请安装 kurigram>=2.2.7,<2.2.10"
    )


def test_missing_memory_storage_does_not_stub_whole_runtime():
    """MemoryStorage 缺失只应影响该类本身，不得把整套运行时替换为占位实现。

    否则真实类型（如 InlineKeyboardMarkup）会被替换成不接受参数的占位类，
    在离故障点很远的用例里报出「X() takes no arguments」，难以定位。
    """
    code = textwrap.dedent(
        """
        import builtins

        # 先让 pyrogram 正常加载，避免干扰其内部对 pyrogram.storage 的合法使用
        import pyrogram.types as real_types

        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            # 仅模拟「2.2.10+ 已移除 MemoryStorage」这一件事
            if name == "pyrogram.storage" and fromlist and "MemoryStorage" in fromlist:
                raise ImportError("simulated: MemoryStorage removed")
            return real_import(name, globals, locals, fromlist, level)

        builtins.__import__ = fake_import

        import tg_signer.compat as compat

        assert compat._PYROGRAM_IMPORT_ERROR is None, "不应整体降级为占位实现"
        assert compat.MemoryStorage is None, "MemoryStorage 应为 None"
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


@pytest.mark.asyncio
async def test_safe_get_forum_topics_filters_deleted_topics():
    client = MagicMock()
    client.is_connected = True
    client.resolve_peer = AsyncMock(return_value=raw.types.InputPeerChannel(channel_id=123, access_hash=456))

    topic1 = raw.types.ForumTopic(
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
    topic2 = raw.types.ForumTopic(
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
    client.resolve_peer = AsyncMock(return_value=raw.types.InputPeerChannel(channel_id=123, access_hash=456))

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
    client.resolve_peer = AsyncMock(return_value=raw.types.InputPeerChannel(channel_id=123, access_hash=456))

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
    client.resolve_peer = AsyncMock(return_value=raw.types.InputPeerChannel(channel_id=123, access_hash=456))

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

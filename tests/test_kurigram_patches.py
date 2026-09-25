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

from tg_signer import compat as compat_module
from tg_signer.compat import (
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


def _make_valid_session_string(dc_id: int = 2, api_id: int = 123456, user_id: int = 777000) -> str:
    """构造可通过 is_valid_session_string 校验的新版 session_string。"""
    import base64
    import struct

    packed = struct.pack(
        ">BI?256sQ?", dc_id, api_id, False, bytes(range(256)), user_id, False
    )
    return base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")


@pytest.mark.asyncio
async def test_kurigram_runtime_contract_is_satisfied():
    """kurigram 运行时契约守卫与内存存储生命周期验证。

    项目钉死 kurigram==2.2.26：SQLiteStorage 原生支持 in_memory + session_string，
    Client.__init__ 会自动装配内存存储，不再需要自研 MemoryStorage 适配层。
    """
    from pyrogram.storage.sqlite_storage import SQLiteStorage

    assert compat_module._PYROGRAM_IMPORT_ERROR is None, (
        f"Telegram 运行时依赖导入失败: {compat_module._PYROGRAM_IMPORT_ERROR!r}"
    )
    # 内存存储生命周期（string 会话模式的承载）
    storage = SQLiteStorage(
        "test_contract_lifecycle",
        workdir=Path("."),
        session_string=_make_valid_session_string(),
        in_memory=True,
    )
    assert storage.in_memory is True
    assert storage.session_string

    await storage.open()
    try:
        assert storage.conn is not None
        assert await storage.user_id() == 777000
        assert await storage.dc_id() == 2
        assert compat_module.is_valid_session_string(storage.session_string)
    finally:
        await storage.close()


def test_missing_pyrogram_does_not_stub_whole_runtime():
    """pyrogram 导入失败只应降级占位符号，不得污染正常环境的真实类型。

    同时守护 session_string 校验在依赖降级时依然可用（字面量常量兜底）。
    """
    code = textwrap.dedent(
        """
        import builtins
        import pyrogram.types as real_types

        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "pyrogram":
                raise ImportError("simulated: pyrogram unavailable")
            return real_import(name, globals, locals, fromlist, level)

        builtins.__import__ = fake_import

        import tg_signer.compat as compat

        assert compat._PYROGRAM_IMPORT_ERROR is not None, "应记录导入失败原因"
        assert compat.InlineKeyboardMarkup is not real_types.InlineKeyboardMarkup, (
            "降级环境必须是占位实现"
        )
        # 校验逻辑不依赖 pyrogram 真实类，字面量兜底保证可用
        assert compat.is_valid_session_string("garbage") is False
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


def test_native_sqlite_storage_in_memory_session_string_contract():
    """kurigram 2.2.26 原生 SQLiteStorage 必须完整转发 in_memory + session_string。"""
    from pyrogram.storage.sqlite_storage import SQLiteStorage

    session_string = _make_valid_session_string()
    storage = SQLiteStorage(
        "my_session",
        workdir=Path("/custom"),
        session_string=session_string,
        in_memory=True,
    )
    assert storage.in_memory is True
    assert storage.name == "my_session"
    assert storage.session_string == session_string
    # in_memory 模式下 database 直接解析为 ":memory:"，与文件路径无关
    assert storage.database == ":memory:"


def test_is_valid_session_string_accepts_and_rejects():
    """session_string 校验：接受 pyrogram 新旧格式，拒绝 Telethon 前缀与损坏数据。"""
    from tg_signer.compat import is_valid_session_string

    # 新版格式（含 api_id）
    assert is_valid_session_string(_make_valid_session_string()) is True

    # 旧格式（无 api_id）：351/356 两种 user_id 宽度
    import base64
    import struct

    old_32 = base64.urlsafe_b64encode(
        struct.pack(">B?256sI?", 2, False, bytes(range(256)), 777000, False)
    ).decode("ascii").rstrip("=")
    old_64 = base64.urlsafe_b64encode(
        struct.pack(">B?256sQ?", 2, False, bytes(range(256)), 777000, False)
    ).decode("ascii").rstrip("=")
    assert len(old_32) == 351 and is_valid_session_string(old_32) is True
    assert len(old_64) == 356 and is_valid_session_string(old_64) is True

    # 历史错误导出产生的超长串（357）必须判坏，避免上游解码阶段抛错
    assert is_valid_session_string(old_64 + "A") is False
    # Telethon 风格前缀与各类损坏输入
    assert is_valid_session_string("1" + old_64) is False
    assert is_valid_session_string("not-base64!!!") is False
    assert is_valid_session_string("") is False
    assert is_valid_session_string(None) is False
    assert is_valid_session_string(12345) is False


@pytest.mark.asyncio
async def test_in_memory_client_without_session_string_fails_closed():
    """in_memory 模式无可用 session_string 时必须明确报错，且不得伪装成「会话失效」。

    空内存库 connect() 同样返回 False；消息刻意不含 "Session invalid"，
    避免上层把配置缺失误判为账号需重新登录。引用计数必须回滚，不残留半初始化客户端。
    """
    import tg_signer.core.client as client_mod

    client = client_mod.Client("test_dummy", session_string=None, in_memory=True)
    with pytest.raises(ConnectionError) as exc_info:
        async with client:
            pass
    message = str(exc_info.value)
    assert "session_string" in message
    assert "Session invalid" not in message
    assert client_mod._CLIENT_REFS.get(client.key, 0) == 0
    assert client.key not in client_mod._CLIENT_INSTANCES


@pytest.mark.asyncio
async def test_in_memory_client_preloads_valid_session_string(tmp_path: Path):
    """in_memory 且未显式传串时，必须从会话目录预加载合法 session_string 并原生装配。"""
    import tg_signer.core.client as client_mod
    from tg_signer.core import _CLIENT_INSTANCES

    keys_before = set(_CLIENT_INSTANCES.keys())
    try:
        session_string = _make_valid_session_string()
        (tmp_path / "preload_test.session_string").write_text(
            session_string, encoding="utf-8"
        )
        client = client_mod.Client(
            "preload_test", in_memory=True, workdir=tmp_path, api_id=1, api_hash="h"
        )
        assert client.session_string == session_string
        # 父类原生装配：内存存储 + 携带 session_string
        assert client.storage.in_memory is True
        assert client.storage.session_string == session_string
    finally:
        for k in list(_CLIENT_INSTANCES.keys()):
            if k not in keys_before:
                _CLIENT_INSTANCES.pop(k, None)


@pytest.mark.asyncio
async def test_in_memory_client_discards_corrupted_session_string(tmp_path: Path):
    """损坏的 session_string 缓存必须被删除并按缺失处理（自愈，而非启动即崩）。"""
    import tg_signer.core.client as client_mod
    from tg_signer.core import _CLIENT_INSTANCES

    keys_before = set(_CLIENT_INSTANCES.keys())
    try:
        cache = tmp_path / "corrupt_test.session_string"
        # 历史错误导出产生的 357 长度坏串
        cache.write_text("A" * 357, encoding="utf-8")
        client = client_mod.Client(
            "corrupt_test", in_memory=True, workdir=tmp_path, api_id=1, api_hash="h"
        )
        assert client.session_string is None
        assert not cache.exists(), "坏缓存必须被删除以便下次从 .session 重导"

        with pytest.raises(ConnectionError) as exc_info:
            async with client:
                pass
        assert "Session invalid" not in str(exc_info.value)
    finally:
        for k in list(_CLIENT_INSTANCES.keys()):
            if k not in keys_before:
                _CLIENT_INSTANCES.pop(k, None)


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
async def test_chat_photo_parse_patch_keeps_await_contract():
    """回归：ChatPhoto._parse 在 kurigram 2.2.10+ 是协程函数，包装后必须仍可 await。

    同步桩在空照片分支返回裸 None，会被 User._parse_full 的 ``await`` 拒收，抛出
    ``TypeError: object NoneType can't be used in 'await' expression``，
    并在 Client.__aenter__ 中被误报为 ``Session invalid``。
    """
    patch_animated_chat_photo_parser()
    assert inspect.iscoroutinefunction(types.ChatPhoto._parse)

    # 与 User._parse_full 中 personal_photo / fallback_photo 缺省时的调用形态一致
    assert await types.ChatPhoto._parse(None, None, 111, 0) is None


@pytest.mark.asyncio
async def test_chat_photo_parse_patch_delegates_real_photo():
    patch_animated_chat_photo_parser()

    photo = await types.ChatPhoto._parse(
        None, raw.types.UserProfilePhoto(photo_id=111, dc_id=2), 111, 0
    )
    assert isinstance(photo, types.ChatPhoto)


@pytest.mark.asyncio
async def test_chat_photo_parse_patch_guards_photo_without_sizes():
    """兜底分支同样保持协程契约：上游对 sizes 为空的 Photo 会抛 IndexError。"""
    patch_animated_chat_photo_parser()

    empty_photo = raw.types.Photo(
        id=1,
        access_hash=2,
        file_reference=b"x",
        date=1700000000,
        sizes=[],
        dc_id=2,
    )
    assert await types.ChatPhoto._parse(None, empty_photo, 111, 0) is None


def test_patch_matches_sync_original_contract(monkeypatch):
    """原函数为同步实现时，包装器必须保持同步（不得把返回值变成协程）。"""

    def sync_chat_photo_parse(client, chat_photo, peer_id, peer_access_hash=0):
        return "sync-photo"

    def sync_chat_animation_parse(client, video, file_name):
        return "sync-anim"

    monkeypatch.setattr(types.ChatPhoto, "_parse", sync_chat_photo_parse)
    monkeypatch.setattr(
        types.Animation, "_parse_chat_animation", sync_chat_animation_parse
    )
    monkeypatch.setattr(compat_module, "_ANIMATED_PHOTO_PATCHED", False)

    assert patch_animated_chat_photo_parser() is True
    assert not inspect.iscoroutinefunction(types.ChatPhoto._parse)
    assert not inspect.iscoroutinefunction(types.Animation._parse_chat_animation)
    assert types.ChatPhoto._parse(None, None, 111, 0) is None
    assert types.Animation._parse_chat_animation(None, None, "x.mp4") is None


@pytest.mark.asyncio
async def test_get_me_parses_self_user_with_missing_personal_photo():
    """回归：get_me() 解析自身用户时必须容忍缺省的 personal_photo / fallback_photo。

    修复前该路径抛 ``TypeError: object NoneType can't be used in 'await' expression``，
    并被 ``Client.__aenter__`` 包装成 ``ConnectionError: Session invalid``，
    表现为任务启动即报「会话失效」。
    """
    import tempfile
    from unittest.mock import AsyncMock

    from tg_signer.core.client import Client

    self_user = raw.types.User(
        id=111,
        is_self=True,
        first_name="Tester",
        username="tester",
        access_hash=999,
        status=raw.types.UserStatusEmpty(),
    )
    full_user = raw.types.UserFull(
        id=111,
        settings=raw.types.PeerSettings(),
        notify_settings=raw.types.PeerNotifySettings(),
        common_chats_count=0,
        profile_photo=raw.types.UserProfilePhoto(photo_id=111, dc_id=2),
    )
    response = raw.types.users.UserFull(
        full_user=full_user, users=[self_user], chats=[]
    )

    with tempfile.TemporaryDirectory() as workdir:
        client = Client(
            "regression_probe",
            api_id=611335,
            api_hash="d524b414d21f4d37f08684c1df41ac9c",
            workdir=Path(workdir),
            in_memory=True,
            session_string="regression_probe",
        )
        client.invoke = AsyncMock(return_value=response)

        me = await client.get_me()

    assert me.id == 111
    assert isinstance(me.photo, types.ChatPhoto)


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


@pytest.mark.asyncio
async def test_call_with_retry_flood_wait_exceeds_threshold():
    from tg_signer.compat import call_with_retry, errors

    mock_cb = AsyncMock()
    # Mock FloodWait with 600s
    fw_err = errors.FloodWait("Flood wait")
    fw_err.value = 600
    mock_cb.side_effect = fw_err

    logs = []
    with pytest.raises(errors.FloodWait):
        await call_with_retry(
            mock_cb,
            operation="test_op",
            max_retries=2,
            max_flood_wait=120,
            log=lambda lvl, msg: logs.append((lvl, msg)),
        )

    assert mock_cb.await_count == 1
    assert any("长时 FloodWait" in msg for lvl, msg in logs)

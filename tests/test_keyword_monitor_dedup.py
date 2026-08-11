"""
关键词监听重启去重测试。

服务重启/重连后 Telegram 会补投停机期间的旧消息，
按 (账号, 会话) 已处理水位跳过，避免重复命中、推送与命中记录。
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.keyword_monitor import (
    KeywordMonitorRule,
    KeywordMonitorService,
)
from backend.services.keyword_monitor import (
    runtime as runtime_mod,
)


class _FakeSettings:
    def __init__(self, workdir: Path):
        self._workdir = workdir

    def resolve_workdir(self) -> Path:
        return self._workdir


class _FakeConfig:
    def get_global_settings(self) -> dict:
        return {}


def _make_message(*, text: str, id: int, chat_id: int):
    message = MagicMock()
    message.text = text
    message.caption = None
    message.id = id
    message.chat.id = chat_id
    message.chat.title = "Group"
    message.chat.username = None
    message.chat.type = "supergroup"
    message.from_user = None
    message.link = None
    return message


def _make_rule(chat_id: int = 1001) -> KeywordMonitorRule:
    return KeywordMonitorRule(
        account_name="acc",
        task_name="listen_a",
        chat_id=chat_id,
        chat_name="Group",
        message_thread_id=None,
        sender_filter=None,
        action={"keywords": ["code"], "push_channel": "telegram"},
    )


def test_is_seen_message_marks_and_skips():
    service = KeywordMonitorService()
    # 首见推进水位，同 ID / 更旧 ID 跳过，更新 ID 再推进
    assert service._is_seen_message("acc", 1001, 10) is False
    assert service._is_seen_message("acc", 1001, 10) is True
    assert service._is_seen_message("acc", 1001, 9) is True
    assert service._is_seen_message("acc", 1001, 11) is False
    assert service._is_seen_message("acc", 1001, 11) is True
    # 不同账号 / 会话水位互相独立
    assert service._is_seen_message("acc", 1002, 10) is False
    assert service._is_seen_message("other", 1001, 10) is False
    # 无消息 ID 不参与去重，也不推进水位
    assert service._is_seen_message("acc", 1001, None) is False
    assert service._is_seen_message("acc", 1001, 9) is True


def test_seen_state_persist_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(runtime_mod, "settings", _FakeSettings(tmp_path))
    service = KeywordMonitorService()
    service._is_seen_message("acc", 1001, 42)
    service._maybe_persist_seen_state(force=True)

    path = tmp_path / "keyword_monitor" / "seen.json"
    assert path.exists()

    # 新实例（模拟重启）加载水位后跳过旧消息
    service2 = KeywordMonitorService()
    service2._load_seen_state()
    assert service2._is_seen_message("acc", 1001, 42) is True
    assert service2._is_seen_message("acc", 1001, 43) is False


def test_seen_state_corrupt_or_dirty_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(runtime_mod, "settings", _FakeSettings(tmp_path))
    path = tmp_path / "keyword_monitor" / "seen.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    # 损坏 JSON 不抛异常，从空水位开始
    path.write_text("{not-json", encoding="utf-8")
    service = KeywordMonitorService()
    service._load_seen_state()
    assert service._is_seen_message("acc", 1001, 5) is False

    # 非 int / 非正数条目被过滤，合法条目生效
    path.write_text(
        json.dumps({"acc:1001": "oops", "acc:1002": 7, "acc:1003": -1}),
        encoding="utf-8",
    )
    service._load_seen_state()
    assert service._is_seen_message("acc", 1002, 7) is True
    assert service._is_seen_message("acc", 1001, 999) is False
    assert service._is_seen_message("acc", 1003, 100) is False


@pytest.mark.asyncio
async def test_stop_persists_seen_state(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(runtime_mod, "settings", _FakeSettings(tmp_path))
    service = KeywordMonitorService()
    service._is_seen_message("acc", 1001, 42)
    await service.stop()
    path = tmp_path / "keyword_monitor" / "seen.json"
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == {"acc:1001": 42}


@pytest.mark.asyncio
async def test_on_message_skips_duplicate_after_restart(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(runtime_mod, "settings", _FakeSettings(tmp_path))
    monkeypatch.setattr(
        "backend.services.config.get_config_service", lambda: _FakeConfig()
    )
    hit_recorder = MagicMock()
    monkeypatch.setattr(
        "backend.services.keyword_monitor.hits.record_keyword_hit", hit_recorder
    )
    push = AsyncMock()
    monkeypatch.setattr(runtime_mod, "send_keyword_push", push)

    service = KeywordMonitorService()
    service._rules = [_make_rule()]
    client = MagicMock()

    message = _make_message(text="hello code", id=101, chat_id=1001)
    await service._on_message("acc", client, message)
    assert push.call_count == 1
    assert hit_recorder.call_count == 1

    # 模拟重启：水位已落盘，新实例加载后跳过同一条补投消息
    service2 = KeywordMonitorService()
    service2._rules = service._rules
    service2._load_seen_state()
    await service2._on_message("acc", client, message)
    assert push.call_count == 1
    assert hit_recorder.call_count == 1

    # 停机期间的新消息（更高 ID）正常处理
    message2 = _make_message(text="hello code again", id=102, chat_id=1001)
    await service2._on_message("acc", client, message2)
    assert push.call_count == 2
    assert hit_recorder.call_count == 2


@pytest.mark.asyncio
async def test_on_message_skips_without_side_effects(tmp_path: Path, monkeypatch):
    """已见消息在规则判定前短路，不产生日志与命中副作用。"""
    monkeypatch.setattr(runtime_mod, "settings", _FakeSettings(tmp_path))
    monkeypatch.setattr(
        "backend.services.config.get_config_service", lambda: _FakeConfig()
    )
    hit_recorder = MagicMock()
    monkeypatch.setattr(
        "backend.services.keyword_monitor.hits.record_keyword_hit", hit_recorder
    )
    push = AsyncMock()
    monkeypatch.setattr(runtime_mod, "send_keyword_push", push)

    service = KeywordMonitorService()
    service._rules = [_make_rule()]
    client = MagicMock()

    message = _make_message(text="hello code", id=101, chat_id=1001)
    await service._on_message("acc", client, message)
    assert push.call_count == 1
    # 直接再次投递同一条消息（无重启、同实例）：水位同样拦截
    await service._on_message("acc", client, message)
    assert push.call_count == 1
    assert hit_recorder.call_count == 1
    # 无文本消息不推进水位，不产生副作用
    no_text = _make_message(text="", id=200, chat_id=1001)
    await service._on_message("acc", client, no_text)
    assert push.call_count == 1

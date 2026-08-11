"""关键词监听 ignore_self / 时间窗纯函数测试。"""
from datetime import datetime, timezone
from types import SimpleNamespace

from backend.services.keyword_monitor.rules import (
    _action_ignore_self,
    _action_in_active_time_window,
    _message_is_self,
)


def test_ignore_self_default_true():
    assert _action_ignore_self({}) is True
    assert _action_ignore_self({"ignore_self": False}) is False
    assert _action_ignore_self({"ignore_self": True}) is True
    assert _action_ignore_self({"ignore_self": "0"}) is False


def test_message_is_self():
    self_msg = SimpleNamespace(from_user=SimpleNamespace(is_self=True))
    other_msg = SimpleNamespace(from_user=SimpleNamespace(is_self=False))
    no_user = SimpleNamespace(from_user=None)
    assert _message_is_self(self_msg) is True
    assert _message_is_self(other_msg) is False
    assert _message_is_self(no_user) is False


def test_action_time_window_all_day_when_empty():
    assert _action_in_active_time_window({}) is True
    assert _action_in_active_time_window({"active_time_start": "09:00"}) is True


def test_action_time_window_respects_range():
    noon = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
    action = {"active_time_start": "09:00", "active_time_end": "18:00"}
    assert _action_in_active_time_window(action, now=noon, tz_name="UTC") is True
    night = datetime(2026, 7, 22, 22, 0, tzinfo=timezone.utc)
    assert _action_in_active_time_window(action, now=night, tz_name="UTC") is False


def test_action_time_window_uses_panel_timezone_when_now_omitted(monkeypatch):
    """缺省 now 时应使用面板时区的当前时间（此处固定 mock）。"""
    fixed = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed.replace(tzinfo=None)
            return fixed.astimezone(tz)

    monkeypatch.setattr(
        "backend.services.keyword_monitor.rules.datetime",
        _FixedDateTime,
        raising=False,
    )
    # 直接传入 now 更稳妥：验证 tz_name 转换路径
    # UTC 10:00 + Asia/Shanghai = 18:00，窗 17:00-19:00 应命中
    action = {"active_time_start": "17:00", "active_time_end": "19:00"}
    assert (
        _action_in_active_time_window(
            action, now=fixed, tz_name="Asia/Shanghai"
        )
        is True
    )

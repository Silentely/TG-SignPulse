"""时间窗匹配与规范化测试。"""
from datetime import datetime, timezone

from backend.utils.time_window import (
    is_within_time_window,
    normalize_time_window,
    parse_hhmm,
    resolve_tz,
)


def test_parse_hhmm_valid():
    assert parse_hhmm("9:05").hour == 9
    assert parse_hhmm("09:05").minute == 5
    assert parse_hhmm("23:59").hour == 23
    # HTML <input type="time"> 可能带秒
    assert parse_hhmm("09:05:00").minute == 5
    assert parse_hhmm("09:05:30").second == 30


def test_parse_hhmm_invalid():
    assert parse_hhmm("") is None
    assert parse_hhmm("25:00") is None
    assert parse_hhmm("12:60") is None
    assert parse_hhmm("abc") is None


def test_normalize_time_window_requires_both():
    assert normalize_time_window("09:00", "18:00") == ("09:00", "18:00")
    assert normalize_time_window("9:00", "18:00") == ("09:00", "18:00")
    assert normalize_time_window("09:00:00", "18:00:00") == ("09:00", "18:00")
    assert normalize_time_window("09:00", "") == (None, None)
    assert normalize_time_window(None, "18:00") == (None, None)


def test_within_normal_window():
    now = datetime(2026, 7, 22, 10, 30, tzinfo=timezone.utc)
    assert is_within_time_window(now, "09:00", "18:00", tz_name="UTC") is True
    assert is_within_time_window(now, "11:00", "18:00", tz_name="UTC") is False


def test_within_overnight_window():
    night = datetime(2026, 7, 22, 23, 30, tzinfo=timezone.utc)
    early = datetime(2026, 7, 22, 1, 15, tzinfo=timezone.utc)
    midday = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
    assert is_within_time_window(night, "23:00", "02:00", tz_name="UTC") is True
    assert is_within_time_window(early, "23:00", "02:00", tz_name="UTC") is True
    assert is_within_time_window(midday, "23:00", "02:00", tz_name="UTC") is False


def test_empty_window_means_all_day():
    now = datetime(2026, 7, 22, 3, 0, tzinfo=timezone.utc)
    assert is_within_time_window(now, None, None) is True
    assert is_within_time_window(now, "", "") is True


def test_timezone_conversion_affects_window():
    # UTC 15:00 = Asia/Shanghai 23:00
    utc_moment = datetime(2026, 7, 22, 15, 0, tzinfo=timezone.utc)
    # 在上海时区应落在 22:00-02:00 跨夜窗
    assert (
        is_within_time_window(
            utc_moment, "22:00", "02:00", tz_name="Asia/Shanghai"
        )
        is True
    )
    # 按 UTC 钟点 15:00 不在该窗
    assert (
        is_within_time_window(utc_moment, "22:00", "02:00", tz_name="UTC") is False
    )


def test_resolve_tz_fallback():
    assert resolve_tz("Not/AZone") is not None
    assert resolve_tz("") is not None

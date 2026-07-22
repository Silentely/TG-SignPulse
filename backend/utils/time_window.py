"""时间窗匹配工具（支持跨午夜 HH:MM，可按任务时区判断）。"""
from __future__ import annotations

import re
from datetime import datetime, time, timezone
from typing import Any, Optional, Tuple
from zoneinfo import ZoneInfo

# 兼容 HTML time 输入的 HH:MM:SS，以及 H:MM
_HHMM_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")


def parse_hhmm(value: Any) -> Optional[time]:
    """解析 HH:MM / H:MM / HH:MM:SS；非法返回 None。"""
    text = str(value or "").strip()
    if not text:
        return None
    match = _HHMM_RE.fullmatch(text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    second = int(match.group(3) or 0)
    if hour > 23 or minute > 59 or second > 59:
        return None
    return time(hour=hour, minute=minute, second=second)


def normalize_time_window(
    start: Any, end: Any
) -> Tuple[Optional[str], Optional[str]]:
    """
    规范化时间窗配置为 HH:MM。
    仅当起止都能解析时才启用；否则返回 (None, None) 表示全天。
    """
    start_t = parse_hhmm(start)
    end_t = parse_hhmm(end)
    if start_t is None or end_t is None:
        return None, None
    return (
        f"{start_t.hour:02d}:{start_t.minute:02d}",
        f"{end_t.hour:02d}:{end_t.minute:02d}",
    )


def resolve_tz(tz_name: Any = None):
    """解析时区名；失败回退 UTC。"""
    name = str(tz_name or "").strip()
    if not name:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def is_within_time_window(
    now: datetime,
    start: Any,
    end: Any,
    *,
    tz_name: Any = None,
) -> bool:
    """
    判断 now 是否落在 [start, end) 时间窗内。

    - start/end 任一无效 → True（视为全天）
    - start == end → True（全天）
    - start < end：普通区间
    - start > end：跨午夜，例如 23:00–02:00
    - tz_name 提供时，将 now 转换到该时区再取钟点
    """
    start_t = parse_hhmm(start)
    end_t = parse_hhmm(end)
    if start_t is None or end_t is None:
        return True
    if start_t.hour == end_t.hour and start_t.minute == end_t.minute:
        return True

    moment = now
    if tz_name is not None and str(tz_name).strip():
        tz = resolve_tz(tz_name)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=tz)
        else:
            moment = moment.astimezone(tz)
    elif moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    current = moment.time().replace(second=0, microsecond=0, tzinfo=None)
    start_cmp = start_t.replace(second=0, microsecond=0)
    end_cmp = end_t.replace(second=0, microsecond=0)

    if start_cmp < end_cmp:
        return start_cmp <= current < end_cmp
    # 跨午夜
    return current >= start_cmp or current < end_cmp


def is_within_time_window_now(
    start: Any,
    end: Any,
    *,
    tz_name: Any = None,
) -> bool:
    """按指定时区的当前时间判断是否在窗内。"""
    tz = resolve_tz(tz_name)
    return is_within_time_window(datetime.now(tz), start, end, tz_name=tz_name)

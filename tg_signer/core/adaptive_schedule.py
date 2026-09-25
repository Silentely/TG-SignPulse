"""
Adaptive schedule cooldown duration parser.

Extracts cooldown durations from Telegram bot replies in Chinese and English,
supporting composite time formats and custom regex patterns.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import List, Optional

# Canonical unit order and weighting
_UNIT_WEIGHT = {
    "days": 4,
    "hours": 3,
    "minutes": 2,
    "seconds": 1,
}

# Unit regex patterns
_D_RE = r"(?:天|days?|d(?![a-zA-Z]))"
_H_RE = r"(?:小时|时(?!间|候|刻|尚|态|代|局)|hours?|hrs?|h(?![a-zA-Z]))"
_M_RE = r"(?:分钟|(?<![积金得获加总])分(?!钟|数|值|享|析|类|配|别|寸|辩|辨|界)|minutes?|mins?|m(?![a-zA-Z]))"
_S_RE = r"(?:秒钟|秒(?!表|杀|懂|选|回|批)|seconds?|secs?|s(?![a-zA-Z]))"

# Negative lookbehind to reject non-cooldown contexts (streak days, ordinal days, scores)
_TOKEN_PATTERN = re.compile(
    r"(?<!第)(?<!第\s)"
    r"(?<!连续)(?<!连续\s)"
    r"(?<!连续签到)(?<!连续签到\s)"
    r"(?<!已连续)(?<!已连续\s)"
    r"(?<!获得)(?<!获得\s)"
    r"(?<!得分)(?<!得分\s)"
    r"(?<!积分)(?<!积分\s)"
    r"(?<!今日积分)(?<!今日积分\s)"
    r"(?<!剩余积分)(?<!剩余积分\s)"
    r"(?<!金币)(?<!金币\s)"
    r"(?<!经验)(?<!经验\s)"
    r"(?<!点数)(?<!点数\s)"
    r"(?<!奖励)(?<!奖励\s)"
    r"(?<!加)(?<!加\s)"
    r"(?<!\+)(?<!\+\s)"
    r"(?<!\d)"
    r"(?P<val>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>"
    rf"(?P<days>{_D_RE})|"
    rf"(?P<hours>{_H_RE})|"
    rf"(?P<minutes>{_M_RE})|"
    rf"(?P<seconds>{_S_RE})"
    r")",
    re.IGNORECASE,
)

# Connectors between components in a single composite duration (e.g. "2h 30m", "1 day and 2 hours")
_CONNECTOR_PATTERN = re.compile(r"^[\s,，及和又零and]*$", re.IGNORECASE)

# 数值区间（"0-3h"、"10-20 分钟"、"2~4小时"、"1个半小时-2小时"）：区间只说明可能范围，
# 把后半段当成确定冷却时长会把上界误判为真实等待时间（如 "0-3h" → 3 小时），
# 因此整段屏蔽，交由调用方走自身兜底策略。
# 端点后允许带单位：自然语言归一后 "1个半小时" 变成 "1.5小时"，单位夹在数字与分隔符之间，
# 不放开单位会漏掉这类区间（"1.5小时-2小时" 会被当成 1.5 小时）。
_UNIT_TAIL = rf"(?:{_D_RE}|{_H_RE}|{_M_RE}|{_S_RE})?"
_NUMERIC_RANGE_PATTERN = re.compile(
    rf"\d+(?:\.\d+)?\s*(?:个)?{_UNIT_TAIL}"
    rf"\s*[-–—~至]\s*\d+(?:\.\d+)?\s*(?:个)?{_UNIT_TAIL}"
)


def _preprocess_duration_text(text: str) -> str:
    """Preprocess natural language duration phrases (e.g. 半小时, 1小时零5分, 1个半小时)."""
    text = re.sub(r"(?:一|1)\s*个半\s*小时", "1.5小时", text)
    text = re.sub(r"(?<!\d)(\d+)\s*小时半", r"\1.5小时", text)
    text = re.sub(r"(?<!\d)半\s*天", "0.5天", text)
    text = re.sub(r"(?<!\d)半\s*小时", "0.5小时", text)
    text = re.sub(r"(?<!\d)半\s*分钟", "0.5分钟", text)
    # "半个(小时)" 与 "半小时" 等价；先补单位再屏蔽区间，"半个-1小时" 才能被识别为区间
    text = re.sub(r"(?<!\d)半\s*个\s*小时", "0.5小时", text)
    text = re.sub(r"(?<!\d)半\s*个(?=[\s\-–—~至,，。!！?？]|$)", "0.5小时", text)
    text = re.sub(r"(?<!\d)一个\s*小时", "1小时", text)
    text = re.sub(r"(?<!\d)一\s*天", "1天", text)
    # 区间屏蔽须在自然语言归一之后：避免 "半个-1小时" 之类的串被区间规则误吞
    return _NUMERIC_RANGE_PATTERN.sub(" ", text)


class _TimeToken:
    def __init__(self, unit: str, val: float, start: int, end: int):
        self.unit = unit
        self.val = val
        self.start = start
        self.end = end


def _extract_tokens(text: str) -> List[_TimeToken]:
    tokens: List[_TimeToken] = []
    for m in _TOKEN_PATTERN.finditer(text):
        val_str = m.group("val")
        try:
            val = float(val_str)
        except ValueError:
            continue

        unit_type = None
        if m.group("days"):
            unit_type = "days"
        elif m.group("hours"):
            unit_type = "hours"
        elif m.group("minutes"):
            unit_type = "minutes"
        elif m.group("seconds"):
            unit_type = "seconds"

        if unit_type:
            tokens.append(_TimeToken(unit=unit_type, val=val, start=m.start(), end=m.end()))
    return tokens


def _cluster_tokens(tokens: List[_TimeToken], text: str) -> List[dict]:
    """Group tokens into composite duration clusters."""
    if not tokens:
        return []

    clusters: List[dict] = []
    current_cluster: dict = {}
    last_token: Optional[_TimeToken] = None

    for tok in tokens:
        if last_token is None:
            current_cluster = {tok.unit: tok.val}
            last_token = tok
            continue

        # Check if tok can be appended to current cluster:
        # 1. Strictly smaller unit weight (e.g. hours -> minutes)
        # 2. Text between last_token.end and tok.start is just connectors/whitespace
        # 3. Current cluster does not already have this unit
        between = text[last_token.end : tok.start]
        can_merge = (
            _UNIT_WEIGHT[tok.unit] < _UNIT_WEIGHT[last_token.unit]
            and tok.unit not in current_cluster
            and bool(_CONNECTOR_PATTERN.match(between))
        )

        if can_merge:
            current_cluster[tok.unit] = tok.val
            last_token = tok
        else:
            clusters.append(current_cluster)
            current_cluster = {tok.unit: tok.val}
            last_token = tok

    if current_cluster:
        clusters.append(current_cluster)

    return clusters


def _dict_to_timedelta(d: dict) -> Optional[timedelta]:
    td = timedelta(
        days=d.get("days", 0),
        hours=d.get("hours", 0),
        minutes=d.get("minutes", 0),
        seconds=d.get("seconds", 0),
    )
    # Reasonable cooldown range: 10 seconds to 72 hours
    if 10.0 <= td.total_seconds() <= 259200.0:
        return td
    return None


def _extract_first_duration(text: Optional[str]) -> Optional[timedelta]:
    if not text or not isinstance(text, str):
        return None
    text = _preprocess_duration_text(text)
    tokens = _extract_tokens(text)
    clusters = _cluster_tokens(tokens, text)
    if not clusters:
        return None
    return _dict_to_timedelta(clusters[0])


def parse_cooldown_timedelta(
    text: str, custom_patterns: Optional[List[str]] = None
) -> Optional[timedelta]:
    """
    Parse cooldown duration from message text into a timedelta object.

    Supports Chinese and English formats, composite durations (e.g. '3小时15分钟',
    '2h 30m'), and custom regex patterns with priority matching.
    """
    if not text or not isinstance(text, str):
        return None

    # 1. Check custom patterns first if provided
    if custom_patterns:
        for pattern in custom_patterns:
            pattern = str(pattern or "").strip()
            # Guard against pattern length ReDoS attacks
            if not pattern or len(pattern) > 200:
                continue
            try:
                m = re.search(pattern, text, re.IGNORECASE)
            except re.error:
                continue
            if m:
                # Try captured group first if present
                if m.lastindex and m.lastindex >= 1:
                    captured = m.group(1)
                    if captured and isinstance(captured, str):
                        res = _extract_first_duration(captured)
                        if res:
                            return res
                        # If captured is a bare number, default to seconds
                        try:
                            num = float(captured.strip())
                            if 10.0 <= num <= 259200.0:
                                return timedelta(seconds=num)
                        except ValueError:
                            pass

                # Try the full match
                res = _extract_first_duration(m.group(0))
                if res:
                    return res

    # 2. Default extraction: find first duration cluster in text
    return _extract_first_duration(text)

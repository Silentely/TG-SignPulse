"""
签到任务文本处理

纯函数：乱码修复等，供历史/日志拼装复用。
"""
from __future__ import annotations

_MOJIBAKE_TOKENS = (
    "绛",
    "璐",
    "浠",
    "鐧",
    "鏃",
    "閰",
    "杩",
    "鍙",
    "鍦",
    "娑",
    "妫",
    "瀛",
    "�",
)


def repair_mojibake(text: str) -> str:
    """尝试修复常见 UTF-8 被按 GBK 误读的乱码。"""
    if not isinstance(text, str) or not text:
        return "" if text is None else str(text)

    suspicious_count = sum(text.count(token) for token in _MOJIBAKE_TOKENS)
    if suspicious_count < 2 and "�" not in text:
        return text

    try:
        candidate = text.encode("gbk", errors="strict").decode("utf-8", errors="strict")
    except Exception:
        return text

    candidate_suspicious = sum(candidate.count(token) for token in _MOJIBAKE_TOKENS)
    if candidate_suspicious < suspicious_count:
        return candidate
    return text

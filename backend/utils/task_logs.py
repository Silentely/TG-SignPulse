from __future__ import annotations

import re
from typing import Iterable

_TIMESTAMP_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}.*? -\s*")
# 标签分隔符：全角与半角冒号都可能是日志前缀的分隔符
_LABEL_SEPARATOR = re.compile(r"[：:]")


def normalize_log_line(value: object) -> str:
    text = str(value or "").replace("\x00", "").strip()
    if not text:
        return ""
    return _TIMESTAMP_PREFIX.sub("", text).strip()


def _value_after_label(line: str, label: str = "") -> str:
    """取日志行中标签之后的内容；无分隔符时返回整行（或标签后的剩余文本）。

    必须按「标签后第一个出现的冒号」切分，不能先判断行内有无全角冒号再 split：
    消息正文里的全角冒号会被误当成标签分隔符，从而截断正文前缀
    （如 "任务对象最后一条消息: 提示：明天再来" 只应剥掉 "任务对象最后一条消息: "）。
    label 非空时先定位标签本身，避免行首其它冒号抢先切分。
    """
    if label:
        idx = line.find(label)
        if idx == -1:
            return line.strip()
        remainder = line[idx + len(label) :]
        parts = _LABEL_SEPARATOR.split(remainder, maxsplit=1)
        return (parts[1] if len(parts) == 2 else remainder).strip()

    parts = _LABEL_SEPARATOR.split(line, maxsplit=1)
    if len(parts) == 2:
        return parts[1].strip()
    return line.strip()


def extract_last_target_message(flow_logs: Iterable[object] | None) -> str:
    if not flow_logs:
        return ""

    lines: list[str] = []
    for raw in flow_logs:
        normalized = normalize_log_line(raw)
        if not normalized:
            continue
        for line in normalized.splitlines():
            clean_line = line.strip()
            if clean_line:
                lines.append(clean_line)

    if not lines:
        return ""

    for line in reversed(lines):
        if line.startswith("任务对象最后一条消息:") or line.startswith("任务对象最后一条消息："):
            value = _value_after_label(line)
            if value:
                return value

    for line in reversed(lines):
        if (
            line.startswith("收到回复")
            or line.startswith("Bot回复")
            or line.startswith("机器人回复")
        ):
            value = _value_after_label(line)
            if value:
                return value

    for line in reversed(lines):
        if line.startswith("收到图片"):
            value = _value_after_label(line)
            if value:
                return value

    for line in reversed(lines):
        lower = line.lower()
        idx = lower.find("text:")
        if idx != -1:
            value = line[idx + len("text:"):].strip()
            if value:
                return value
        idx_zh = line.find("text：")
        if idx_zh != -1:
            value = line[idx_zh + len("text："):].strip()
            if value:
                return value

    for line in reversed(lines):
        if "图片:" in line or "图片：" in line:
            value = _value_after_label(line, label="图片")
            if value:
                return f"[图片] {value}"

    return ""

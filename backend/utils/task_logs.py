from __future__ import annotations

import re
from typing import Iterable

_TIMESTAMP_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}.*? -\s*")


def normalize_log_line(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return _TIMESTAMP_PREFIX.sub("", text).strip()


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
        if line.startswith("任务对象最后一条消息:"):
            value = line.split(":", 1)[-1].strip()
            if value:
                return value

    for line in reversed(lines):
        if line.startswith("收到回复"):
            value = line.split("：", 1)[-1].strip() if "：" in line else line.split(":", 1)[-1].strip()
            if value:
                return value

    for line in reversed(lines):
        if line.startswith("收到图片"):
            value = line.split("：", 1)[-1].strip() if "：" in line else line.split(":", 1)[-1].strip()
            if value:
                return value

    for line in reversed(lines):
        lower = line.lower()
        if "text:" in lower:
            _, value = line.split(":", 1)
            value = value.strip()
            if value:
                return value

    for line in reversed(lines):
        if "图片:" in line:
            value = line.split("图片:", 1)[-1].strip()
            if value:
                return f"[图片] {value}"

    return ""

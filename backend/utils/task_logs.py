from __future__ import annotations

import re
from typing import Iterable

_TIMESTAMP_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}.*? -\s*")
_LOG_RUNNER_PREFIX = re.compile(r"^账户「.*?」\s*-\s*任务「.*?」\s*[:：]\s*")
# 标签分隔符：全角与半角冒号都可能是日志前缀的分隔符
_LABEL_SEPARATOR = re.compile(r"[：:]")
_SEND_ACTIONS = (
    "已发送",
    "发送文本",
    "发送消息",
    "发送命令",
    "Action-",
    "点击按钮",
    "执行步骤",
)

_REPLY_BOUNDARY_PREFIXES = (
    "步骤 [",
    "步骤 step_",
    "步骤 ",
    "第 ",
    "命中成功规则",
    "命中失败规则",
    "机器人已确认",
    "PulseFlow",
    "任务执行完成",
    "本步骤耗时",
    "收到来自「",
    "收到机器人回复",
    "收到回复",
    "Bot回复",
    "机器人回复",
    "任务对象最后一条消息",
    "AI 请求",
    "AI 响应",
    "AI 正在分析",
    "点击完成",
    "开始执行任务",
    "消息更新监听",
    "等待机器人回复确认",
    "等待机器人确认",
    "已恢复 peer",
    "peer 预热",
    "确认任务对象",
    "当前任务使用执行引擎",
)


def normalize_log_line(value: object) -> str:
    text = str(value or "").replace("\x00", "").strip()
    if not text:
        return ""
    return _TIMESTAMP_PREFIX.sub("", text).strip()


def _clean_line_prefix(line: str) -> str:
    return _LOG_RUNNER_PREFIX.sub("", line).strip()


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


def _collect_multiline_reply(
    lines: list[str], start_idx: int, first_line_val: str
) -> str:
    """从起始行开始向下收集多行回复内容，遇到系统边界行或发送操作时截断。"""
    parts = [first_line_val] if first_line_val else []
    for j in range(start_idx + 1, len(lines)):
        nxt = _clean_line_prefix(lines[j])
        if any(nxt.startswith(p) for p in _REPLY_BOUNDARY_PREFIXES):
            break
        if any(p in nxt for p in _SEND_ACTIONS):
            break
        if nxt:
            parts.append(nxt)
    return "\n".join(parts).strip()


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

    # Pass 1: 显式标记的「任务对象最后一条消息」
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        clean = _clean_line_prefix(line)
        if any(p in clean for p in _SEND_ACTIONS):
            continue
        if clean.startswith("任务对象最后一条消息:") or clean.startswith(
            "任务对象最后一条消息："
        ):
            val = _value_after_label(clean)
            res = _collect_multiline_reply(lines, i, val)
            if res:
                return res

    # Pass 2: 收到机器人回复 / 收到回复（支持多行回复与冒号后换行）
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        clean = _clean_line_prefix(line)
        if any(p in clean for p in _SEND_ACTIONS):
            continue
        if (
            clean.startswith("收到回复")
            or clean.startswith("Bot回复")
            or clean.startswith("机器人回复")
            or clean.startswith("收到机器人回复")
        ):
            val = _value_after_label(clean)
            res = _collect_multiline_reply(lines, i, val)
            if res:
                return res

    # Pass 3: 收到图片
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        clean = _clean_line_prefix(line)
        if any(p in clean for p in _SEND_ACTIONS):
            continue
        if clean.startswith("收到图片"):
            val = _value_after_label(clean)
            res = _collect_multiline_reply(lines, i, val)
            if res:
                return res

    # Pass 4: text:
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        clean = _clean_line_prefix(line)
        if any(p in clean for p in _SEND_ACTIONS):
            continue
        lower = clean.lower()
        idx = lower.find("text:")
        if idx != -1:
            val = clean[idx + len("text:") :].strip()
            res = _collect_multiline_reply(lines, i, val)
            if res:
                return res
        idx_zh = clean.find("text：")
        if idx_zh != -1:
            val = clean[idx_zh + len("text：") :].strip()
            res = _collect_multiline_reply(lines, i, val)
            if res:
                return res

    # Pass 5: 图片:
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        clean = _clean_line_prefix(line)
        if any(p in clean for p in _SEND_ACTIONS):
            continue
        if "图片:" in clean or "图片：" in clean:
            val = _value_after_label(clean, label="图片")
            if val:
                return f"[图片] {val}"

    return ""


def resolve_effective_last_target(
    stored_target: str | None,
    extracted_target: str | None,
    *,
    message: str = "",
    success: bool = False,
) -> str:
    """综合已存储的 last_target 与从 flow_logs 提取的回复，解析最准确的目标返回内容。

    - 若某一方为空，取另一方；
    - 若两者相同，直接返回；
    - 若任务成功且两者不一致，当 stored 疑似中间交互验证码（如包含「按钮:」）
      或 extracted 与成功执行摘要 message 吻合时，优先采用 extracted 纠正旧历史；
    - 其余情况以 stored 为准。
    """
    stored = str(stored_target or "").strip()
    extracted = str(extracted_target or "").strip()
    if not stored:
        return extracted
    if not extracted:
        return stored
    if stored == extracted:
        return stored

    if success:
        clean_msg = " ".join(message.split())
        clean_ext = " ".join(extracted.split())
        if clean_msg and (clean_msg in clean_ext or clean_ext in clean_msg):
            return extracted
        if "按钮:" in stored or "按钮：" in stored:
            return extracted

    return stored

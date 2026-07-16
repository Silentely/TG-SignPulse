"""
签到目标消息摘要

从聊天消息对象提取可读摘要，供 last_target 回填复用。
"""
from __future__ import annotations

from typing import Any, Dict, List


def message_matches_thread(message: Any, chat_config: Dict[str, Any]) -> bool:
    if message is None:
        return False
    raw_thread_id = chat_config.get("message_thread_id")
    if raw_thread_id in (None, "", 0):
        return True
    try:
        thread_id = int(raw_thread_id)
    except (TypeError, ValueError):
        return True
    message_thread_id = getattr(message, "message_thread_id", None) or getattr(
        message,
        "reply_to_top_message_id",
        None,
    )
    return message_thread_id == thread_id


def format_target_message_summary(message: Any) -> str:
    if message is None:
        return ""

    text = str(
        getattr(message, "text", None) or getattr(message, "caption", None) or ""
    ).strip()
    if text:
        return text

    reply_markup = getattr(message, "reply_markup", None)
    button_rows: List[str] = []
    if reply_markup is not None:
        inline_keyboard = getattr(reply_markup, "inline_keyboard", None)
        reply_keyboard = getattr(reply_markup, "keyboard", None)
        rows = inline_keyboard or reply_keyboard or []
        for row in rows:
            row_texts: List[str] = []
            for button in row or []:
                button_text = str(
                    getattr(button, "text", None) or button or ""
                ).strip()
                if button_text:
                    row_texts.append(button_text)
            if row_texts:
                button_rows.append(" | ".join(row_texts))
        if button_rows:
            return " / ".join(button_rows)

    media_markers = (
        ("photo", "[图片]"),
        ("sticker", "[贴纸]"),
        ("animation", "[动图]"),
        ("video", "[视频]"),
        ("document", "[文件]"),
        ("audio", "[音频]"),
        ("voice", "[语音]"),
        ("video_note", "[视频消息]"),
    )
    for attr_name, label in media_markers:
        if getattr(message, attr_name, None) is not None:
            return label

    poll = getattr(message, "poll", None)
    if poll is not None:
        question = str(getattr(poll, "question", "") or "").strip()
        return f"[投票] {question}".strip()

    return ""

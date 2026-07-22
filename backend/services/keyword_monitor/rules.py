"""关键词监控规则模型与纯函数工具。"""
from __future__ import annotations

import logging
import os
import random
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from backend.core.config import get_settings
from tg_signer.compat import (
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
)


# 自定义异常类：AI 调用不可恢复错误
class TerminalAIActionError(Exception):
    """AI 调用发生不可恢复错误，后续动作应立即失败而非重试"""
    pass


# 模块级别变量
logger = logging.getLogger("backend.keyword_monitor")
settings = get_settings()

DEFAULT_CONTINUE_TIMEOUT = 25
DEFAULT_HISTORY_LIMIT = 10
DEFAULT_COMMAND_PREFIX = "/start"
# 同一账号对同一 Bot 连续发送命令的最小间隔（秒），等待而非跳过
DEFAULT_BOT_CMD_INTERVAL = 2.0
# 单次 action 最多处理的注册码/链接数量（调高易触发 Telegram 风控/封禁）
DEFAULT_BOT_CMD_MAX_BATCH = 5
_BOT_CMD_MAX_BATCH_RISK_HINT = (
    "调高 max_batch 可能导致 Telegram 风控、限流甚至账号封禁，请谨慎设置"
)

# 解析消息中的 Telegram 深链：t.me/bot?start=payload
_TG_START_LINK_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me|telegram\.dog)/"
    r"([A-Za-z][A-Za-z0-9_]{3,31})"
    r"\?start=([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)


def _is_callback_data_invalid(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "data_invalid" in text or "encrypted data is invalid" in text


@dataclass(frozen=True)
class KeywordMonitorRule:
    account_name: str
    task_name: str
    chat_id: int
    chat_name: str
    message_thread_id: Optional[int]
    sender_filter: Optional[List[str]]
    action: Dict[str, Any]


def _parse_keywords(value: Any, *, split_commas: bool = True) -> List[str]:
    if isinstance(value, list):
        raw_items = value
    elif split_commas:
        raw_items = re.split(r"[\n,]+", str(value or ""))
    else:
        raw_items = str(value or "").splitlines()
    return [str(item).strip() for item in raw_items if str(item).strip()]


def _keyword_split_commas(action: Dict[str, Any]) -> bool:
    return (action.get("match_mode") or "contains").strip() != "regex"


def _regex_keyword_value(match: re.Match[str]) -> str:
    for group in match.groups():
        if group is not None:
            value = str(group).strip()
            if value:
                return value
    return match.group(0).strip()


def _normalize_bot_username(value: Any) -> str:
    """规范化 Bot 用户名：去空白与前导 @。"""
    return str(value or "").strip().lstrip("@").strip()


def _as_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _as_non_negative_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number < 0:
        return default
    return number


def _as_positive_int(value: Any, default: int, minimum: int = 1) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < minimum:
        return default
    return number


def _extract_tg_start_links(text: str) -> List[tuple[str, str]]:
    """从消息文本提取 (bot_username, start_param)，保序去重。"""
    if not text:
        return []
    results: List[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in _TG_START_LINK_RE.finditer(text):
        bot = match.group(1)
        param = match.group(2)
        key = (bot.lower(), param)
        if key in seen:
            continue
        seen.add(key)
        results.append((bot, param))
    return results


def _match_all_keyword_values(action: Dict[str, Any], text: str) -> List[str]:
    """返回消息中全部命中值（正则 finditer；contains/exact 至多一个）。"""
    keywords = _parse_keywords(
        action.get("keywords"),
        split_commas=_keyword_split_commas(action),
    )
    if not keywords or not text:
        return []

    mode = (action.get("match_mode") or "contains").strip()
    ignore_case = bool(action.get("ignore_case", True))
    haystack = text.lower() if ignore_case else text
    results: List[str] = []
    seen: set[str] = set()

    for keyword in keywords:
        needle = keyword.lower() if ignore_case else keyword
        if mode == "exact":
            if haystack == needle and keyword not in seen:
                seen.add(keyword)
                results.append(keyword)
            continue
        if mode == "regex":
            flags = re.IGNORECASE if ignore_case else 0
            try:
                for match in re.finditer(keyword, text, flags=flags):
                    value = _regex_keyword_value(match)
                    if value and value not in seen:
                        seen.add(value)
                        results.append(value)
            except re.error as exc:
                logger.warning("Invalid keyword monitor regex %r: %s", keyword, exc)
            continue
        if needle in haystack and keyword not in seen:
            seen.add(keyword)
            results.append(keyword)
    return results


def _is_immediate_continue_action(action: Optional[Dict[str, Any]]) -> bool:
    if not action:
        return False
    try:
        return int(action.get("action")) in {1, 2}
    except (TypeError, ValueError):
        return False


def _message_text(message: Message) -> str:
    return (message.text or message.caption or "").strip()


def _message_url(message: Message) -> str:
    link = getattr(message, "link", None)
    if isinstance(link, str) and link:
        return link

    username = getattr(message.chat, "username", None)
    if username:
        return f"https://t.me/{username}/{message.id}"

    chat_id = getattr(message.chat, "id", None)
    if isinstance(chat_id, int):
        chat_id_text = str(chat_id)
        if chat_id_text.startswith("-100"):
            return f"https://t.me/c/{chat_id_text[4:]}/{message.id}"
    return ""


def _as_int_or_none(value: Any) -> Optional[int]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_forward_chat_id(value: Any) -> Optional[Union[int, str]]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("@"):
        return text
    try:
        return int(text)
    except ValueError:
        return text


_TEMPLATE_PATTERN = re.compile(r"(?:\$\{|\{)([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _read_positive_int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(int(raw), minimum)
    except (TypeError, ValueError):
        return default


def _read_positive_float_env(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(float(raw), minimum)
    except (TypeError, ValueError):
        return default


def _resolve_action_delay(action: Dict[str, Any], fallback_delay: float = 0.0) -> float:
    raw_delay = action.get("delay")
    if raw_delay is None:
        return max(float(fallback_delay or 0.0), 0.0)

    delay_text = str(raw_delay).strip()
    if not delay_text:
        return max(float(fallback_delay or 0.0), 0.0)

    try:
        if "-" in delay_text:
            start_text, end_text = delay_text.split("-", 1)
            start = float(start_text)
            end = float(end_text)
            if end < start:
                start, end = end, start
            return max(random.uniform(start, end), 0.0)
        return max(float(delay_text), 0.0)
    except (TypeError, ValueError):
        return max(float(fallback_delay or 0.0), 0.0)


def _render_template(value: Any, variables: Dict[str, str]) -> Any:
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        return variables.get(match.group(1), "")

    return _TEMPLATE_PATTERN.sub(replace, value)


def _render_action_templates(action: Dict[str, Any], variables: Dict[str, str]) -> Dict[str, Any]:
    rendered: Dict[str, Any] = {}
    for key, value in action.items():
        if isinstance(value, str):
            rendered[key] = _render_template(value, variables)
        elif isinstance(value, list):
            rendered[key] = [
                _render_template(item, variables) if isinstance(item, str) else item
                for item in value
            ]
        else:
            rendered[key] = value
    return rendered


def _clean_text_for_match(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", str(text))
    return "".join(
        ch
        for ch in normalized.lower()
        if not unicodedata.category(ch).startswith(("P", "S", "Z", "C"))
    )


def _button_text_matches(target_text: str, button_text: str) -> bool:
    if not target_text or not button_text:
        return False
    if target_text == button_text or target_text in button_text:
        return True
    return len(button_text) >= 2 and button_text in target_text


def _message_matches_thread(message: Message, message_thread_id: Optional[int]) -> bool:
    if message_thread_id is None:
        return True
    return message_thread_id in _message_thread_candidates(message)


def _parse_sender_filter(value: Any) -> Optional[List[str]]:
    """解析发送者过滤列表。支持逗号或换行分隔的用户名列表。"""
    if not value:
        return None
    if isinstance(value, list):
        items = [str(s).strip().lower() for s in value if str(s).strip()]
    else:
        items = [
            s.strip().lower().lstrip("@")
            for s in re.split(r"[\n,]+", str(value))
            if s.strip()
        ]
    return items if items else None


def _message_matches_sender(message: Message, sender_filter: Optional[List[str]]) -> bool:
    """检查消息发送者是否在白名单中。sender_filter 为 None 表示不过滤。"""
    if sender_filter is None:
        return True
    if not message.from_user:
        return False
    username = (message.from_user.username or "").lower()
    return username in sender_filter


def _action_ignore_self(action: Dict[str, Any]) -> bool:
    """是否忽略自己发送的消息；缺省 True。"""
    return _as_bool(action.get("ignore_self"), default=True)


def _message_is_self(message: Message) -> bool:
    user = getattr(message, "from_user", None)
    if user is None:
        return False
    return bool(getattr(user, "is_self", False))


def _action_time_window(action: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """读取动作上的监听时间窗配置。"""
    from backend.utils.time_window import normalize_time_window

    return normalize_time_window(
        action.get("active_time_start"),
        action.get("active_time_end"),
    )


def _resolve_panel_timezone() -> str:
    """读取面板任务时区（与调度器一致），失败回退空串由工具层用 UTC。"""
    try:
        from backend.services.config import get_config_service

        settings = get_config_service().get_global_settings() or {}
        tz = str(settings.get("timezone") or "").strip()
        if tz:
            return tz
    except Exception:
        pass
    try:
        return str(get_settings().timezone or "").strip()
    except Exception:
        return ""


def _action_in_active_time_window(
    action: Dict[str, Any],
    *,
    now: Optional[Any] = None,
    tz_name: Optional[str] = None,
) -> bool:
    """判断当前时间是否在动作配置的监听时间窗内（按面板时区）。"""
    from datetime import datetime

    from backend.utils.time_window import is_within_time_window, resolve_tz

    start, end = _action_time_window(action)
    if not start or not end:
        return True
    panel_tz = (tz_name if tz_name is not None else _resolve_panel_timezone()) or None
    if now is not None:
        return is_within_time_window(now, start, end, tz_name=panel_tz)
    tz = resolve_tz(panel_tz)
    return is_within_time_window(datetime.now(tz), start, end, tz_name=panel_tz)


def _message_thread_candidates(message: Message) -> list[int]:
    candidates: list[int] = []
    for raw_value in (
        getattr(message, "message_thread_id", None),
        getattr(message, "direct_messages_chat_topic_id", None),
        getattr(message, "reply_to_top_message_id", None),
        getattr(message, "reply_to_message_id", None),
        getattr(getattr(message, "topic", None), "id", None),
    ):
        value = _as_int_or_none(raw_value)
        if value is None or value in candidates:
            continue
        candidates.append(value)
    return candidates


def _reply_markup_marker(reply_markup: Any) -> Any:
    if isinstance(reply_markup, InlineKeyboardMarkup):
        return (
            "inline",
            tuple(
                tuple(getattr(button, "text", "") for button in row)
                for row in reply_markup.inline_keyboard
            ),
        )
    if isinstance(reply_markup, ReplyKeyboardMarkup):
        return (
            "reply",
            tuple(
                tuple(
                    button if isinstance(button, str) else getattr(button, "text", "")
                    for button in row
                )
                for row in reply_markup.keyboard
            ),
        )
    return None


def _message_state_marker(message: Message) -> tuple[Any, ...]:
    return (
        getattr(message, "id", None),
        getattr(message, "text", None),
        getattr(message, "caption", None),
        getattr(message, "edit_date", None),
        _reply_markup_marker(getattr(message, "reply_markup", None)),
    )


def _messages_state(messages: list[Message]) -> dict[int, tuple[Any, ...]]:
    return {
        message.id: _message_state_marker(message)
        for message in messages
        if message is not None
    }


def _message_has_button_text(message: Message, text: str) -> bool:
    target_text = _clean_text_for_match(text)
    if not target_text:
        return False

    reply_markup = getattr(message, "reply_markup", None)
    if isinstance(reply_markup, InlineKeyboardMarkup):
        rows = reply_markup.inline_keyboard
    elif isinstance(reply_markup, ReplyKeyboardMarkup):
        rows = reply_markup.keyboard
    else:
        return False

    for row in rows:
        for button in row:
            button_text = button if isinstance(button, str) else getattr(button, "text", "")
            if not button_text:
                continue
            if _button_text_matches(target_text, _clean_text_for_match(button_text)):
                return True
    return False


def _collect_clickable_buttons(message: Message) -> list[tuple[str, Any, str]]:
    reply_markup = getattr(message, "reply_markup", None)
    clickable_buttons: list[tuple[str, Any, str]] = []
    if isinstance(reply_markup, InlineKeyboardMarkup):
        for row in reply_markup.inline_keyboard:
            for button in row:
                button_text = getattr(button, "text", "")
                if button_text:
                    clickable_buttons.append(("inline", button, button_text))
    elif isinstance(reply_markup, ReplyKeyboardMarkup):
        for row in reply_markup.keyboard:
            for button in row:
                button_text = button if isinstance(button, str) else getattr(button, "text", "")
                if button_text:
                    clickable_buttons.append(("reply", button, button_text))
    return clickable_buttons


def _message_supports_continue_action(message: Message, action: Dict[str, Any]) -> bool:
    try:
        action_id = int(action.get("action"))
    except (TypeError, ValueError):
        return False

    reply_markup = getattr(message, "reply_markup", None)
    if action_id == 3:
        return _message_has_button_text(message, str(action.get("text") or ""))
    if action_id == 4:
        return bool(message.photo and _collect_clickable_buttons(message))
    if action_id == 5:
        return bool(message.text or message.caption)
    if action_id == 6:
        return bool(message.photo)
    if action_id == 7:
        return bool((message.text or message.caption) and reply_markup)
    return False


def _message_has_terminal_success_text(message: Message) -> bool:
    text = "\n".join(
        item
        for item in [
            getattr(message, "text", None),
            getattr(message, "caption", None),
        ]
        if item
    ).lower()
    if not text.strip():
        return False
    failure_markers = (
        "失败",
        "错误",
        "异常",
        "未成功",
        "无法",
        "failed",
        "failure",
        "error",
        "invalid",
    )
    if any(marker in text for marker in failure_markers):
        return False
    success_markers = (
        "签到成功",
        "已签到",
        "成功",
        "完成",
        "success",
        "successful",
        "done",
        "completed",
    )
    return any(marker in text for marker in success_markers)



__all__ = [
    "TerminalAIActionError",
    "KeywordMonitorRule",
    "DEFAULT_CONTINUE_TIMEOUT",
    "DEFAULT_HISTORY_LIMIT",
    "DEFAULT_COMMAND_PREFIX",
    "DEFAULT_BOT_CMD_INTERVAL",
    "DEFAULT_BOT_CMD_MAX_BATCH",
]

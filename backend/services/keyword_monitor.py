from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from pyrogram import errors, filters
from pyrogram.handlers import MessageHandler
from pyrogram.types import InlineKeyboardMarkup, Message, ReplyKeyboardMarkup

from backend.core.config import get_settings
from backend.services.push_notifications import send_keyword_push
from backend.utils.account_locks import get_account_lock
from backend.utils.proxy import build_proxy_dict
from backend.utils.tg_session import (
    get_account_proxy,
    get_account_session_string,
    get_session_mode,
    load_session_string_file,
)

logger = logging.getLogger("backend.keyword_monitor")
settings = get_settings()

DEFAULT_CONTINUE_TIMEOUT = 25
DEFAULT_HISTORY_LIMIT = 10


@dataclass(frozen=True)
class KeywordMonitorRule:
    account_name: str
    task_name: str
    chat_id: int
    chat_name: str
    message_thread_id: Optional[int]
    action: Dict[str, Any]


def _parse_keywords(value: Any) -> List[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = re.split(r"[\n,]+", str(value or ""))
    return [str(item).strip() for item in raw_items if str(item).strip()]


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


_TEMPLATE_PATTERN = re.compile(r"\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


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
    msg_thread_id = _as_int_or_none(
        getattr(message, "message_thread_id", None)
        or getattr(message, "reply_to_top_message_id", None)
    )
    return msg_thread_id == message_thread_id


class KeywordMonitorService:
    def __init__(self) -> None:
        self._handler_refs: list[tuple[Any, Any]] = []
        self._rules: list[KeywordMonitorRule] = []
        self._active_key = ""
        self._lock = asyncio.Lock()

    def _rules_key(self, rules: list[KeywordMonitorRule]) -> str:
        return repr(
            [
                {
                    "account_name": rule.account_name,
                    "task_name": rule.task_name,
                    "chat_id": rule.chat_id,
                    "message_thread_id": rule.message_thread_id,
                    "action": rule.action,
                }
                for rule in rules
            ]
        )

    def _load_rules(self) -> list[KeywordMonitorRule]:
        from backend.services.sign_tasks import get_sign_task_service

        rules: list[KeywordMonitorRule] = []
        tasks = get_sign_task_service().list_tasks(force_refresh=True)
        for task in tasks:
            account_name = str(task.get("account_name") or "").strip()
            task_name = str(task.get("name") or "").strip()
            if not account_name or not task_name or not task.get("enabled", True):
                continue
            for chat in task.get("chats") or []:
                chat_id = chat.get("chat_id")
                try:
                    chat_id_int = int(chat_id)
                except (TypeError, ValueError):
                    continue
                for action in chat.get("actions") or []:
                    try:
                        action_id = int(action.get("action"))
                    except (TypeError, ValueError, AttributeError):
                        continue
                    if action_id != 8 or not _parse_keywords(action.get("keywords")):
                        continue
                    rules.append(
                        KeywordMonitorRule(
                            account_name=account_name,
                            task_name=task_name,
                            chat_id=chat_id_int,
                            chat_name=str(chat.get("name") or chat_id_int),
                            message_thread_id=_as_int_or_none(
                                chat.get("message_thread_id")
                            ),
                            action=dict(action),
                        )
                    )
        return rules

    def _match_keyword(self, action: Dict[str, Any], text: str) -> Optional[str]:
        keywords = _parse_keywords(action.get("keywords"))
        if not keywords or not text:
            return None

        mode = (action.get("match_mode") or "contains").strip()
        ignore_case = bool(action.get("ignore_case", True))
        haystack = text.lower() if ignore_case else text

        for keyword in keywords:
            needle = keyword.lower() if ignore_case else keyword
            if mode == "exact" and haystack == needle:
                return keyword
            if mode == "regex":
                flags = re.IGNORECASE if ignore_case else 0
                try:
                    if re.search(keyword, text, flags=flags):
                        return keyword
                except re.error as exc:
                    logger.warning("Invalid keyword monitor regex %r: %s", keyword, exc)
                continue
            if mode not in {"exact", "regex"} and needle in haystack:
                return keyword
        return None

    def _message_thread_id(self, message: Message) -> Optional[int]:
        return _as_int_or_none(
            getattr(message, "message_thread_id", None)
            or getattr(message, "reply_to_top_message_id", None)
        )

    def _build_variables(
        self,
        *,
        account_name: str,
        rule: KeywordMonitorRule,
        message: Message,
        text: str,
        matched: str,
        chat_title: str,
        sender: str,
        url: str,
    ) -> Dict[str, str]:
        return {
            "keyword": matched,
            "message": text,
            "text": text,
            "sender": sender,
            "chat_id": str(getattr(message.chat, "id", "")),
            "chat_title": chat_title,
            "message_id": str(getattr(message, "id", "")),
            "url": url,
            "task_name": rule.task_name,
            "account_name": account_name,
        }

    def _continue_actions(self, action: Dict[str, Any]) -> list[Dict[str, Any]]:
        actions = action.get("continue_actions")
        if not isinstance(actions, list):
            return []

        supported = {1, 2, 3, 4, 5, 6, 7}
        result: list[Dict[str, Any]] = []
        for item in actions:
            if not isinstance(item, dict):
                continue
            try:
                action_id = int(item.get("action"))
            except (TypeError, ValueError):
                continue
            if action_id in supported:
                result.append(dict(item))
        return result

    def _continue_target(
        self, action: Dict[str, Any], source_message: Message
    ) -> tuple[Union[int, str], Optional[int]]:
        target_chat_id = _parse_forward_chat_id(action.get("continue_chat_id"))
        if target_chat_id is None:
            target_chat_id = source_message.chat.id

        configured_thread_id = _as_int_or_none(action.get("continue_message_thread_id"))
        if configured_thread_id is not None:
            return target_chat_id, configured_thread_id

        if target_chat_id == source_message.chat.id:
            return target_chat_id, self._message_thread_id(source_message)
        return target_chat_id, None

    def _continue_interval(self, action: Dict[str, Any]) -> float:
        try:
            return max(float(action.get("continue_action_interval", 1)), 0.0)
        except (TypeError, ValueError):
            return 1.0

    def _get_ai_tools(self):
        from tg_signer.ai_tools import AITools, OpenAIConfigManager

        for workdir in (settings.resolve_session_dir(), settings.resolve_workdir()):
            cfg = OpenAIConfigManager(workdir).load_config()
            if cfg:
                return AITools(cfg)
        raise RuntimeError("OpenAI config is required for keyword monitor AI actions")

    async def _warm_chat(self, client: Any, chat_id: Union[int, str]) -> None:
        try:
            await client.get_chat(chat_id)
        except Exception as exc:
            logger.debug("Keyword monitor warm chat failed for %r: %s", chat_id, exc)

    async def _request_callback_answer(
        self,
        client: Any,
        chat_id: Union[int, str],
        message_id: int,
        callback_data: Union[str, bytes],
    ) -> bool:
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                await client.request_callback_answer(
                    chat_id, message_id, callback_data=callback_data
                )
                return True
            except errors.FloodWait as exc:
                wait_seconds = max(int(getattr(exc, "value", 1) or 1), 1)
                if attempt >= max_retries:
                    logger.warning("Keyword monitor callback FloodWait failed: %s", exc)
                    return False
                await asyncio.sleep(wait_seconds)
            except (TimeoutError, asyncio.TimeoutError, OSError, ConnectionError) as exc:
                if attempt >= max_retries:
                    logger.warning("Keyword monitor callback timed out: %s", exc)
                    return False
                await asyncio.sleep(min(2**attempt, 6))
            except Exception as exc:
                logger.warning("Keyword monitor callback failed: %s", exc)
                return False
        return False

    async def _click_inline_button(self, client: Any, message: Message, button: Any) -> bool:
        callback_data = getattr(button, "callback_data", None)
        if callback_data is not None:
            if await self._request_callback_answer(
                client, message.chat.id, message.id, callback_data
            ):
                return True

        click = getattr(message, "click", None)
        if callable(click):
            for args, kwargs in (
                ((getattr(button, "text", None),), {}),
                ((), {"text": getattr(button, "text", None)}),
            ):
                try:
                    await click(*args, **kwargs)
                    return True
                except TypeError:
                    continue
                except Exception as exc:
                    logger.warning("Keyword monitor Message.click failed: %s", exc)
                    return False
        return False

    async def _click_keyboard_by_text(
        self,
        client: Any,
        target_chat_id: Union[int, str],
        target_thread_id: Optional[int],
        action: Dict[str, Any],
        message: Message,
    ) -> bool:
        target_text = _clean_text_for_match(str(action.get("text") or ""))
        if not target_text:
            return False

        reply_markup = getattr(message, "reply_markup", None)
        if isinstance(reply_markup, InlineKeyboardMarkup):
            flat_buttons = (button for row in reply_markup.inline_keyboard for button in row)
            for button in flat_buttons:
                button_text = getattr(button, "text", None)
                if not button_text:
                    continue
                if _button_text_matches(target_text, _clean_text_for_match(button_text)):
                    return await self._click_inline_button(client, message, button)
            return False

        if isinstance(reply_markup, ReplyKeyboardMarkup):
            for row in reply_markup.keyboard:
                for button in row:
                    button_text = (
                        button if isinstance(button, str) else getattr(button, "text", "")
                    )
                    if not button_text:
                        continue
                    if _button_text_matches(target_text, _clean_text_for_match(button_text)):
                        kwargs: Dict[str, Any] = {}
                        if target_thread_id is not None:
                            kwargs["message_thread_id"] = target_thread_id
                        await client.send_message(target_chat_id, button_text, **kwargs)
                        return True
        return False

    async def _recent_messages(
        self,
        client: Any,
        chat_id: Union[int, str],
        thread_id: Optional[int],
        limit: int,
    ) -> list[Message]:
        messages: list[Message] = []
        async for message in client.get_chat_history(chat_id, limit=limit):
            if _message_matches_thread(message, thread_id):
                messages.append(message)
        return messages

    def _message_supports_action(self, message: Message, action_id: int) -> bool:
        reply_markup = getattr(message, "reply_markup", None)
        if action_id == 3:
            return bool(reply_markup)
        if action_id == 4:
            return bool(message.photo and isinstance(reply_markup, InlineKeyboardMarkup))
        if action_id == 5:
            return bool(message.text or message.caption)
        if action_id == 6:
            return bool(message.photo)
        if action_id == 7:
            return bool((message.text or message.caption) and reply_markup)
        return False

    async def _find_recent_message(
        self,
        client: Any,
        chat_id: Union[int, str],
        thread_id: Optional[int],
        action_id: int,
    ) -> Optional[Message]:
        limit = _read_positive_int_env(
            "KEYWORD_MONITOR_CONTINUE_HISTORY_LIMIT", DEFAULT_HISTORY_LIMIT, 1
        )
        messages = await self._recent_messages(client, chat_id, thread_id, limit)
        for message in messages:
            if self._message_supports_action(message, action_id):
                return message
        return None

    async def _download_photo_bytes(self, client: Any, message: Message) -> bytes:
        image_buffer = await client.download_media(message.photo.file_id, in_memory=True)
        image_buffer.seek(0)
        return image_buffer.read()

    async def _execute_ai_action(
        self,
        client: Any,
        target_chat_id: Union[int, str],
        target_thread_id: Optional[int],
        action: Dict[str, Any],
        message: Message,
    ) -> bool:
        action_id = int(action.get("action"))
        ai_tools = self._get_ai_tools()
        kwargs: Dict[str, Any] = {}
        if target_thread_id is not None:
            kwargs["message_thread_id"] = target_thread_id

        if action_id == 5:
            query = (message.text or message.caption or "").strip()
            answer = (await ai_tools.calculate_problem(query) or "").strip()
            if not answer:
                return False
            await client.send_message(target_chat_id, answer, **kwargs)
            return True

        if action_id == 6:
            image_bytes = await self._download_photo_bytes(client, message)
            answer = (await ai_tools.extract_text_by_image(image_bytes) or "").strip()
            if not answer:
                return False
            await client.send_message(target_chat_id, answer, **kwargs)
            return True

        if action_id == 7:
            query = (message.text or message.caption or "").strip()
            answer = (await ai_tools.calculate_problem(query) or "").strip()
            if not answer:
                return False
            proxy_action = {"action": 3, "text": answer}
            return await self._click_keyboard_by_text(
                client, target_chat_id, target_thread_id, proxy_action, message
            )

        if action_id == 4:
            reply_markup = getattr(message, "reply_markup", None)
            if not isinstance(reply_markup, InlineKeyboardMarkup) or not message.photo:
                return False
            flat_buttons = [button for row in reply_markup.inline_keyboard for button in row]
            clickable_buttons = [button for button in flat_buttons if getattr(button, "text", None)]
            if not clickable_buttons:
                return False
            image_bytes = await self._download_photo_bytes(client, message)
            question_text = (message.caption or message.text or "").strip() or "Choose the correct option"
            options = [button.text for button in clickable_buttons]
            result_indexes = await ai_tools.choose_options_by_image(
                image_bytes,
                question_text,
                list(enumerate(options, start=1)),
            )
            clicked = 0
            for result_index in result_indexes:
                if result_index == 0:
                    selected_index = 0
                elif 1 <= result_index <= len(options):
                    selected_index = result_index - 1
                elif 0 <= result_index < len(options):
                    selected_index = result_index
                else:
                    return False
                if await self._click_inline_button(client, message, clickable_buttons[selected_index]):
                    clicked += 1
                await asyncio.sleep(0.3)
            return clicked > 0

        return False

    async def _execute_continue_action(
        self,
        client: Any,
        target_chat_id: Union[int, str],
        target_thread_id: Optional[int],
        action: Dict[str, Any],
    ) -> bool:
        action_id = int(action.get("action"))
        kwargs: Dict[str, Any] = {}
        if target_thread_id is not None:
            kwargs["message_thread_id"] = target_thread_id

        if action_id == 1:
            text = str(action.get("text") or "").strip()
            if not text:
                return False
            await client.send_message(target_chat_id, text, **kwargs)
            return True

        if action_id == 2:
            dice = str(action.get("dice") or "🎲").strip() or "🎲"
            await client.send_dice(target_chat_id, dice, **kwargs)
            return True

        recent_message = await self._find_recent_message(
            client, target_chat_id, target_thread_id, action_id
        )
        if recent_message is None:
            logger.warning(
                "Keyword monitor continue action %s found no usable recent message in %r",
                action_id,
                target_chat_id,
            )
            return False

        if action_id == 3:
            if await self._click_keyboard_by_text(
                client, target_chat_id, target_thread_id, action, recent_message
            ):
                return True
            fallback_text = str(action.get("text") or "").strip()
            if fallback_text:
                await client.send_message(target_chat_id, fallback_text, **kwargs)
                return True
            return False

        return await self._execute_ai_action(
            client, target_chat_id, target_thread_id, action, recent_message
        )

    async def _execute_continue_actions(
        self,
        *,
        account_name: str,
        client: Any,
        rule: KeywordMonitorRule,
        message: Message,
        variables: Dict[str, str],
    ) -> None:
        continue_actions = self._continue_actions(rule.action)
        if not continue_actions:
            return

        target_chat_id, target_thread_id = self._continue_target(rule.action, message)
        interval = self._continue_interval(rule.action)
        timeout = _read_positive_float_env(
            "KEYWORD_MONITOR_CONTINUE_ACTION_TIMEOUT", DEFAULT_CONTINUE_TIMEOUT, 1.0
        )

        await self._warm_chat(client, target_chat_id)
        lock = get_account_lock(account_name)
        async with lock:
            for index, raw_action in enumerate(continue_actions, start=1):
                action = _render_action_templates(raw_action, variables)
                started = time.perf_counter()
                try:
                    result = await asyncio.wait_for(
                        self._execute_continue_action(
                            client, target_chat_id, target_thread_id, action
                        ),
                        timeout=timeout,
                    )
                except Exception as exc:
                    logger.warning(
                        "Keyword monitor continue action %s/%s failed for task %s: %s",
                        index,
                        len(continue_actions),
                        rule.task_name,
                        exc,
                        exc_info=True,
                    )
                    return
                if not result:
                    logger.warning(
                        "Keyword monitor continue action %s/%s returned false for task %s",
                        index,
                        len(continue_actions),
                        rule.task_name,
                    )
                    return
                elapsed = time.perf_counter() - started
                if interval > 0 and index < len(continue_actions):
                    await asyncio.sleep(max(interval - elapsed, 0.0))

    async def _on_message(self, account_name: str, client: Any, message: Message) -> None:
        try:
            from backend.services.config import get_config_service

            text = _message_text(message)
            if not text:
                return
            message_thread_id = self._message_thread_id(message)
            matched_rules = [
                rule
                for rule in self._rules
                if rule.account_name == account_name
                and rule.chat_id == message.chat.id
                and (
                    rule.message_thread_id is None
                    or rule.message_thread_id == message_thread_id
                )
            ]
            if not matched_rules:
                return

            global_settings = get_config_service().get_global_settings()
            url = _message_url(message)
            chat_title = (
                getattr(message.chat, "title", None)
                or getattr(message.chat, "username", None)
                or str(getattr(message.chat, "id", ""))
            )
            sender = ""
            if message.from_user:
                sender = (
                    message.from_user.username
                    or " ".join(
                        item
                        for item in [
                            message.from_user.first_name,
                            message.from_user.last_name,
                        ]
                        if item
                    )
                    or str(message.from_user.id)
                )

            for rule in matched_rules:
                matched = self._match_keyword(rule.action, text)
                if not matched:
                    continue
                body_lines = [
                    f"Task: {rule.task_name}",
                    f"Chat: {chat_title}",
                    f"Keyword: {matched}",
                ]
                if sender:
                    body_lines.append(f"Sender: {sender}")
                body_lines.append("")
                body_lines.append(text)
                forward_text = "\n".join(body_lines)
                variables = self._build_variables(
                    account_name=account_name,
                    rule=rule,
                    message=message,
                    text=text,
                    matched=matched,
                    chat_title=chat_title,
                    sender=sender,
                    url=url,
                )

                push_channel = str(rule.action.get("push_channel") or "telegram").strip()
                forward_chat_id = (
                    _parse_forward_chat_id(rule.action.get("forward_chat_id"))
                    if push_channel == "forward"
                    else None
                )
                if forward_chat_id is not None:
                    try:
                        forward_kwargs: dict[str, Any] = {}
                        forward_thread_id = _as_int_or_none(
                            rule.action.get("forward_message_thread_id")
                        )
                        if forward_thread_id is not None:
                            forward_kwargs["message_thread_id"] = forward_thread_id
                        forward_payload = forward_text
                        if url:
                            forward_payload += f"\n\nLink: {url}"
                        await client.send_message(
                            forward_chat_id,
                            forward_payload[:3900],
                            **forward_kwargs,
                        )
                    except Exception as exc:
                        logger.warning(
                            "Failed to forward keyword match to %r: %s",
                            forward_chat_id,
                            exc,
                        )

                if push_channel != "forward":
                    push_settings = dict(global_settings)
                    push_settings["keyword_monitor_push_channel"] = push_channel
                    push_settings["keyword_monitor_bark_url"] = rule.action.get("bark_url")
                    push_settings["keyword_monitor_custom_url"] = rule.action.get(
                        "custom_url"
                    )
                    await send_keyword_push(
                        push_settings,
                        {
                            "title": "TG-SignPulse keyword matched",
                            "body": forward_text,
                            "text": text,
                            "keyword": matched,
                            "account_name": account_name,
                            "task_name": rule.task_name,
                            "chat_id": getattr(message.chat, "id", None),
                            "chat_title": chat_title,
                            "sender": sender,
                            "message_id": message.id,
                            "url": url,
                        },
                    )
                await self._execute_continue_actions(
                    account_name=account_name,
                    client=client,
                    rule=rule,
                    message=message,
                    variables=variables,
                )
        except Exception as exc:
            logger.warning("Keyword monitor handling failed: %s", exc, exc_info=True)

    async def restart_from_tasks(self) -> None:
        async with self._lock:
            from backend.services.config import get_config_service
            from tg_signer.core import get_client

            rules = self._load_rules()
            key = self._rules_key(rules)
            if key == self._active_key:
                return

            await self.stop()
            self._rules = rules
            if not rules:
                self._active_key = key
                return

            session_dir = settings.resolve_session_dir()
            global_settings = get_config_service().get_global_settings()
            tg_config = get_config_service().get_telegram_config()
            api_id = os.getenv("TG_API_ID") or tg_config.get("api_id")
            api_hash = os.getenv("TG_API_HASH") or tg_config.get("api_hash")
            try:
                api_id = int(api_id) if api_id is not None else None
            except (TypeError, ValueError):
                api_id = None

            accounts = sorted({rule.account_name for rule in rules})
            for account_name in accounts:
                account_rules = [rule for rule in rules if rule.account_name == account_name]
                chat_ids = sorted({rule.chat_id for rule in account_rules})
                proxy_value = get_account_proxy(account_name)
                if not proxy_value:
                    proxy_value = (global_settings.get("global_proxy") or "").strip() or None
                proxy = build_proxy_dict(proxy_value) if proxy_value else None

                session_mode = get_session_mode()
                session_string = None
                in_memory = False
                if session_mode == "string":
                    session_string = get_account_session_string(
                        account_name
                    ) or load_session_string_file(session_dir, account_name)
                    in_memory = bool(session_string)
                    if not session_string:
                        logger.warning(
                            "Keyword monitor account %s has no session_string",
                            account_name,
                        )
                        continue

                client = get_client(
                    account_name,
                    proxy=proxy,
                    workdir=session_dir,
                    session_string=session_string,
                    in_memory=in_memory,
                    api_id=api_id,
                    api_hash=api_hash,
                    no_updates=False,
                )

                async def handler(client, message: Message, name: str = account_name) -> None:
                    await self._on_message(name, client, message)

                handler_ref = client.add_handler(
                    MessageHandler(
                        handler,
                        filters.chat(chat_ids) & (filters.text | filters.caption),
                    )
                )
                self._handler_refs.append((client, handler_ref))

                lock = get_account_lock(account_name)
                async with lock:
                    if not getattr(client, "is_connected", False):
                        await client.start()
                logger.info(
                    "Keyword monitor started for %s in %s", account_name, chat_ids
                )

            self._active_key = key

    async def stop(self) -> None:
        for client, handler_ref in self._handler_refs:
            try:
                client.remove_handler(*handler_ref)
            except Exception:
                pass
        self._handler_refs = []
        self._rules = []


_keyword_monitor_service: Optional[KeywordMonitorService] = None


def get_keyword_monitor_service() -> KeywordMonitorService:
    global _keyword_monitor_service
    if _keyword_monitor_service is None:
        _keyword_monitor_service = KeywordMonitorService()
    return _keyword_monitor_service

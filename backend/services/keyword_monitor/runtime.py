"""关键词监控服务（规则见 rules.py）。"""
# 规则工具通过 rules.__all__ + star import 注入；动态名称对静态检查不可见
# ruff: noqa: F401, F403, F405, F821
from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import time
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

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
from tg_signer.compat import (
    InlineKeyboardMarkup,
    Message,
    MessageHandler,
    ReplyKeyboardMarkup,
    errors,
    filters,
)
from tg_signer.log_utils import (
    safe_ai_request_meta,
    safe_ai_result_meta,
    safe_text_preview,
)
from backend.services.keyword_monitor.rules import *  # noqa: F403

# 确保 rules 中以下划线开头的符号也可通过 star import 获得
import backend.services.keyword_monitor.rules as _km_rules

for _name, _val in vars(_km_rules).items():
    if _name.startswith("__"):
        continue
    globals().setdefault(_name, _val)
del _name, _val


class KeywordMonitorService:
    def __init__(self) -> None:
        self._handler_refs: list[tuple[str, Any, Any]] = []
        self._rules: list[KeywordMonitorRule] = []
        self._active_key = ""
        self._lock = asyncio.Lock()
        self._task_logs: dict[tuple[str, str], list[str]] = {}
        self._task_status: dict[tuple[str, str], dict[str, Any]] = {}
        self._skip_log_times: dict[tuple[str, str, str], float] = {}
        self._ai_tools: Optional[Any] = None
        self._ai_cfg_signature: Optional[tuple[str, str, str]] = None
        self._bot_cmd_last_sent: dict[str, float] = {}

    async def _ensure_client_ready(self, client: Any) -> None:
        if getattr(client, "is_connected", False):
            if not getattr(client, "is_initialized", False):
                try:
                    await client.initialize()
                except ConnectionError as exc:
                    if "already initialized" not in str(exc).lower():
                        raise
            return

        is_authorized = await client.connect()
        if not is_authorized:
            raise ConnectionError("Session invalid: unauthorized")

        try:
            await client.get_me()
        except Exception as exc:
            raise ConnectionError(f"Session invalid: {exc}") from exc

        if not getattr(client, "is_initialized", False):
            try:
                await client.initialize()
            except ConnectionError as exc:
                if "already initialized" not in str(exc).lower():
                    raise

    async def _call_client_with_retry(
        self,
        client: Any,
        callback,
        *,
        operation: str,
        max_retries: int = 4,
    ):
        for attempt in range(1, max_retries + 1):
            try:
                return await callback()
            except errors.FloodWait as exc:
                wait_seconds = max(int(getattr(exc, "value", 1) or 1), 1)
                logger.warning(
                    "%s hit FloodWait, retrying in %ss (%s/%s)",
                    operation,
                    wait_seconds,
                    attempt,
                    max_retries,
                )
                if attempt >= max_retries:
                    raise
                await asyncio.sleep(wait_seconds)
            except (TimeoutError, asyncio.TimeoutError, OSError, ConnectionError) as exc:
                backoff = min(2 ** (attempt - 1), 8)
                logger.warning(
                    "%s transient failure, retrying in %ss (%s/%s): %s: %s",
                    operation,
                    backoff,
                    attempt,
                    max_retries,
                    type(exc).__name__,
                    exc,
                )
                if attempt >= max_retries:
                    raise
                try:
                    await self._ensure_client_ready(client)
                except Exception as reconnect_exc:
                    logger.warning(
                        "%s reconnect failed: %s: %s",
                        operation,
                        type(reconnect_exc).__name__,
                        reconnect_exc,
                    )
                await asyncio.sleep(backoff)

    def _task_key(self, account_name: str, task_name: str) -> tuple[str, str]:
        return account_name, task_name

    def _should_log_rule_event(
        self,
        rule: KeywordMonitorRule,
        event_key: str,
        *,
        interval_seconds: float = 30.0,
    ) -> bool:
        now = time.monotonic()
        cache_key = (rule.account_name, rule.task_name, event_key)
        last_logged_at = self._skip_log_times.get(cache_key, 0.0)
        if now - last_logged_at < interval_seconds:
            return False
        self._skip_log_times[cache_key] = now
        return True

    def _append_task_log(
        self,
        account_name: str,
        task_name: str,
        line: str,
        *,
        active: Optional[bool] = None,
    ) -> None:
        key = self._task_key(account_name, task_name)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logs = self._task_logs.setdefault(key, [])
        logs.append(f"{timestamp} - {line}")
        if len(logs) > 1000:
            del logs[:-1000]

        status = self._task_status.setdefault(key, {})
        status["updated_at"] = datetime.now().isoformat(timespec="seconds")
        status["message"] = line
        if active is not None:
            status["active"] = active

    def _append_rule_log(
        self,
        rule: KeywordMonitorRule,
        line: str,
        *,
        active: Optional[bool] = None,
    ) -> None:
        self._append_task_log(
            rule.account_name,
            rule.task_name,
            line,
            active=active,
        )

    def get_task_logs(self, task_name: str, account_name: Optional[str] = None) -> list[str]:
        if account_name:
            return list(self._task_logs.get(self._task_key(account_name, task_name), []))

        for (_item_account, item_task), logs in self._task_logs.items():
            if item_task == task_name:
                return list(logs)
        return []

    def get_task_history_entry(
        self,
        task_name: str,
        account_name: str,
    ) -> Optional[dict[str, Any]]:
        key = self._task_key(account_name, task_name)
        logs = self._task_logs.get(key) or []
        status = self._task_status.get(key)
        if not logs and not status:
            return None

        flow_logs = list(logs[-500:])
        return {
            "time": (status or {}).get("updated_at", ""),
            "success": bool((status or {}).get("active", False)),
            "message": (status or {}).get("message", "关键词后台监听状态"),
            "account_name": account_name,
            "flow_logs": flow_logs,
            "flow_truncated": len(logs) > len(flow_logs),
            "flow_line_count": len(logs),
        }

    def _describe_rule(self, rule: KeywordMonitorRule) -> str:
        keywords = _parse_keywords(
            rule.action.get("keywords"),
            split_commas=_keyword_split_commas(rule.action),
        )
        preview = ", ".join(keywords[:3])
        if len(keywords) > 3:
            preview += f" ... 共 {len(keywords)} 条"
        push_channel = str(rule.action.get("push_channel") or "telegram").strip()
        continue_actions = self._continue_actions(rule.action)
        parts = [
            f"Chat={rule.chat_name}({rule.chat_id})",
            f"匹配方式={rule.action.get('match_mode') or 'contains'}",
            f"关键词={preview or '-'}",
            f"命中处理={push_channel}",
        ]
        if rule.message_thread_id is not None:
            parts.append(f"话题ID={rule.message_thread_id}")
        if rule.sender_filter is not None:
            parts.append(f"发送者={','.join(rule.sender_filter)}")
        if push_channel == "continue":
            parts.append(f"后续动作={len(continue_actions)} 步")
        return "，".join(parts)

    def _describe_continue_action(self, action: Dict[str, Any]) -> str:
        try:
            action_id = int(action.get("action"))
        except (TypeError, ValueError):
            return f"未知动作: {action}"
        if action_id == 1:
            text = str(action.get("text") or "")
            return f"发送文本: {text[:120]}"
        if action_id == 2:
            return f"发送骰子: {action.get('dice') or '🎲'}"
        if action_id == 3:
            return f"点击按钮: {action.get('text') or ''}"
        if action_id == 4:
            return "AI 识图选择按钮"
        if action_id == 5:
            return "AI 计算并发送答案"
        if action_id == 6:
            return "AI 识图并发送文本"
        if action_id == 7:
            return "AI 计算并点击按钮"
        if action_id == 9:
            bot = _normalize_bot_username(action.get("bot_username"))
            cmd = str(action.get("command_prefix") or "").strip() or DEFAULT_COMMAND_PREFIX
            if not cmd.startswith("/"):
                cmd = f"/{cmd}"
            if bot:
                return f"触发 Bot 命令: @{bot} {cmd}"
            return f"触发 Bot 命令 {cmd}（可从深链解析 Bot）"
        return f"动作 {action_id}"

    def _rules_key(self, rules: list[KeywordMonitorRule]) -> str:
        return repr(
            [
                {
                    "account_name": rule.account_name,
                    "task_name": rule.task_name,
                    "chat_id": rule.chat_id,
                    "message_thread_id": rule.message_thread_id,
                    "sender_filter": rule.sender_filter,
                    "action": rule.action,
                }
                for rule in rules
            ]
        )

    def _handlers_are_active_for(self, rules: list[KeywordMonitorRule]) -> bool:
        expected_accounts = {rule.account_name for rule in rules}
        if not expected_accounts:
            return not self._handler_refs

        active_accounts = {
            account_name
            for account_name, client, _handler_ref in self._handler_refs
            if getattr(client, "is_connected", False)
            and getattr(client, "_tg_signpulse_no_updates", None) is False
        }
        return expected_accounts.issubset(active_accounts)

    def _load_rules(self) -> list[KeywordMonitorRule]:
        from backend.services.keyword_monitor.sharding import account_in_monitor_scope
        from backend.services.sign_tasks import get_sign_task_service

        rules: list[KeywordMonitorRule] = []
        tasks = get_sign_task_service().list_tasks(force_refresh=True)
        for task in tasks:
            account_name = str(task.get("account_name") or "").strip()
            task_name = str(task.get("name") or "").strip()
            if not account_name or not task_name or not task.get("enabled", True):
                continue
            # 多实例分片：不在本实例范围的账号跳过
            if not account_in_monitor_scope(account_name):
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
                    if action_id != 8 or not _parse_keywords(
                        action.get("keywords"),
                        split_commas=_keyword_split_commas(action),
                    ):
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
                            sender_filter=_parse_sender_filter(
                                chat.get("sender_filter")
                            ),
                            action=dict(action),
                        )
                    )
        return rules

    def _match_keyword(self, action: Dict[str, Any], text: str) -> Optional[str]:
        """兼容单值命中：返回首个捕获值。"""
        matches = _match_all_keyword_values(action, text)
        return matches[0] if matches else None

    def _message_thread_id(self, message: Message) -> Optional[int]:
        candidates = _message_thread_candidates(message)
        return candidates[0] if candidates else None

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

        supported = {1, 2, 3, 4, 5, 6, 7, 9}
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

    @staticmethod
    def _build_ai_cfg_signature(cfg: Dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(cfg.get("api_key") or ""),
            str(cfg.get("base_url") or ""),
            str(cfg.get("model") or ""),
        )

    def _get_ai_tools(self):
        from tg_signer.ai_tools import AITools, OpenAIConfigManager

        for workdir in (settings.resolve_session_dir(), settings.resolve_workdir()):
            cfg = OpenAIConfigManager(workdir).load_config()
            if cfg:
                signature = self._build_ai_cfg_signature(cfg)
                if self._ai_tools is None or self._ai_cfg_signature != signature:
                    self._ai_tools = AITools(cfg)
                    self._ai_cfg_signature = signature
                return self._ai_tools
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
                    logger.warning(
                        "Keyword monitor button callback did not respond after retries: %s",
                        exc,
                    )
                    return False
                try:
                    await self._ensure_client_ready(client)
                except Exception as reconnect_exc:
                    logger.warning(
                        "Keyword monitor callback reconnect failed: %s: %s",
                        type(reconnect_exc).__name__,
                        reconnect_exc,
                    )
                await asyncio.sleep(min(2**attempt, 6))
            except Exception as exc:
                if _is_callback_data_invalid(exc):
                    logger.warning(
                        "Keyword monitor callback returned DATA_INVALID; waiting for follow-up messages"
                    )
                    return False
                logger.warning("Keyword monitor callback could not be confirmed: %s", exc)
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
                    if _is_callback_data_invalid(exc):
                        logger.warning(
                            "Keyword monitor Message.click could not confirm callback; waiting for follow-up messages"
                        )
                    else:
                        logger.warning(
                            "Keyword monitor Message.click could not confirm callback: %s",
                            exc,
                        )
                    return False
        return False

    async def _click_keyboard_by_text_result(
        self,
        client: Any,
        target_chat_id: Union[int, str],
        target_thread_id: Optional[int],
        action: Dict[str, Any],
        message: Message,
    ) -> tuple[bool, bool]:
        target_text = _clean_text_for_match(str(action.get("text") or ""))
        if not target_text:
            return False, False

        reply_markup = getattr(message, "reply_markup", None)
        if isinstance(reply_markup, InlineKeyboardMarkup):
            flat_buttons = (button for row in reply_markup.inline_keyboard for button in row)
            for button in flat_buttons:
                button_text = getattr(button, "text", None)
                if not button_text:
                    continue
                if _button_text_matches(target_text, _clean_text_for_match(button_text)):
                    return await self._click_inline_button(client, message, button), True
            return False, False

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
                        await self._call_client_with_retry(
                            client,
                            lambda _button_text=button_text, _kwargs=dict(kwargs): client.send_message(
                                target_chat_id, _button_text, **_kwargs
                            ),
                            operation=f"keyword monitor send reply keyboard {target_chat_id}",
                        )
                        return True, True
        return False, False

    async def _click_keyboard_by_text(
        self,
        client: Any,
        target_chat_id: Union[int, str],
        target_thread_id: Optional[int],
        action: Dict[str, Any],
        message: Message,
    ) -> bool:
        clicked, _matched = await self._click_keyboard_by_text_result(
            client,
            target_chat_id,
            target_thread_id,
            action,
            message,
        )
        return clicked

    async def _recent_messages(
        self,
        client: Any,
        chat_id: Union[int, str],
        thread_id: Optional[int],
        limit: int,
    ) -> list[Message]:
        async def _load_messages() -> list[Message]:
            messages: list[Message] = []
            async for message in client.get_chat_history(chat_id, limit=limit):
                if _message_matches_thread(message, thread_id):
                    messages.append(message)
            return messages

        return await self._call_client_with_retry(
            client,
            _load_messages,
            operation=f"keyword monitor get_chat_history {chat_id}",
        )

    def _message_supports_action(self, message: Message, action_id: int) -> bool:
        reply_markup = getattr(message, "reply_markup", None)
        if action_id == 3:
            return bool(reply_markup)
        if action_id == 4:
            return bool(message.photo and _collect_clickable_buttons(message))
        if action_id == 5:
            return bool(message.text or message.caption)
        if action_id == 6:
            return bool(message.photo)
        if action_id == 7:
            return bool((message.text or message.caption) and reply_markup)
        if action_id == 9:
            return bool(message.text or message.caption)
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

    async def _wait_for_chat_advance(
        self,
        client: Any,
        chat_id: Union[int, str],
        thread_id: Optional[int],
        before_state: dict[int, tuple[Any, ...]],
        *,
        limit: int,
        timeout: float,
    ) -> bool:
        deadline = time.perf_counter() + max(timeout, 0.5)
        while time.perf_counter() < deadline:
            await asyncio.sleep(0.5)
            messages = await self._recent_messages(client, chat_id, thread_id, limit)
            current_state = _messages_state(messages)
            for message_id, marker in current_state.items():
                if before_state.get(message_id) != marker:
                    return True
        return False

    async def _wait_for_continue_action_candidate(
        self,
        client: Any,
        chat_id: Union[int, str],
        thread_id: Optional[int],
        action: Dict[str, Any],
        before_state: dict[int, tuple[Any, ...]],
        *,
        limit: int,
        timeout: float,
    ) -> bool:
        deadline = time.perf_counter() + max(timeout, 0.5)
        while time.perf_counter() < deadline:
            await asyncio.sleep(0.5)
            messages = await self._recent_messages(client, chat_id, thread_id, limit)
            current_state = _messages_state(messages)
            changed_ids = {
                message_id
                for message_id, marker in current_state.items()
                if before_state.get(message_id) != marker
            }
            for message in messages:
                if (
                    message.id in changed_ids
                    and _message_supports_continue_action(message, action)
                ):
                    return True
        return False

    async def _wait_for_terminal_success(
        self,
        client: Any,
        chat_id: Union[int, str],
        thread_id: Optional[int],
        before_state: dict[int, tuple[Any, ...]],
        *,
        limit: int,
        timeout: float,
    ) -> bool:
        deadline = time.perf_counter() + max(timeout, 0.5)
        while time.perf_counter() < deadline:
            await asyncio.sleep(0.5)
            messages = await self._recent_messages(client, chat_id, thread_id, limit)
            current_state = _messages_state(messages)
            changed_ids = {
                message_id
                for message_id, marker in current_state.items()
                if before_state.get(message_id) != marker
            }
            for message in messages:
                if message.id in changed_ids and _message_has_terminal_success_text(
                    message
                ):
                    return True
        return False

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
            model = ai_tools.default_model
            logger.info(f"关键词监听 AI 请求 | chat={target_chat_id} | {safe_ai_request_meta(method='calculate_problem', model=model, query_chars=len(query), question_preview=query)}")
            _start = time.monotonic()
            try:
                answer = (
                    await ai_tools.calculate_problem(
                        query,
                        system_prompt=action.get("ai_prompt"),
                    )
                    or ""
                ).strip()
                _elapsed = (time.monotonic() - _start) * 1000
                logger.info(f"关键词监听 AI 响应 | chat={target_chat_id} | {safe_ai_result_meta(method='calculate_problem', model=model, elapsed_ms=_elapsed, response_chars=len(answer), selected_options=[answer] if answer else [])}")
            except Exception as e:
                _elapsed = (time.monotonic() - _start) * 1000
                logger.error(f"关键词监听 AI 调用失败 | chat={target_chat_id} | method=calculate_problem elapsed_ms={_elapsed:.0f} error={type(e).__name__}: {safe_text_preview(e, 200)}")
                raise TerminalAIActionError(f"AI calculate_problem failed: {type(e).__name__}") from e
            if not answer:
                return False
            await self._call_client_with_retry(
                client,
                lambda: client.send_message(target_chat_id, answer, **kwargs),
                operation=f"keyword monitor AI text reply {target_chat_id}",
            )
            return True

        if action_id == 6:
            image_bytes = await self._download_photo_bytes(client, message)
            model = ai_tools.default_model
            logger.info(f"关键词监听 AI 请求 | chat={target_chat_id} | {safe_ai_request_meta(method='extract_text_by_image', model=model, has_image=True, image_bytes=len(image_bytes))}")
            _start = time.monotonic()
            try:
                answer = (
                    await ai_tools.extract_text_by_image(
                        image_bytes,
                        system_prompt=action.get("ai_prompt"),
                    )
                    or ""
                ).strip()
                _elapsed = (time.monotonic() - _start) * 1000
                logger.info(f"关键词监听 AI 响应 | chat={target_chat_id} | {safe_ai_result_meta(method='extract_text_by_image', model=model, elapsed_ms=_elapsed, response_chars=len(answer), selected_options=[answer] if answer else [])}")
            except Exception as e:
                _elapsed = (time.monotonic() - _start) * 1000
                logger.error(f"关键词监听 AI 调用失败 | chat={target_chat_id} | method=extract_text_by_image elapsed_ms={_elapsed:.0f} error={type(e).__name__}: {safe_text_preview(e, 200)}")
                raise TerminalAIActionError(f"AI extract_text_by_image failed: {type(e).__name__}") from e
            if not answer:
                return False
            await self._call_client_with_retry(
                client,
                lambda: client.send_message(target_chat_id, answer, **kwargs),
                operation=f"keyword monitor AI OCR reply {target_chat_id}",
            )
            return True

        if action_id == 7:
            query = (message.text or message.caption or "").strip()
            model = ai_tools.default_model
            logger.info(f"关键词监听 AI 请求 | chat={target_chat_id} | {safe_ai_request_meta(method='calculate_problem', model=model, query_chars=len(query), question_preview=query)}")
            _start = time.monotonic()
            try:
                answer = (
                    await ai_tools.calculate_problem(
                        query,
                        system_prompt=action.get("ai_prompt"),
                    )
                    or ""
                ).strip()
                _elapsed = (time.monotonic() - _start) * 1000
                logger.info(f"关键词监听 AI 响应 | chat={target_chat_id} | {safe_ai_result_meta(method='calculate_problem', model=model, elapsed_ms=_elapsed, response_chars=len(answer), selected_options=[answer] if answer else [])}")
            except Exception as e:
                _elapsed = (time.monotonic() - _start) * 1000
                logger.error(f"关键词监听 AI 调用失败 | chat={target_chat_id} | method=calculate_problem elapsed_ms={_elapsed:.0f} error={type(e).__name__}: {safe_text_preview(e, 200)}")
                raise TerminalAIActionError(f"AI calculate+click failed: {type(e).__name__}") from e
            if not answer:
                return False
            proxy_action = {"action": 3, "text": answer}
            return await self._click_keyboard_by_text(
                client, target_chat_id, target_thread_id, proxy_action, message
            )

        if action_id == 4:
            if not message.photo:
                return False
            clickable_buttons = _collect_clickable_buttons(message)
            if not clickable_buttons:
                return False
            image_bytes = await self._download_photo_bytes(client, message)
            question_text = (message.caption or message.text or "").strip() or "Choose the correct option"
            options = [button_text for _, _, button_text in clickable_buttons]
            model = ai_tools.default_model
            logger.info(f"关键词监听 AI 请求 | chat={target_chat_id} | {safe_ai_request_meta(method='choose_options_by_image', model=model, has_image=True, image_bytes=len(image_bytes), query_chars=len(question_text), options_count=len(options), question_preview=question_text, options_preview=options)}")
            _start = time.monotonic()
            try:
                result_indexes = await ai_tools.choose_options_by_image(
                    image_bytes,
                    question_text,
                    list(enumerate(options, start=1)),
                    system_prompt=action.get("ai_prompt"),
                )
                _elapsed = (time.monotonic() - _start) * 1000
                # 收集选中的选项内容
                selected_options = []
                if result_indexes:
                    for idx in result_indexes:
                        if 1 <= idx <= len(options):
                            selected_options.append(options[idx - 1])
                        elif 0 <= idx < len(options):
                            selected_options.append(options[idx])
                logger.info(f"关键词监听 AI 响应 | chat={target_chat_id} | {safe_ai_result_meta(method='choose_options_by_image', model=model, elapsed_ms=_elapsed, result_type='list', result_count=len(result_indexes or []), selected_options=selected_options)}")
            except Exception as e:
                _elapsed = (time.monotonic() - _start) * 1000
                logger.error(f"关键词监听 AI 调用失败 | chat={target_chat_id} | method=choose_options_by_image elapsed_ms={_elapsed:.0f} error={type(e).__name__}: {safe_text_preview(e, 200)}")
                raise TerminalAIActionError(f"AI choose_options_by_image failed: {type(e).__name__}") from e
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
                button_kind, button, button_text = clickable_buttons[selected_index]
                if button_kind == "inline":
                    if await self._click_inline_button(client, message, button):
                        clicked += 1
                else:
                    await self._call_client_with_retry(
                        client,
                        lambda _button_text=button_text, _kwargs=dict(kwargs): client.send_message(
                            target_chat_id, _button_text, **_kwargs
                        ),
                        operation=f"keyword monitor reply keyboard click {target_chat_id}",
                    )
                    clicked += 1
                await asyncio.sleep(0.3)
            return clicked > 0

        return False

    def _prune_bot_cmd_rate_map(self) -> None:
        if len(self._bot_cmd_last_sent) <= 1000:
            return
        cutoff = time.monotonic() - 300.0
        self._bot_cmd_last_sent = {
            key: sent_at
            for key, sent_at in self._bot_cmd_last_sent.items()
            if sent_at > cutoff
        }

    async def _await_bot_cmd_slot(self, rate_key: str, interval: float) -> None:
        """等待直到距离上次发送已满足间隔，避免硬跳过批量码。"""
        if interval <= 0:
            self._bot_cmd_last_sent[rate_key] = time.monotonic()
            self._prune_bot_cmd_rate_map()
            return
        now = time.monotonic()
        last_sent = self._bot_cmd_last_sent.get(rate_key, 0.0)
        wait_seconds = interval - (now - last_sent)
        if wait_seconds > 0:
            logger.debug(
                "Bot 命令间隔等待：key=%s wait=%.2fs interval=%.2fs",
                rate_key,
                wait_seconds,
                interval,
            )
            await asyncio.sleep(wait_seconds)
        self._bot_cmd_last_sent[rate_key] = time.monotonic()
        self._prune_bot_cmd_rate_map()

    def _collect_bot_cmd_jobs(
        self,
        action: Dict[str, Any],
        *,
        message_text: str,
        variables: Dict[str, str],
        match_action: Optional[Dict[str, Any]] = None,
    ) -> List[tuple[str, str]]:
        """
        收集待发送的 (bot_username, start_param) 列表。

        优先级：
        1. 消息中的 t.me/?start= 深链（可自动解析 Bot 名）
        2. 父规则关键词多匹配 + start_param 模板
        3. 变量中的单个 {keyword}
        """
        configured_bot = _normalize_bot_username(action.get("bot_username"))
        parse_deep_links = _as_bool(action.get("parse_deep_links"), True)
        multi_match = _as_bool(action.get("multi_match"), True)
        raw_max_batch = action.get("max_batch")
        max_batch = _as_positive_int(
            raw_max_batch, DEFAULT_BOT_CMD_MAX_BATCH, minimum=1
        )
        # 显式调高批量上限时提醒风控风险
        if raw_max_batch is not None and max_batch > DEFAULT_BOT_CMD_MAX_BATCH:
            logger.warning(
                "Bot 命令 max_batch=%s 高于默认值 %s：%s",
                max_batch,
                DEFAULT_BOT_CMD_MAX_BATCH,
                _BOT_CMD_MAX_BATCH_RISK_HINT,
            )
        jobs: List[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()

        def _append_job(bot: str, param: str) -> None:
            bot_name = _normalize_bot_username(bot)
            start_param = str(param or "").strip()
            if not bot_name or not start_param:
                return
            key = (bot_name.lower(), start_param)
            if key in seen:
                return
            seen.add(key)
            jobs.append((bot_name, start_param))

        if parse_deep_links and message_text:
            for link_bot, link_param in _extract_tg_start_links(message_text):
                _append_job(configured_bot or link_bot, link_param)

        if not jobs:
            start_param_tpl = str(action.get("start_param") or "{keyword}")
            keyword_source = match_action if isinstance(match_action, dict) else action
            keyword_values: List[str] = []
            if multi_match and "{keyword}" in start_param_tpl and message_text:
                keyword_values = _match_all_keyword_values(keyword_source, message_text)
            if not keyword_values:
                single = str(variables.get("keyword") or "").strip()
                if single:
                    keyword_values = [single]

            if multi_match and "{keyword}" in start_param_tpl and keyword_values:
                for keyword in keyword_values:
                    rendered = str(
                        _render_template(
                            start_param_tpl, {**variables, "keyword": keyword}
                        )
                    ).strip()
                    _append_job(configured_bot, rendered)
            else:
                rendered = str(
                    _render_template(start_param_tpl, variables)
                ).strip()
                _append_job(configured_bot, rendered)

        if len(jobs) > max_batch:
            logger.warning(
                "Bot 命令批量截断：候选 %s 条，仅发送前 %s 条。%s",
                len(jobs),
                max_batch,
                _BOT_CMD_MAX_BATCH_RISK_HINT,
            )
        return jobs[:max_batch]

    async def _execute_bot_link_action(
        self,
        client: Any,
        target_chat_id: Union[int, str],
        target_thread_id: Optional[int],
        action: Dict[str, Any],
        *,
        source_message: Optional[Message] = None,
        variables: Optional[Dict[str, str]] = None,
        account_name: str = "",
        task_name: str = "",
        match_action: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        执行 action_id=9：向 Bot 发送命令。

        增强能力：
        - 解析消息内 t.me/bot?start= 深链并逐条触发（默认最多 5 条）
        - 正则多匹配时批量发送捕获值（受 max_batch 限制）
        - 未配置 bot_username 时可从深链自动解析 Bot 名
        - 批量发送按间隔等待；调高 max_batch 有风控/封禁风险
        """
        logger.warning(
            "[BOT_CMD_ENTRY] bot_username=%s | source_message=%s | variables=%s | action=%s",
            action.get("bot_username"),
            "present" if source_message else "None",
            variables,
            action,
        )
        if source_message is None:
            logger.warning("Bot 命令触发跳过：source_message 为 None")
            return False

        variables = variables or {}
        message_text = _message_text(source_message)
        jobs = self._collect_bot_cmd_jobs(
            action,
            message_text=message_text,
            variables=variables,
            match_action=match_action,
        )
        if not jobs:
            configured_bot = _normalize_bot_username(action.get("bot_username"))
            if not configured_bot:
                logger.warning(
                    "Bot 命令触发跳过：未配置 bot_username 且消息中无可解析的 t.me/?start= 链接"
                )
            else:
                logger.warning("Bot 命令触发跳过：start_param 为空")
            return False

        command_prefix = (
            str(action.get("command_prefix") or "").strip() or DEFAULT_COMMAND_PREFIX
        )
        if not command_prefix.startswith("/"):
            command_prefix = f"/{command_prefix}"
        send_interval = _as_non_negative_float(
            action.get("send_interval"), DEFAULT_BOT_CMD_INTERVAL
        )

        log_rule = KeywordMonitorRule(
            account_name=account_name,
            task_name=task_name,
            chat_id=target_chat_id if isinstance(target_chat_id, int) else 0,
            chat_name=str(target_chat_id),
            message_thread_id=target_thread_id,
            sender_filter=None,
            action=action,
        )
        max_batch = _as_positive_int(
            action.get("max_batch"), DEFAULT_BOT_CMD_MAX_BATCH, minimum=1
        )
        if max_batch > DEFAULT_BOT_CMD_MAX_BATCH:
            self._append_rule_log(
                log_rule,
                f"警告：max_batch={max_batch} 高于默认 {DEFAULT_BOT_CMD_MAX_BATCH}，"
                f"{_BOT_CMD_MAX_BATCH_RISK_HINT}",
            )
        if len(jobs) > 1:
            self._append_rule_log(
                log_rule,
                f"Bot 命令批量触发：共 {len(jobs)} 条（上限 {max_batch}），"
                f"间隔 {send_interval:g}s",
            )

        success_count = 0
        for bot_username, start_param in jobs:
            rate_key = f"{account_name}:{bot_username.lower()}"
            await self._await_bot_cmd_slot(rate_key, send_interval)
            logger.info(
                "Bot 命令 action 发送 | bot=%s | cmd=%s | param=%s | chat=%s",
                bot_username,
                command_prefix,
                start_param,
                target_chat_id,
            )
            try:
                result = await self._call_client_with_retry(
                    client,
                    lambda _bot=bot_username, _param=start_param, _cmd=command_prefix: client.send_message(
                        _bot, f"{_cmd} {_param}"
                    ),
                    operation=f"keyword monitor bot cmd {bot_username}",
                )
                msg_id = getattr(result, "id", None)
                chat = getattr(result, "chat", None)
                chat_id = getattr(chat, "id", None)
                logger.info(
                    "Bot 命令 action 成功 | bot=%s | param=%s | msg_id=%s | result_chat_id=%s",
                    bot_username,
                    start_param,
                    msg_id,
                    chat_id,
                )
                self._append_rule_log(
                    log_rule,
                    f"Bot 命令触发成功：向 @{bot_username} 发送 {command_prefix} {start_param}",
                )
                success_count += 1
            except Exception as exc:
                logger.warning(
                    "Bot 命令 action 异常 | bot=%s | cmd=%s | param=%s | error=%s: %s",
                    bot_username,
                    command_prefix,
                    start_param,
                    type(exc).__name__,
                    str(exc)[:200],
                    exc_info=True,
                )
                self._append_rule_log(
                    log_rule,
                    f"Bot 命令触发失败：@{bot_username} {command_prefix} {start_param}，错误={exc}",
                )

        return success_count > 0

    async def _execute_continue_action(
        self,
        client: Any,
        target_chat_id: Union[int, str],
        target_thread_id: Optional[int],
        action: Dict[str, Any],
        timeout: Optional[float] = None,
        next_action: Optional[Dict[str, Any]] = None,
        *,
        source_message: Optional[Message] = None,
        variables: Optional[Dict[str, str]] = None,
        account_name: str = "",
        task_name: str = "",
        match_action: Optional[Dict[str, Any]] = None,
    ) -> bool:
        action_id = int(action.get("action"))
        logger.warning(
            "[CONTINUE_ACTION_ENTRY] action_id=%s | action=%s | source_message=%s",
            action_id, action, "present" if source_message else "None",
        )
        kwargs: Dict[str, Any] = {}
        if target_thread_id is not None:
            kwargs["message_thread_id"] = target_thread_id

        if action_id == 1:
            text = str(action.get("text") or "").strip()
            if not text:
                return False
            await self._call_client_with_retry(
                client,
                lambda: client.send_message(target_chat_id, text, **kwargs),
                operation=f"keyword monitor continue send_message {target_chat_id}",
            )
            return True

        if action_id == 2:
            dice = str(action.get("dice") or "🎲").strip() or "🎲"
            await self._call_client_with_retry(
                client,
                lambda: client.send_dice(target_chat_id, dice, **kwargs),
                operation=f"keyword monitor continue send_dice {target_chat_id}",
            )
            return True

        if action_id == 9:
            return await self._execute_bot_link_action(
                client, target_chat_id, target_thread_id, action,
                source_message=source_message,
                variables=variables,
                account_name=account_name,
                task_name=task_name,
                match_action=match_action,
            )

        action_timeout = timeout or _read_positive_float_env(
            "KEYWORD_MONITOR_CONTINUE_ACTION_TIMEOUT", DEFAULT_CONTINUE_TIMEOUT, 1.0
        )
        deadline = time.perf_counter() + action_timeout
        limit = _read_positive_int_env(
            "KEYWORD_MONITOR_CONTINUE_HISTORY_LIMIT", DEFAULT_HISTORY_LIMIT, 1
        )

        while time.perf_counter() < deadline:
            recent_messages = await self._recent_messages(
                client,
                target_chat_id,
                target_thread_id,
                limit,
            )
            usable_messages = [
                message
                for message in recent_messages
                if self._message_supports_action(message, action_id)
            ]

            for recent_message in usable_messages:
                if action_id == 3:
                    before_state = _messages_state(recent_messages)
                    clicked, matched = await self._click_keyboard_by_text_result(
                        client,
                        target_chat_id,
                        target_thread_id,
                        action,
                        recent_message,
                    )
                    if clicked:
                        return True
                    if matched:
                        follow_timeout = min(6.0, action_timeout)
                        if next_action is not None:
                            if _is_immediate_continue_action(next_action):
                                if await self._wait_for_chat_advance(
                                    client,
                                    target_chat_id,
                                    target_thread_id,
                                    before_state,
                                    limit=limit,
                                    timeout=follow_timeout,
                                ):
                                    logger.info(
                                        "Keyword monitor button click returned false, "
                                        "but chat advanced before immediate next action; continuing"
                                    )
                                    return True
                                logger.warning(
                                    "Keyword monitor button click returned false, "
                                    "and chat did not advance before immediate next action"
                                )
                                return False
                            if await self._wait_for_continue_action_candidate(
                                client,
                                target_chat_id,
                                target_thread_id,
                                next_action,
                                before_state,
                                limit=limit,
                                timeout=follow_timeout,
                            ):
                                logger.info(
                                    "Keyword monitor button click returned false, "
                                    "but next action is ready; continuing"
                                )
                                return True
                            logger.warning(
                                "Keyword monitor button click returned false, "
                                "and next action is not ready"
                            )
                            return False
                        if await self._wait_for_terminal_success(
                            client,
                            target_chat_id,
                            target_thread_id,
                            before_state,
                            limit=limit,
                            timeout=follow_timeout,
                        ):
                            logger.info(
                                "Keyword monitor button click returned false, "
                                "but terminal success text was detected"
                            )
                            return True
                        logger.warning(
                            "Keyword monitor button click returned false, "
                            "and no terminal success text was detected"
                        )
                        return False
                    continue

                if await self._execute_ai_action(
                    client,
                    target_chat_id,
                    target_thread_id,
                    action,
                    recent_message,
                ):
                    return True

            await asyncio.sleep(0.5)

        logger.warning(
            "Keyword monitor continue action %s timed out waiting for usable message in %r",
            action_id,
            target_chat_id,
        )
        return False

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
            rendered_actions = [
                _render_action_templates(raw_action, variables)
                for raw_action in continue_actions
            ]
            self._append_rule_log(
                rule,
                f"开始执行关键词命中后续动作：{len(rendered_actions)} 步，目标 Chat={target_chat_id}"
                + (
                    f"，话题ID={target_thread_id}"
                    if target_thread_id is not None
                    else ""
                ),
            )
            for index, action in enumerate(rendered_actions, start=1):
                next_action = (
                    rendered_actions[index]
                    if index < len(rendered_actions)
                    else None
                )
                action_desc = self._describe_continue_action(action)
                action_delay = _resolve_action_delay(
                    action,
                    interval if index > 1 else 0.0,
                )
                if action_delay > 0:
                    self._append_rule_log(
                        rule,
                        f"后续动作 {index}/{len(rendered_actions)} 等待 {action_delay:g} 秒后执行：{action_desc}",
                    )
                    await asyncio.sleep(action_delay)
                self._append_rule_log(
                    rule,
                    f"后续动作 {index}/{len(rendered_actions)} 开始：{action_desc}",
                )
                # Bot 批量命令需要更长超时：间隔 × 上限 + 缓冲
                action_timeout = timeout
                try:
                    if int(action.get("action")) == 9:
                        send_interval = _as_non_negative_float(
                            action.get("send_interval"), DEFAULT_BOT_CMD_INTERVAL
                        )
                        max_batch = _as_positive_int(
                            action.get("max_batch"),
                            DEFAULT_BOT_CMD_MAX_BATCH,
                            minimum=1,
                        )
                        action_timeout = max(
                            timeout, send_interval * max_batch + 15.0
                        )
                except (TypeError, ValueError):
                    action_timeout = timeout
                try:
                    result = await asyncio.wait_for(
                        self._execute_continue_action(
                            client,
                            target_chat_id,
                            target_thread_id,
                            action,
                            timeout=action_timeout,
                            next_action=next_action,
                            source_message=message,
                            variables=variables,
                            account_name=account_name,
                            task_name=rule.task_name,
                            match_action=rule.action,
                        ),
                        timeout=action_timeout + 1,
                    )
                except Exception as exc:
                    is_terminal = isinstance(exc, TerminalAIActionError)
                    log_level = logging.ERROR if is_terminal else logging.WARNING
                    logger.log(
                        log_level,
                        "Keyword monitor continue action %s/%s %s for task %s: %s",
                        index,
                        len(continue_actions),
                        "terminal AI failure" if is_terminal else "failed",
                        rule.task_name,
                        exc,
                        exc_info=True,
                    )
                    self._append_rule_log(
                        rule,
                        f"后续动作 {index}/{len(rendered_actions)} {'AI 调用不可恢复失败' if is_terminal else '执行异常'}：{exc}",
                    )
                    return
                if not result:
                    logger.warning(
                        "Keyword monitor continue action %s/%s returned false for task %s",
                        index,
                        len(continue_actions),
                        rule.task_name,
                    )
                    self._append_rule_log(
                        rule,
                        f"后续动作 {index}/{len(rendered_actions)} 执行失败：{action_desc}",
                    )
                    return
                self._append_rule_log(
                    rule,
                    f"后续动作 {index}/{len(rendered_actions)} 执行成功：{action_desc}",
                )
            self._append_rule_log(rule, "关键词命中后续动作全部执行完成")

    async def _on_message(self, account_name: str, client: Any, message: Message) -> None:
        try:
            from backend.services.config import get_config_service

            text = _message_text(message)
            if not text:
                return
            message_thread_id = self._message_thread_id(message)
            same_chat_rules = [
                rule
                for rule in self._rules
                if rule.account_name == account_name
                and rule.chat_id == message.chat.id
            ]
            if not same_chat_rules:
                return
            is_self_message = _message_is_self(message)
            matched_rules = [
                rule
                for rule in same_chat_rules
                if _message_matches_thread(message, rule.message_thread_id)
                and _message_matches_sender(message, rule.sender_filter)
                and not (is_self_message and _action_ignore_self(rule.action))
                and _action_in_active_time_window(rule.action)
            ]
            if not matched_rules:
                thread_candidates = _message_thread_candidates(message)
                for rule in same_chat_rules:
                    if rule.message_thread_id is None:
                        continue
                    if not self._should_log_rule_event(
                        rule,
                        "thread_mismatch",
                        interval_seconds=45.0,
                    ):
                        continue
                    self._append_rule_log(
                        rule,
                        "监听收到消息但话题ID不匹配："
                        f"配置={rule.message_thread_id}，"
                        f"消息={message_thread_id if message_thread_id is not None else '-'}，"
                        f"候选={thread_candidates or ['-']}",
                        active=True,
                    )
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
                all_matched = _match_all_keyword_values(rule.action, text)
                matched = all_matched[0] if all_matched else None
                if not matched:
                    if self._should_log_rule_event(
                        rule,
                        "keyword_miss",
                        interval_seconds=60.0,
                    ):
                        text_preview = text.replace("\n", " ").strip()
                        if len(text_preview) > 120:
                            text_preview = text_preview[:117] + "..."
                        self._append_rule_log(
                            rule,
                            f"监听收到消息但关键词未命中：消息={text_preview}",
                            active=True,
                        )
                    continue
                text_preview = text.replace("\n", " ").strip()
                if len(text_preview) > 160:
                    text_preview = text_preview[:157] + "..."
                capture_display = matched
                if len(all_matched) > 1:
                    capture_display = f"{','.join(all_matched[:8])}" + (
                        f"…(+{len(all_matched) - 8})" if len(all_matched) > 8 else ""
                    )
                    capture_display = f"{capture_display}（共{len(all_matched)}个）"
                self._append_rule_log(
                    rule,
                    f"关键词命中：Chat={chat_title}({getattr(message.chat, 'id', '')})，"
                    f"消息ID={getattr(message, 'id', '')}，捕获值={capture_display}，消息={text_preview}",
                    active=True,
                )
                body_lines = [
                    f"Task: {rule.task_name}",
                    f"Chat: {chat_title}",
                    f"Keyword: {matched}",
                ]
                if len(all_matched) > 1:
                    body_lines.append(f"Keywords: {', '.join(all_matched[:20])}")
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
                continue_enabled = push_channel == "continue"
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
                        await self._call_client_with_retry(
                            client,
                            lambda _forward_chat_id=forward_chat_id, _forward_payload=forward_payload[:3900], _forward_kwargs=dict(forward_kwargs): client.send_message(
                                _forward_chat_id,
                                _forward_payload,
                                **_forward_kwargs,
                            ),
                            operation=f"keyword monitor forward match {forward_chat_id}",
                        )
                        self._append_rule_log(
                            rule,
                            f"关键词命中消息已转发：目标 Chat={forward_chat_id}"
                            + (
                                f"，话题ID={forward_thread_id}"
                                if forward_thread_id is not None
                                else ""
                            ),
                        )
                    except Exception as exc:
                        logger.warning(
                            "Failed to forward keyword match to %r: %s",
                            forward_chat_id,
                            exc,
                        )
                        self._append_rule_log(
                            rule,
                            f"关键词命中消息转发失败：目标 Chat={forward_chat_id}，错误={exc}",
                        )

                if push_channel not in {"forward", "continue"}:
                    push_settings = dict(global_settings)
                    push_settings["keyword_monitor_push_channel"] = push_channel
                    push_settings["keyword_monitor_bark_url"] = rule.action.get("bark_url")
                    push_settings["keyword_monitor_custom_url"] = rule.action.get(
                        "custom_url"
                    )
                    push_settings["keyword_monitor_server_chan_send_key"] = (
                        rule.action.get("server_chan_send_key")
                        or rule.action.get("server_chan_sendkey")
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
                    self._append_rule_log(
                        rule,
                        f"关键词命中通知已处理：推送方式={push_channel}",
                    )
                if continue_enabled:
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
            from tg_signer.core import (
                _CLIENT_INSTANCES,
                close_client_by_name,
                get_client,
            )

            rules = self._load_rules()
            key = self._rules_key(rules)
            if key == self._active_key and self._handlers_are_active_for(rules):
                for rule in rules:
                    if not self._task_logs.get(
                        self._task_key(rule.account_name, rule.task_name)
                    ):
                        self._append_rule_log(
                            rule,
                            f"关键词后台监听运行中：{self._describe_rule(rule)}",
                            active=True,
                        )
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
            started_accounts: set[str] = set()
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
                        for rule in account_rules:
                            self._append_rule_log(
                                rule,
                                "关键词后台监听启动失败：账号没有可用 session_string",
                                active=False,
                            )
                        continue

                lock = get_account_lock(account_name)
                async with lock:
                    client_key = str(session_dir.joinpath(account_name).resolve())
                    existing = _CLIENT_INSTANCES.get(client_key)
                    if (
                        existing is not None
                        and getattr(existing, "_tg_signpulse_no_updates", None) is True
                    ):
                        logger.info(
                            "Recreating keyword monitor client for %s with updates enabled",
                            account_name,
                        )
                        await close_client_by_name(account_name, workdir=session_dir)

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

                    async def handler(
                        client, message: Message, name: str = account_name
                    ) -> None:
                        await self._on_message(name, client, message)

                    handler_ref = client.add_handler(
                        MessageHandler(
                            handler,
                            filters.chat(chat_ids) & (filters.text | filters.caption),
                        )
                    )
                    try:
                        await client.__aenter__()
                    except Exception:
                        try:
                            client.remove_handler(*handler_ref)
                        except Exception:
                            pass
                        logger.warning(
                            "Keyword monitor failed to start for %s",
                            account_name,
                            exc_info=True,
                        )
                        for rule in account_rules:
                            self._append_rule_log(
                                rule,
                                "关键词后台监听启动失败：Telegram client 启动失败，请检查账号登录状态、代理或 API 配置",
                                active=False,
                            )
                        continue

                    self._handler_refs.append((account_name, client, handler_ref))
                    started_accounts.add(account_name)
                    logger.info(
                        "Keyword monitor started for %s in %s", account_name, chat_ids
                    )
                    for rule in account_rules:
                        self._append_rule_log(
                            rule,
                            f"关键词后台监听已启动：{self._describe_rule(rule)}",
                            active=True,
                        )

            self._active_key = key if started_accounts == set(accounts) else ""

    async def stop(self) -> None:
        for rule in self._rules:
            self._append_rule_log(
                rule,
                "关键词后台监听已停止",
                active=False,
            )
        for account_name, client, handler_ref in self._handler_refs:
            lock = get_account_lock(account_name)
            async with lock:
                try:
                    client.remove_handler(*handler_ref)
                except Exception:
                    pass
                try:
                    await client.__aexit__(None, None, None)
                except Exception:
                    pass
        self._handler_refs = []
        self._rules = []
        self._active_key = ""
        self._bot_cmd_last_sent.clear()


_keyword_monitor_service: Optional[KeywordMonitorService] = None


def get_keyword_monitor_service() -> KeywordMonitorService:
    global _keyword_monitor_service
    if _keyword_monitor_service is None:
        _keyword_monitor_service = KeywordMonitorService()
    return _keyword_monitor_service

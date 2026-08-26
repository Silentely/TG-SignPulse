"""关键词监控服务（规则见 rules.py，继续动作执行见 continue_actions.py）。"""
# 规则工具通过 rules.__all__ + star import 注入；动态名称对静态检查不可见
# ruff: noqa: F401, F403, F405, F821
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Dict, List, Optional, Union

# 确保 rules 中以下划线开头的符号也可通过 star import 获得
import backend.services.keyword_monitor.rules as _km_rules
from backend.services.keyword_monitor.continue_actions import (
    continue_actions,
    describe_continue_action,
    execute_bot_link_action,
    execute_continue_actions,
    message_supports_action,
)
from backend.services.keyword_monitor.rules import *  # noqa: F403
from backend.services.push_notifications import send_keyword_push
from backend.utils.account_locks import get_account_lock
from backend.utils.atomic_io import write_json_atomic
from backend.utils.proxy import build_proxy_dict
from backend.utils.tg_session import (
    get_session_mode,
    load_account_session_string,
    resolve_effective_proxy,
)
from backend.utils.time import utc_now_iso_z_seconds, utc_now_naive
from tg_signer.compat import (
    Message,
    MessageHandler,
    call_with_retry,
    filters,
)
from tg_signer.log_utils import safe_exception_summary

for _name, _val in vars(_km_rules).items():
    if _name.startswith("__"):
        continue
    globals().setdefault(_name, _val)
del _name, _val

# 规则事件日志节流间隔（秒）：同一事件在间隔内只记录一次，避免高频消息刷屏
# 话题不匹配提示的节流周期
LOG_THROTTLE_THREAD_MISMATCH_SECONDS = 45.0
# 关键词未命中提示的节流周期（命中路径的节流见 _should_log_rule_event 默认值）
LOG_THROTTLE_KEYWORD_MISS_SECONDS = 60.0

# 重启去重状态文件：按 (账号, 会话) 记录已处理的最大消息 ID，
# 服务重启/重连后 Telegram 补投的旧消息据此跳过，避免重复命中与推送
_SEEN_STATE_FILENAME = "seen.json"
_SEEN_PERSIST_INTERVAL = 30.0


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
        self._seen: dict[str, int] = {}
        self._seen_baseline: dict[str, int] = {}
        self._seen_window: dict[str, set[int]] = {}
        self._seen_dirty = False
        self._last_seen_persist = 0.0

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
        return await call_with_retry(
            callback,
            operation=operation,
            max_retries=max_retries,
            log=lambda level, msg: logger.warning("%s", msg) if level == "WARNING" else logger.info("%s", msg),
            reconnect=lambda: self._ensure_client_ready(client),
        )

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
        # 统一 UTC：行前缀保持前端可剥离的 "%Y-%m-%d %H:%M:%S" 形态，
        # updated_at 用 Z 后缀 ISO，供前端 new Date() 按 UTC 正确解析
        timestamp = utc_now_naive().strftime("%Y-%m-%d %H:%M:%S")
        logs = self._task_logs.setdefault(key, [])
        logs.append(f"{timestamp} - {line}")
        if len(logs) > 1000:
            del logs[:-1000]

        status = self._task_status.setdefault(key, {})
        status["updated_at"] = utc_now_iso_z_seconds()
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
        """薄转发：继续动作描述（实现见 continue_actions.describe_continue_action）。"""
        return describe_continue_action(action)

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
        """薄转发：继续动作过滤（描述/执行共用，实现见 continue_actions.continue_actions）。"""
        return continue_actions(action)

    def _message_supports_action(self, message: Message, action_id: int) -> bool:
        """薄转发：消息是否支持某继续动作（实现见 continue_actions.message_supports_action）。"""
        return message_supports_action(message, action_id)

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
        """薄转发：Bot 命令触发动作（实现见 continue_actions.execute_bot_link_action）。"""
        return await execute_bot_link_action(
            self,
            client,
            target_chat_id,
            target_thread_id,
            action,
            source_message=source_message,
            variables=variables,
            account_name=account_name,
            task_name=task_name,
            match_action=match_action,
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
        """薄转发：继续动作执行入口（实现见 continue_actions.execute_continue_actions）。"""
        await execute_continue_actions(
            self,
            account_name=account_name,
            client=client,
            rule=rule,
            message=message,
            variables=variables,
        )

    def _seen_key(self, account_name: str, chat_id: Union[int, str]) -> str:
        return f"{account_name}:{chat_id}"

    def _load_seen_state(self) -> None:
        """重启时加载已处理消息水位；文件缺失或损坏时从空开始。"""
        path = settings.resolve_workdir() / "keyword_monitor" / _SEEN_STATE_FILENAME
        loaded: dict[str, int] = {}
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for key, value in raw.items():
                        if (
                            isinstance(key, str)
                            and isinstance(value, int)
                            and not isinstance(value, bool)
                            and value > 0
                        ):
                            loaded[key] = value
            except (OSError, ValueError) as exc:
                logger.warning("加载关键词监听去重水位失败: %s", exc)
        self._seen = loaded
        self._seen_baseline = dict(loaded)
        self._seen_window = {k: set() for k in loaded}
        self._seen_dirty = False
        self._last_seen_persist = time.monotonic()

    def _persist_seen_state(self) -> None:
        """原子写盘已处理水位（调用方确保有变更）。"""
        path = settings.resolve_workdir() / "keyword_monitor" / _SEEN_STATE_FILENAME
        try:
            write_json_atomic(path, self._seen)
            self._last_seen_persist = time.monotonic()
            self._seen_dirty = False
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("持久化关键词监听去重水位失败: %s", exc)

    def _maybe_persist_seen_state(self, *, force: bool = False) -> None:
        if not self._seen_dirty:
            return
        if not force and time.monotonic() - self._last_seen_persist < _SEEN_PERSIST_INTERVAL:
            return
        self._persist_seen_state()

    def _is_seen_message(
        self,
        account_name: str,
        chat_id: Union[int, str],
        message_id: Optional[int],
    ) -> bool:
        """重启去重与滑动窗口去重：
        1. 若 message_id <= 重启前基准水位线，说明是重启/重连补投的历史旧消息，直接跳过；
        2. 若 message_id 在当前运行周期的已处理集合中，说明重复到达，直接跳过；
        3. 否则记录到最近已处理窗口并更新最大水位线。
        """
        if message_id is None:
            return False
        key = self._seen_key(account_name, chat_id)
        baseline = self._seen_baseline.get(key, 0)
        if message_id <= baseline:
            return True

        seen_set = self._seen_window.setdefault(key, set())
        if message_id in seen_set:
            return True

        seen_set.add(message_id)
        if len(seen_set) > 300:
            keep = sorted(seen_set, reverse=True)[:200]
            self._seen_window[key] = set(keep)

        current_max = self._seen.get(key, 0)
        if message_id > current_max:
            self._seen[key] = message_id
            self._seen_dirty = True
            self._maybe_persist_seen_state()

        return False

    async def _on_message(self, account_name: str, client: Any, message: Message) -> None:
        try:
            from backend.services.config import get_config_service

            text = _message_text(message)
            if not text:
                return
            chat_id = getattr(message.chat, "id", None)
            if chat_id is None:
                return
            # 重启/重连后 Telegram 会补投停机期间的旧消息，按已处理水位跳过
            if self._is_seen_message(account_name, chat_id, getattr(message, "id", None)):
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
                        interval_seconds=LOG_THROTTLE_THREAD_MISMATCH_SECONDS,
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
                        interval_seconds=LOG_THROTTLE_KEYWORD_MISS_SECONDS,
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
                # 结构化命中记录（列表 / 分组 / 导出）
                try:
                    from backend.services.keyword_monitor.hits import record_keyword_hit

                    record_keyword_hit(
                        account_name=account_name,
                        task_name=rule.task_name,
                        chat_id=getattr(message.chat, "id", None),
                        chat_title=chat_title,
                        keyword=matched,
                        keywords=all_matched,
                        message_id=getattr(message, "id", None),
                        message_text=text,
                        sender=sender,
                        url=url,
                        push_channel=str(
                            rule.action.get("push_channel") or "telegram"
                        ).strip(),
                        message_thread_id=message_thread_id,
                    )
                except Exception as hit_exc:
                    logger.warning("持久化关键词命中记录失败: %s", hit_exc)
                # Bark/Server酱 等无结构化字段的通道需要完整上下文：
                # 多账号用户据此区分来源，时间戳便于回溯
                body_lines = [
                    f"账号: {account_name}",
                    f"任务: {rule.task_name}",
                    f"会话: {chat_title}",
                    f"关键词: {matched}",
                ]
                if len(all_matched) > 1:
                    body_lines.append(
                        f"关键词(共{len(all_matched)}个): {', '.join(all_matched[:20])}"
                    )
                if sender:
                    body_lines.append(f"发送者: {sender}")
                body_lines.append(f"时间 (UTC): {utc_now_iso_z_seconds()}")
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
                # 分派：转发 / 继续动作 / 推送三者互斥，按配置通道分发到对应 handler
                if push_channel == "forward":
                    await self._handle_forward(
                        rule,
                        client,
                        message,
                        forward_text=forward_text,
                        url=url,
                    )
                elif push_channel == "continue":
                    await self._handle_continue(
                        rule,
                        client,
                        message,
                        account_name=account_name,
                        variables=variables,
                    )
                else:
                    await self._handle_push(
                        rule,
                        account_name,
                        message,
                        forward_text=forward_text,
                        text=text,
                        matched=matched,
                        url=url,
                        sender=sender,
                        chat_title=chat_title,
                        push_channel=push_channel,
                        global_settings=global_settings,
                    )
        except Exception as exc:
            logger.warning("关键词监听处理失败: %s", exc, exc_info=True)

    async def _handle_forward(
        self,
        rule: KeywordMonitorRule,
        client: Any,
        message: Message,
        *,
        forward_text: str,
        url: str,
    ) -> None:
        """转发通道：把命中消息文本转发到配置的目标 Chat。"""
        forward_chat_id = _parse_forward_chat_id(rule.action.get("forward_chat_id"))
        if forward_chat_id is None:
            return
        try:
            forward_kwargs: dict[str, Any] = {}
            forward_thread_id = _as_int_or_none(
                rule.action.get("forward_message_thread_id")
            )
            if forward_thread_id is not None:
                forward_kwargs["message_thread_id"] = forward_thread_id
            forward_payload = forward_text
            if url:
                forward_payload += f"\n\n链接: {url}"
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
                "关键词命中消息转发失败 %r: %s",
                forward_chat_id,
                exc,
            )
            self._append_rule_log(
                rule,
                f"关键词命中消息转发失败：目标 Chat={forward_chat_id}，原因：{safe_exception_summary(exc, 120)}",
            )

    async def _handle_push(
        self,
        rule: KeywordMonitorRule,
        account_name: str,
        message: Message,
        *,
        forward_text: str,
        text: str,
        matched: str,
        url: str,
        sender: str,
        chat_title: str,
        push_channel: str,
        global_settings: dict[str, Any],
    ) -> None:
        """推送通道：按规则配置的通道（telegram/bark/custom_url/server_chan）发送通知。"""
        push_settings = dict(global_settings)
        push_settings["keyword_monitor_push_channel"] = push_channel
        push_settings["keyword_monitor_bark_url"] = rule.action.get("bark_url")
        push_settings["keyword_monitor_custom_url"] = rule.action.get("custom_url")
        push_settings["keyword_monitor_server_chan_send_key"] = (
            rule.action.get("server_chan_send_key")
            or rule.action.get("server_chan_sendkey")
        )
        try:
            await send_keyword_push(
                push_settings,
                {
                    "title": "TG-SignPulse 关键词命中",
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
        except Exception as exc:
            # 推送失败不冒泡：命中记录已持久化，失败仅记为规则日志与告警，
            # 避免单条推送抖动把整个监听处理误判为失败
            logger.warning(
                "关键词命中通知推送失败（推送方式=%s）: %s",
                push_channel,
                exc,
            )
            self._append_rule_log(
                rule,
                f"关键词命中通知推送失败：推送方式={push_channel}，原因：{safe_exception_summary(exc, 120)}",
            )
            return
        self._append_rule_log(
            rule,
            f"关键词命中通知已处理：推送方式={push_channel}",
        )

    async def _handle_continue(
        self,
        rule: KeywordMonitorRule,
        client: Any,
        message: Message,
        *,
        account_name: str,
        variables: Dict[str, str],
    ) -> None:
        """继续动作通道：命中后按规则顺序执行配置的后续动作。"""
        await self._execute_continue_actions(
            account_name=account_name,
            client=client,
            rule=rule,
            message=message,
            variables=variables,
        )

    def _prune_inactive_rule_state(self, rules: List[Any]) -> None:
        """按当前规则键集合裁剪内存日志/状态：删除的账号/任务不滞留。

        早退路径（规则键未变）也会调用，避免 `_task_logs`/`_task_status`/
        `_skip_log_times`/`_seen` 随账号/任务删除无限累积。
        """
        active_keys = {self._task_key(r.account_name, r.task_name) for r in rules}
        for store in (self._task_logs, self._task_status):
            for key in list(store.keys()):
                if key not in active_keys:
                    store.pop(key, None)
        for key in list(self._skip_log_times.keys()):
            if (key[0], key[1]) not in active_keys:
                self._skip_log_times.pop(key, None)
        # 去重水位（seen.json 持久态）按规则账号集合裁剪，账号删除后不再累积
        active_accounts = {str(r.account_name or "").strip() for r in rules}
        pruned_seen = False
        for key in list(self._seen.keys()):
            account = key.split(":", 1)[0] if ":" in key else key
            if account not in active_accounts:
                self._seen.pop(key, None)
                self._seen_baseline.pop(key, None)
                self._seen_window.pop(key, None)
                pruned_seen = True
        if pruned_seen:
            self._seen_dirty = True

    async def restart_from_tasks(self) -> None:
        async with self._lock:
            from backend.services.config import get_config_service
            from backend.services.telegram.credentials import (
                resolve_telegram_api_credentials,
            )
            from tg_signer.core import (
                _CLIENT_INSTANCES,
                close_client_by_name,
                get_client,
            )

            rules = self._load_rules()
            # 先按目标规则集合清理滞留状态（早退与重建路径均覆盖）
            self._prune_inactive_rule_state(rules)
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

            # 重启后加载已处理水位，跳过补投的旧消息
            self._load_seen_state()

            session_dir = settings.resolve_session_dir()
            global_settings = get_config_service().get_global_settings()
            tg_config = get_config_service().get_telegram_config()
            try:
                api_id, api_hash = resolve_telegram_api_credentials(
                    tg_config,
                    env_api_id=os.getenv("TG_API_ID"),
                    env_api_hash=os.getenv("TG_API_HASH"),
                )
            except ValueError:
                # 监控启动不强制校验凭据，缺失时由后续客户端创建报错
                api_id = None
                api_hash = None

            accounts = sorted({rule.account_name for rule in rules})
            started_accounts: set[str] = set()
            for account_name in accounts:
                account_rules = [rule for rule in rules if rule.account_name == account_name]
                chat_ids = sorted({rule.chat_id for rule in account_rules})
                proxy_value = resolve_effective_proxy(
                    account_name,
                    global_proxy=global_settings.get("global_proxy"),
                )
                proxy = build_proxy_dict(proxy_value) if proxy_value else None

                session_mode = get_session_mode()
                session_string = load_account_session_string(
                    account_name, session_dir=session_dir, session_mode=session_mode
                )
                in_memory = False
                if session_mode == "string":
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
                            "关键词监听客户端需启用消息更新，正在重建: account=%s",
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
                            "关键词监听启动失败 account=%s",
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
                        "关键词监听已启动 account=%s chats=%s", account_name, chat_ids
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
        # 停机前落盘已处理水位，供下次启动去重
        self._maybe_persist_seen_state(force=True)


_keyword_monitor_service: Optional[KeywordMonitorService] = None


def get_keyword_monitor_service() -> KeywordMonitorService:
    global _keyword_monitor_service
    if _keyword_monitor_service is None:
        _keyword_monitor_service = KeywordMonitorService()
    return _keyword_monitor_service

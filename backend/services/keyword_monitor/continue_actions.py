"""关键词监听"继续动作"执行族。

从 runtime.KeywordMonitorService 迁出的继续动作执行逻辑，全部为模块级函数：
- 需要访问服务实例状态（日志、重试、限频映射、AI 工具缓存）的函数，通过首参
  ``service`` 传入，避免拆出独立类后与 runtime 互相持有引用；
- 纯函数直接独立为模块函数，不依赖任何服务状态。

保持 runtime.KeywordMonitorService 原调用语义与日志输出完全一致。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Union

from backend.core.config import get_settings
from backend.services.keyword_monitor.rules import (
    _BOT_CMD_MAX_BATCH_RISK_HINT,
    DEFAULT_BOT_CMD_INTERVAL,
    DEFAULT_BOT_CMD_MAX_BATCH,
    DEFAULT_COMMAND_PREFIX,
    DEFAULT_CONTINUE_TIMEOUT,
    DEFAULT_HISTORY_LIMIT,
    KeywordMonitorRule,
    TerminalAIActionError,
    _as_bool,
    _as_int_or_none,
    _as_non_negative_float,
    _as_positive_int,
    _extract_tg_start_links,
    _is_callback_data_invalid,
    _is_immediate_continue_action,
    _match_all_keyword_values,
    _message_has_terminal_success_text,
    _message_matches_thread,
    _message_supports_continue_action,
    _message_text,
    _message_thread_candidates,
    _messages_state,
    _normalize_bot_username,
    _parse_forward_chat_id,
    _render_action_templates,
    _render_template,
    _resolve_action_delay,
)
from backend.utils.account_locks import get_account_lock
from tg_signer.compat import (
    Message,
    button_text_matches,
    clean_text_for_match,
    collect_clickable_buttons,
    errors,
)
from tg_signer.log_utils import (
    safe_ai_request_meta,
    safe_ai_result_meta,
    safe_text_preview,
)
from tg_signer.utils import read_positive_float_env, read_positive_int_env

# 与 rules/runtime 共用同一 logger 单例，测试 patch backend.services.keyword_monitor.logger 生效
logger = logging.getLogger("backend.keyword_monitor")
settings = get_settings()


def prune_bot_cmd_rate_map(rate_map: Dict[str, float]) -> None:
    """限频映射清扫：超过 1000 条时剔除 5 分钟前的陈旧记录，防内存缓增。"""
    if len(rate_map) <= 1000:
        return
    cutoff = time.monotonic() - 300.0
    stale_keys = [key for key, sent_at in rate_map.items() if sent_at <= cutoff]
    for key in stale_keys:
        rate_map.pop(key, None)


async def await_bot_cmd_slot(rate_map: Dict[str, float], rate_key: str, interval: float) -> None:
    """等待直到距离上次发送已满足间隔，避免硬跳过批量码。"""
    if interval <= 0:
        rate_map[rate_key] = time.monotonic()
        prune_bot_cmd_rate_map(rate_map)
        return
    now = time.monotonic()
    last_sent = rate_map.get(rate_key, 0.0)
    wait_seconds = interval - (now - last_sent)
    if wait_seconds > 0:
        logger.debug(
            "Bot 命令间隔等待：key=%s wait=%.2fs interval=%.2fs",
            rate_key,
            wait_seconds,
            interval,
        )
        await asyncio.sleep(wait_seconds)
    rate_map[rate_key] = time.monotonic()
    prune_bot_cmd_rate_map(rate_map)


def collect_bot_cmd_jobs(
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


def continue_actions(action: Dict[str, Any]) -> list[Dict[str, Any]]:
    """过滤出受支持的继续动作列表（action_id ∈ 1/2/3/4/5/6/7/9）。"""
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


def continue_target(
    action: Dict[str, Any], source_message: Message
) -> tuple[Union[int, str], Optional[int]]:
    """计算继续动作的目标 Chat 与话题 ID。"""
    target_chat_id = _parse_forward_chat_id(action.get("continue_chat_id"))
    if target_chat_id is None:
        target_chat_id = source_message.chat.id

    configured_thread_id = _as_int_or_none(action.get("continue_message_thread_id"))
    if configured_thread_id is not None:
        return target_chat_id, configured_thread_id

    if target_chat_id == source_message.chat.id:
        candidates = _message_thread_candidates(source_message)
        return target_chat_id, candidates[0] if candidates else None
    return target_chat_id, None


def continue_interval(action: Dict[str, Any]) -> float:
    """读取继续动作之间的间隔秒数，非法值回退 1 秒。"""
    try:
        return max(float(action.get("continue_action_interval", 1)), 0.0)
    except (TypeError, ValueError):
        return 1.0


def describe_continue_action(action: Dict[str, Any]) -> str:
    """描述单个继续动作，用于任务日志展示。"""
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


def get_ai_tools(service: Any):
    """读取/重建 AI 工具实例；OpenAI 配置缺失时抛错（调用方视为不可恢复）。"""
    from tg_signer.ai_tools import AITools, OpenAIConfigManager, ai_cfg_signature

    for workdir in (settings.resolve_session_dir(), settings.resolve_workdir()):
        cfg = OpenAIConfigManager(workdir).load_config()
        if cfg:
            signature = ai_cfg_signature(cfg)
            if service._ai_tools is None or service._ai_cfg_signature != signature:
                service._ai_tools = AITools(cfg)
                service._ai_cfg_signature = signature
            return service._ai_tools
    raise RuntimeError("OpenAI config is required for keyword monitor AI actions")


async def warm_chat(client: Any, chat_id: Union[int, str]) -> None:
    """预热目标会话，失败仅记录调试日志不中断。"""
    try:
        await client.get_chat(chat_id)
    except Exception as exc:
        logger.debug("关键词监听会话预热失败 %r: %s", chat_id, exc)


async def request_callback_answer(
    service: Any,
    client: Any,
    chat_id: Union[int, str],
    message_id: int,
    callback_data: Union[str, bytes],
) -> bool:
    """请求 inline 按钮回执，FloodWait 等待 / 瞬态错误重连重试。"""
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
                logger.warning("关键词监听回调触发 FloodWait 失败: %s", exc)
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
                await service._ensure_client_ready(client)
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
            logger.warning("关键词监听回调无法确认: %s", exc)
            return False
    return False


async def click_inline_button(
    service: Any, client: Any, message: Message, button: Any
) -> bool:
    """点击 inline 按钮：优先走回执，回退 Message.click 按文本点击。"""
    callback_data = getattr(button, "callback_data", None)
    if callback_data is not None:
        if await request_callback_answer(
            service, client, message.chat.id, message.id, callback_data
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


async def click_keyboard_by_text_result(
    service: Any,
    client: Any,
    target_chat_id: Union[int, str],
    target_thread_id: Optional[int],
    action: Dict[str, Any],
    message: Message,
) -> tuple[bool, bool]:
    """按目标文本匹配并点击按钮。

    键盘遍历复用 tg_signer.compat.collect_clickable_buttons 的统一提取，
    消除 runtime/rules 各自手写键盘遍历的重复。返回 (是否点击成功, 是否命中目标按钮)。
    """
    target_text = clean_text_for_match(str(action.get("text") or ""))
    if not target_text:
        return False, False

    for button_kind, button, button_text in collect_clickable_buttons(message):
        if not button_text_matches(target_text, clean_text_for_match(button_text)):
            continue
        if button_kind == "inline":
            return await click_inline_button(service, client, message, button), True
        # 回复键盘（普通键盘）：直接发送按钮文本等效点击
        kwargs: Dict[str, Any] = {}
        if target_thread_id is not None:
            kwargs["message_thread_id"] = target_thread_id
        await service._call_client_with_retry(
            client,
            lambda _button_text=button_text, _kwargs=dict(kwargs): client.send_message(
                target_chat_id, _button_text, **_kwargs
            ),
            operation=f"keyword monitor send reply keyboard {target_chat_id}",
        )
        return True, True
    return False, False


async def click_keyboard_by_text(
    service: Any,
    client: Any,
    target_chat_id: Union[int, str],
    target_thread_id: Optional[int],
    action: Dict[str, Any],
    message: Message,
) -> bool:
    """按目标文本点击按钮，仅返回是否点击成功。"""
    clicked, _matched = await click_keyboard_by_text_result(
        service,
        client,
        target_chat_id,
        target_thread_id,
        action,
        message,
    )
    return clicked


async def load_recent_messages(
    service: Any,
    client: Any,
    chat_id: Union[int, str],
    thread_id: Optional[int],
    limit: int,
) -> list[Message]:
    """拉取目标会话最近消息（带重试），并过滤话题不匹配的消息。"""

    async def _load_messages() -> list[Message]:
        messages: list[Message] = []
        async for message in client.get_chat_history(chat_id, limit=limit):
            if _message_matches_thread(message, thread_id):
                messages.append(message)
        return messages

    return await service._call_client_with_retry(
        client,
        _load_messages,
        operation=f"keyword monitor get_chat_history {chat_id}",
    )


def message_supports_action(message: Message, action_id: int) -> bool:
    """消息是否支持指定继续动作。

    4/5/6/7 复用 rules._message_supports_continue_action 的共享判定；
    3（点击按钮）与 9（Bot 命令）为本模块特判，保持原 runtime 语义。
    """
    if action_id == 3:
        return bool(getattr(message, "reply_markup", None))
    if action_id == 9:
        return bool(message.text or message.caption)
    return _message_supports_continue_action(message, {"action": action_id})


async def wait_for_chat_advance(
    service: Any,
    client: Any,
    chat_id: Union[int, str],
    thread_id: Optional[int],
    before_state: dict[int, tuple[Any, ...]],
    *,
    limit: int,
    timeout: float,
) -> bool:
    """等待会话出现任一消息变化（用于点击后紧跟发送型动作的确认）。"""
    deadline = time.perf_counter() + max(timeout, 0.5)
    while time.perf_counter() < deadline:
        await asyncio.sleep(0.5)
        messages = await load_recent_messages(service, client, chat_id, thread_id, limit)
        current_state = _messages_state(messages)
        for message_id, marker in current_state.items():
            if before_state.get(message_id) != marker:
                return True
    return False


async def wait_for_continue_action_candidate(
    service: Any,
    client: Any,
    chat_id: Union[int, str],
    thread_id: Optional[int],
    action: Dict[str, Any],
    before_state: dict[int, tuple[Any, ...]],
    *,
    limit: int,
    timeout: float,
) -> bool:
    """等待出现适配后续动作的新消息。"""
    deadline = time.perf_counter() + max(timeout, 0.5)
    while time.perf_counter() < deadline:
        await asyncio.sleep(0.5)
        messages = await load_recent_messages(service, client, chat_id, thread_id, limit)
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


async def wait_for_terminal_success(
    service: Any,
    client: Any,
    chat_id: Union[int, str],
    thread_id: Optional[int],
    before_state: dict[int, tuple[Any, ...]],
    *,
    limit: int,
    timeout: float,
) -> bool:
    """等待出现含"成功"标记的终态消息。"""
    deadline = time.perf_counter() + max(timeout, 0.5)
    while time.perf_counter() < deadline:
        await asyncio.sleep(0.5)
        messages = await load_recent_messages(service, client, chat_id, thread_id, limit)
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


async def download_photo_bytes(client: Any, message: Message) -> bytes:
    """下载消息图片为字节串。"""
    image_buffer = await client.download_media(message.photo.file_id, in_memory=True)
    image_buffer.seek(0)
    return image_buffer.read()


async def _run_ai_call(
    target_chat_id: Union[int, str],
    *,
    ai_tools: Any,
    method: str,
    request_meta: Dict[str, Any],
    ai_call,
    error_label: str,
    result_meta,
) -> Optional[str]:
    """AI 调用样板收敛：请求日志→计时→调用→响应日志→异常包装→空检查。

    返回规范化后的答案文本；空答案返回 None。
    TerminalAIActionError 语义：AI 不可恢复错误必须继续抛，由上层
    execute_continue_actions 判定为终态失败，此处绝不吞掉。
    """
    model = ai_tools.default_model
    logger.info(
        "关键词监听 AI 请求 | chat=%s | %s",
        target_chat_id,
        safe_ai_request_meta(method=method, model=model, **request_meta),
    )
    _start = time.monotonic()
    try:
        answer = (await ai_call() or "").strip()
        _elapsed = (time.monotonic() - _start) * 1000
        logger.info(
            "关键词监听 AI 响应 | chat=%s | %s",
            target_chat_id,
            safe_ai_result_meta(
                method=method,
                model=model,
                elapsed_ms=_elapsed,
                **result_meta(answer),
            ),
        )
    except Exception as exc:
        _elapsed = (time.monotonic() - _start) * 1000
        logger.error(
            "关键词监听 AI 调用失败 | chat=%s | method=%s elapsed_ms=%.0f error=%s: %s",
            target_chat_id,
            method,
            _elapsed,
            type(exc).__name__,
            safe_text_preview(exc, 200),
        )
        raise TerminalAIActionError(f"{error_label}: {type(exc).__name__}") from exc
    if not answer:
        return None
    return answer


async def execute_ai_action(
    service: Any,
    client: Any,
    target_chat_id: Union[int, str],
    target_thread_id: Optional[int],
    action: Dict[str, Any],
    message: Message,
) -> bool:
    """执行 AI 类继续动作（action_id=4/5/6/7）。"""
    action_id = int(action.get("action"))
    ai_tools = get_ai_tools(service)
    kwargs: Dict[str, Any] = {}
    if target_thread_id is not None:
        kwargs["message_thread_id"] = target_thread_id

    if action_id == 5:
        query = (message.text or message.caption or "").strip()
        answer = await _run_ai_call(
            target_chat_id,
            ai_tools=ai_tools,
            method="calculate_problem",
            request_meta={"query_chars": len(query), "question_preview": query},
            ai_call=lambda: ai_tools.calculate_problem(
                query, system_prompt=action.get("ai_prompt")
            ),
            error_label="AI calculate_problem failed",
            result_meta=lambda a: {
                "response_chars": len(a),
                "selected_options": [a] if a else [],
            },
        )
        if answer is None:
            return False
        await service._call_client_with_retry(
            client,
            lambda: client.send_message(target_chat_id, answer, **kwargs),
            operation=f"keyword monitor AI text reply {target_chat_id}",
        )
        return True

    if action_id == 6:
        image_bytes = await download_photo_bytes(client, message)
        answer = await _run_ai_call(
            target_chat_id,
            ai_tools=ai_tools,
            method="extract_text_by_image",
            request_meta={"has_image": True, "image_bytes": len(image_bytes)},
            ai_call=lambda: ai_tools.extract_text_by_image(
                image_bytes, system_prompt=action.get("ai_prompt")
            ),
            error_label="AI extract_text_by_image failed",
            result_meta=lambda a: {
                "response_chars": len(a),
                "selected_options": [a] if a else [],
            },
        )
        if answer is None:
            return False
        await service._call_client_with_retry(
            client,
            lambda: client.send_message(target_chat_id, answer, **kwargs),
            operation=f"keyword monitor AI OCR reply {target_chat_id}",
        )
        return True

    if action_id == 7:
        query = (message.text or message.caption or "").strip()
        answer = await _run_ai_call(
            target_chat_id,
            ai_tools=ai_tools,
            method="calculate_problem",
            request_meta={"query_chars": len(query), "question_preview": query},
            ai_call=lambda: ai_tools.calculate_problem(
                query, system_prompt=action.get("ai_prompt")
            ),
            error_label="AI calculate+click failed",
            result_meta=lambda a: {
                "response_chars": len(a),
                "selected_options": [a] if a else [],
            },
        )
        if answer is None:
            return False
        proxy_action = {"action": 3, "text": answer}
        return await click_keyboard_by_text(
            service, client, target_chat_id, target_thread_id, proxy_action, message
        )

    if action_id == 4:
        if not message.photo:
            return False
        clickable_buttons = collect_clickable_buttons(message)
        if not clickable_buttons:
            return False
        image_bytes = await download_photo_bytes(client, message)
        question_text = (
            (message.caption or message.text or "").strip()
            or "Choose the correct option"
        )
        options = [button_text for _, _, button_text in clickable_buttons]
        model = ai_tools.default_model
        logger.info(
            "关键词监听 AI 请求 | chat=%s | %s",
            target_chat_id,
            safe_ai_request_meta(
                method="choose_options_by_image",
                model=model,
                has_image=True,
                image_bytes=len(image_bytes),
                query_chars=len(question_text),
                options_count=len(options),
                question_preview=question_text,
                options_preview=options,
            ),
        )
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
            logger.info(
                "关键词监听 AI 响应 | chat=%s | %s",
                target_chat_id,
                safe_ai_result_meta(
                    method="choose_options_by_image",
                    model=model,
                    elapsed_ms=_elapsed,
                    result_type="list",
                    result_count=len(result_indexes or []),
                    selected_options=selected_options,
                ),
            )
        except Exception as exc:
            _elapsed = (time.monotonic() - _start) * 1000
            logger.error(
                "关键词监听 AI 调用失败 | chat=%s | method=choose_options_by_image elapsed_ms=%.0f error=%s: %s",
                target_chat_id,
                _elapsed,
                type(exc).__name__,
                safe_text_preview(exc, 200),
            )
            raise TerminalAIActionError(
                f"AI choose_options_by_image failed: {type(exc).__name__}"
            ) from exc
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
                if await click_inline_button(service, client, message, button):
                    clicked += 1
            else:
                await service._call_client_with_retry(
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


async def execute_bot_link_action(
    service: Any,
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
    jobs = collect_bot_cmd_jobs(
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
        service._append_rule_log(
            log_rule,
            f"警告：max_batch={max_batch} 高于默认 {DEFAULT_BOT_CMD_MAX_BATCH}，"
            f"{_BOT_CMD_MAX_BATCH_RISK_HINT}",
        )
    if len(jobs) > 1:
        service._append_rule_log(
            log_rule,
            f"Bot 命令批量触发：共 {len(jobs)} 条（上限 {max_batch}），"
            f"间隔 {send_interval:g}s",
        )

    success_count = 0
    for bot_username, start_param in jobs:
        rate_key = f"{account_name}:{bot_username.lower()}"
        await await_bot_cmd_slot(service._bot_cmd_last_sent, rate_key, send_interval)
        logger.info(
            "Bot 命令 action 发送 | bot=%s | cmd=%s | param=%s | chat=%s",
            bot_username,
            command_prefix,
            start_param,
            target_chat_id,
        )
        try:
            result = await service._call_client_with_retry(
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
            service._append_rule_log(
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
            service._append_rule_log(
                log_rule,
                f"Bot 命令触发失败：@{bot_username} {command_prefix} {start_param}，错误={exc}",
            )

    return success_count > 0


async def execute_continue_action(
    service: Any,
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
    """执行单步继续动作。

    1/2/9 直接发送；3/4/5/6/7 在超时窗口内轮询目标会话寻找可用消息执行。
    """
    action_id = int(action.get("action"))
    logger.warning(
        "[CONTINUE_ACTION_ENTRY] action_id=%s | action=%s | source_message=%s",
        action_id,
        action,
        "present" if source_message else "None",
    )
    kwargs: Dict[str, Any] = {}
    if target_thread_id is not None:
        kwargs["message_thread_id"] = target_thread_id

    if action_id == 1:
        text = str(action.get("text") or "").strip()
        if not text:
            return False
        await service._call_client_with_retry(
            client,
            lambda: client.send_message(target_chat_id, text, **kwargs),
            operation=f"keyword monitor continue send_message {target_chat_id}",
        )
        return True

    if action_id == 2:
        dice = str(action.get("dice") or "🎲").strip() or "🎲"
        await service._call_client_with_retry(
            client,
            lambda: client.send_dice(target_chat_id, dice, **kwargs),
            operation=f"keyword monitor continue send_dice {target_chat_id}",
        )
        return True

    if action_id == 9:
        return await execute_bot_link_action(
            service,
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

    action_timeout = timeout or read_positive_float_env(
        "KEYWORD_MONITOR_CONTINUE_ACTION_TIMEOUT", DEFAULT_CONTINUE_TIMEOUT, 1.0
    )
    deadline = time.perf_counter() + action_timeout
    limit = read_positive_int_env(
        "KEYWORD_MONITOR_CONTINUE_HISTORY_LIMIT", DEFAULT_HISTORY_LIMIT, 1
    )

    while time.perf_counter() < deadline:
        recent_messages = await load_recent_messages(
            service,
            client,
            target_chat_id,
            target_thread_id,
            limit,
        )
        usable_messages = [
            message
            for message in recent_messages
            if message_supports_action(message, action_id)
        ]

        for recent_message in usable_messages:
            if action_id == 3:
                before_state = _messages_state(recent_messages)
                clicked, matched = await click_keyboard_by_text_result(
                    service,
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
                            if await wait_for_chat_advance(
                                service,
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
                        if await wait_for_continue_action_candidate(
                            service,
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
                    if await wait_for_terminal_success(
                        service,
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

            if await execute_ai_action(
                service,
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


async def execute_continue_actions(
    service: Any,
    *,
    account_name: str,
    client: Any,
    rule: KeywordMonitorRule,
    message: Message,
    variables: Dict[str, str],
) -> None:
    """按规则顺序执行命中后的全部继续动作，任一失败即中止。

    TerminalAIActionError 视为终态失败（AI 不可恢复），其余异常视为步骤失败。
    """
    continue_action_list = continue_actions(rule.action)
    if not continue_action_list:
        return

    target_chat_id, target_thread_id = continue_target(rule.action, message)
    interval = continue_interval(rule.action)
    timeout = read_positive_float_env(
        "KEYWORD_MONITOR_CONTINUE_ACTION_TIMEOUT", DEFAULT_CONTINUE_TIMEOUT, 1.0
    )

    await warm_chat(client, target_chat_id)
    lock = get_account_lock(account_name)
    async with lock:
        rendered_actions = [
            _render_action_templates(raw_action, variables)
            for raw_action in continue_action_list
        ]
        service._append_rule_log(
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
            action_desc = describe_continue_action(action)
            action_delay = _resolve_action_delay(
                action,
                interval if index > 1 else 0.0,
            )
            if action_delay > 0:
                service._append_rule_log(
                    rule,
                    f"后续动作 {index}/{len(rendered_actions)} 等待 {action_delay:g} 秒后执行：{action_desc}",
                )
                await asyncio.sleep(action_delay)
            service._append_rule_log(
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
                    execute_continue_action(
                        service,
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
                    len(continue_action_list),
                    "terminal AI failure" if is_terminal else "failed",
                    rule.task_name,
                    exc,
                    exc_info=True,
                )
                service._append_rule_log(
                    rule,
                    f"后续动作 {index}/{len(rendered_actions)} {'AI 调用不可恢复失败' if is_terminal else '执行异常'}：{exc}",
                )
                return
            if not result:
                logger.warning(
                    "Keyword monitor continue action %s/%s returned false for task %s",
                    index,
                    len(continue_action_list),
                    rule.task_name,
                )
                service._append_rule_log(
                    rule,
                    f"后续动作 {index}/{len(rendered_actions)} 执行失败：{action_desc}",
                )
                return
            service._append_rule_log(
                rule,
                f"后续动作 {index}/{len(rendered_actions)} 执行成功：{action_desc}",
            )
        service._append_rule_log(rule, "关键词命中后续动作全部执行完成")

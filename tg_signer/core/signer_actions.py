"""UserSigner 动作执行器 Mixin（从 runtime.py 拆分）。

动作类型对应的点击/发送/AI 调用执行逻辑；判定工具见 signer_matchers.py。
方法经 self 解析，跨 Mixin 方法（_log_received_target_message 等）运行时可用。
"""
from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime, timedelta
from typing import Any, BinaryIO, Optional, Union

from croniter import croniter

from tg_signer.async_utils import compute_backoff
from tg_signer.compat import (
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    button_text_matches,
    clean_text_for_match,
    collect_clickable_buttons,
    errors,
)
from tg_signer.config import (
    ActionT,
    ChooseOptionByImageAction,
    ClickButtonByCalculationProblemAction,
    ClickKeyboardByTextAction,
    KeywordNotifyAction,
    ReplyByCalculationProblemAction,
    ReplyByImageRecognitionAction,
    SendDiceAction,
    SendTextAction,
    SignChatV3,
)
from tg_signer.core.client import (
    Client,
    _is_callback_confirmation_unavailable,
    _is_callback_data_invalid,
    get_now,
)
from tg_signer.log_utils import (
    safe_ai_request_meta,
    safe_ai_result_meta,
    safe_text_preview,
)
from tg_signer.utils import (
    print_to_user,
    read_positive_float_env,
    read_positive_int_env,
)


class SignerActionsMixin:

    async def _click_inline_button(self, message: Message, btn) -> bool:
        callback_data = getattr(btn, "callback_data", None)
        if callback_data is not None:
            if (
                await self.request_callback_answer(
                    self.app,
                    message.chat.id,
                    message.id,
                    callback_data,
                )
                is not None
            ):
                return True

        click = getattr(message, "click", None)
        if callable(click):
            # pyrogram Message.click(x=0, y=None, ...)：x 为字符串时按按钮文本点击；
            # 不存在 text 关键字参数，历史上第二个 ((), {"text": ...}) 兜底必然 TypeError，已移除
            try:
                await click(getattr(btn, "text", None))
                self.log("点击完成")
                return True
            except TypeError:
                # 按钮文本不可点击（如 None/非法文本），回落等待后续消息确认
                pass
            except Exception as e:
                if _is_callback_data_invalid(e):
                    self.log(
                        "Message.click 也无法确认按钮回调，继续等待机器人后续消息确认",
                        level="WARNING",
                    )
                else:
                    self.log(f"Message.click 无法确认按钮回调: {e}", level="WARNING")

        if callback_data is None:
            self.log(
                "按钮没有可用 callback_data，且 Message.click 未确认点击结果，将等待后续消息判断",
                level="WARNING",
            )
        else:
            self.log(
                "按钮回调未被 Telegram API 确认，将等待后续消息判断是否已推进",
                level="WARNING",
            )
        return False


    async def _click_keyboard_by_text_result(
        self,
        action: ClickKeyboardByTextAction,
        message: Message,
        *,
        message_thread_id: Optional[int] = None,
        before_click=None,
        log_not_found: bool = True,
    ) -> tuple[bool, bool]:
        target_text = clean_text_for_match(action.text)
        if not target_text:
            self.log("点击按钮动作的目标文本为空（清理后无匹配内容）", level="WARNING")
            return False, False

        if reply_markup := message.reply_markup:
            if isinstance(reply_markup, InlineKeyboardMarkup):
                flat_buttons = (b for row in reply_markup.inline_keyboard for b in row)
                for btn in flat_buttons:
                    if not btn.text:
                        continue
                    btn_text_clean = clean_text_for_match(btn.text)
                    if button_text_matches(target_text, btn_text_clean):
                        self.context.last_callback_answer = None
                        self.log(f"成功匹配到并点击按钮: [{btn.text}] (匹配词: {action.text})")
                        if before_click:
                            await before_click()
                        return await self._click_inline_button(message, btn), True
                if log_not_found:
                    self.log(
                        f"Target button '{action.text}' not found in inline keyboard.",
                        level="WARNING",
                    )
            elif isinstance(reply_markup, ReplyKeyboardMarkup):
                for row in reply_markup.keyboard:
                    for btn in row:
                        btn_text = btn if isinstance(btn, str) else getattr(btn, "text", "")
                        if not btn_text:
                            continue
                        btn_text_clean = clean_text_for_match(btn_text)
                        if button_text_matches(target_text, btn_text_clean):
                            self.log(f"成功匹配并发送回复键盘文本: [{btn_text}] (匹配词: {action.text})")
                            kwargs = {}
                            if message_thread_id is not None:
                                kwargs["message_thread_id"] = message_thread_id
                            if before_click:
                                await before_click()
                            await self.send_message(message.chat.id, btn_text, **kwargs)
                            return True, True
                if log_not_found:
                    self.log(
                        f"Target button '{action.text}' not found in reply keyboard.",
                        level="WARNING",
                    )
        return False, False


    async def _click_keyboard_by_text(
        self,
        action: ClickKeyboardByTextAction,
        message: Message,
        *,
        message_thread_id: Optional[int] = None,
    ):
        clicked, _matched = await self._click_keyboard_by_text_result(
            action,
            message,
            message_thread_id=message_thread_id,
        )
        return clicked


    async def _execute_ai_action(
        self,
        *,
        method: str,
        ai_call: Any,
        model: str,
        request_meta: dict,
        result_meta: dict | Any,
        action_log: str,
        empty_result_log: str | None = None,
        result_empty_check: Any = None,
        success_log: str | None = None,
    ) -> Any:
        """统一 AI 调用样板：计时 → 请求日志 → 调用 → 响应日志 → 异常标准化。

        `result_meta` 支持两种形态：
        - dict：直接展开为 safe_ai_result_meta 关键字参数（适用于静态元数据）
        - callable(result, elapsed_ms) -> dict：从原始结果动态派生元数据（如 selected_options）
        """
        self.log(action_log)
        self.log(
            f"AI 请求 | {safe_ai_request_meta(method=method, model=model, **request_meta)}"
        )
        _start = time.monotonic()
        try:
            result = await ai_call()
        except Exception as exc:
            _elapsed = (time.monotonic() - _start) * 1000
            self.log(
                f"AI 调用失败 | method={method} model={model} elapsed_ms={_elapsed:.0f}"
                f" error={type(exc).__name__}: {safe_text_preview(exc, 200)}",
                level="ERROR",
            )
            raise
        _elapsed = (time.monotonic() - _start) * 1000
        _meta = result_meta(result, _elapsed) if callable(result_meta) else dict(result_meta)
        self.log(
            f"AI 响应 | {safe_ai_result_meta(method=method, model=model, elapsed_ms=_elapsed, **_meta)}"
        )
        # 空结果检查：result_empty_check 是接收结果的可调用对象（如 lambda r: (r or "").strip()），
        # 返回值为空（falsy）即视为空结果，原实现误写为 not result_empty_check 导致恒不触发
        if (
            empty_result_log
            and result_empty_check is not None
            and not result_empty_check(result)
        ):
            self.log(empty_result_log, level="WARNING")
            return None
        if success_log:
            self.log(success_log(result), level="DEBUG")
        return result


    async def _reply_by_calculation_problem(
        self, action: ReplyByCalculationProblemAction, message
    ):
        if message.text:
            self._log_received_target_message(message)
            self.log("AI 正在分析计算题")
            self.log(f"题目内容：{self._normalize_log_text(message.text, 220)}")
            ai_prompt = action.ai_prompt if (action.ai_prompt or "").strip() else None
            if ai_prompt:
                self.log("当前 AI 动作使用自定义提示词")
            model = self.get_ai_tools().default_model
            answer = await self._execute_ai_action(
                method="calculate_problem",
                ai_call=lambda: self.get_ai_tools().calculate_problem(
                    message.text,
                    system_prompt=ai_prompt,
                ),
                model=model,
                request_meta={
                    "query_chars": len(message.text),
                    "custom_prompt": bool(ai_prompt),
                    "question_preview": message.text,
                },
                result_meta=lambda result, _elapsed_ms: {
                    "response_chars": len(result or ""),
                    "selected_options": [],
                },
                action_log="AI 正在分析计算题",
                empty_result_log="AI 未返回有效答案",
                result_empty_check=lambda r: (r or "").strip(),
                success_log=lambda r: f"AI 计算完成 | answer_chars={len(r)} | 预览: {safe_text_preview(r, 80)}",
            )
            if answer is None:
                return False
            answer = answer.strip()
            if not answer:
                return False
            await self.send_message(message.chat.id, answer)
            return True
        return False


    async def _reply_by_image_recognition(
        self, action: ReplyByImageRecognitionAction, message
    ):
        if not message.photo:
            return False
        if collect_clickable_buttons(message):
            self.log("跳过带按钮的图片消息，等待真正的验证码/题目图片")
            return False
        self._log_received_target_message(message)
        self.log("AI 正在分析图片中的文字")
        image_buffer: BinaryIO = await self.app.download_media(
            message.photo.file_id, in_memory=True
        )
        image_buffer.seek(0)
        image_bytes = image_buffer.read()
        ai_prompt = action.ai_prompt if (action.ai_prompt or "").strip() else None
        if ai_prompt:
            self.log("当前 AI 动作使用自定义提示词")
        model = self.get_ai_tools().default_model
        text = await self._execute_ai_action(
            method="extract_text_by_image",
            ai_call=lambda: self.get_ai_tools().extract_text_by_image(
                image_bytes,
                system_prompt=ai_prompt,
            ),
            model=model,
            request_meta={
                "has_image": True,
                "image_bytes": len(image_bytes),
                "custom_prompt": bool(ai_prompt),
            },
            result_meta=lambda result, _elapsed_ms: {
                "response_chars": len(result or ""),
                "selected_options": [],
            },
            action_log="AI 正在分析图片中的文字",
            empty_result_log="AI 未识别到可发送文本",
            result_empty_check=lambda r: (r or "").strip(),
            success_log=lambda r: f"AI OCR 完成 | text_chars={len(r)} | 预览: {safe_text_preview(r, 80)}",
        )
        if text is None:
            return False
        text = text.strip()
        if not text:
            return False
        await self.send_message(message.chat.id, text)
        return True


    async def _click_button_by_calculation_problem(
        self, action: ClickButtonByCalculationProblemAction, message
    ):
        if not message.text:
            return False
        self._log_received_target_message(message)
        self.log("AI 正在计算按钮答案")
        ai_prompt = action.ai_prompt if (action.ai_prompt or "").strip() else None
        if ai_prompt:
            self.log("当前 AI 动作使用自定义提示词")
        model = self.get_ai_tools().default_model
        answer = await self._execute_ai_action(
            method="calculate_problem",
            ai_call=lambda: self.get_ai_tools().calculate_problem(
                message.text,
                system_prompt=ai_prompt,
            ),
            model=model,
            request_meta={
                "query_chars": len(message.text),
                "custom_prompt": bool(ai_prompt),
                "question_preview": message.text,
            },
            result_meta=lambda result, _elapsed_ms: {
                "response_chars": len(result or ""),
                "selected_options": [],
            },
            action_log="AI 正在计算按钮答案",
            empty_result_log="AI 未返回可用于点击的答案",
            result_empty_check=lambda r: (r or "").strip(),
            success_log=lambda r: f"AI 计算完成 | answer_chars={len(r)} | 预览: {safe_text_preview(r, 80)}",
        )
        if answer is None:
            return False
        answer = answer.strip()
        if not answer:
            return False
        proxy_action = ClickKeyboardByTextAction(text=answer)
        return await self._click_keyboard_by_text(proxy_action, message)


    async def _choose_option_by_image(self, action: ChooseOptionByImageAction, message):
        if not message.photo:
            return False
        clickable_buttons = collect_clickable_buttons(message)
        if clickable_buttons:
            self._log_received_target_message(message)
            self.log("AI 正在分析图片并匹配可点击按钮")
            image_buffer: BinaryIO = await self.app.download_media(
                message.photo.file_id, in_memory=True
            )
            image_buffer.seek(0)
            image_bytes = image_buffer.read()
            options = [button_text for _, _, button_text in clickable_buttons]
            if not options:
                self.log("未找到可供点击的按钮", level="WARNING")
                return False
            question_text = (message.caption or message.text or "").strip()
            if not question_text:
                question_text = "选择正确的选项"
            ai_prompt = action.ai_prompt if (action.ai_prompt or "").strip() else None
            if ai_prompt:
                self.log("当前 AI 动作使用自定义提示词")
            model = self.get_ai_tools().default_model
            result_indexes = await self._execute_ai_action(
                method="choose_options_by_image",
                ai_call=lambda: self.get_ai_tools().choose_options_by_image(
                    image_bytes,
                    question_text,
                    list(enumerate(options, start=1)),
                    system_prompt=ai_prompt,
                ),
                model=model,
                request_meta={
                    "has_image": True,
                    "image_bytes": len(image_bytes),
                    "query_chars": len(question_text),
                    "options_count": len(options),
                    "custom_prompt": bool(ai_prompt),
                    "question_preview": question_text,
                    "options_preview": options,
                },
                result_meta=lambda result, elapsed_ms: {
                    "result_type": "list",
                    "result_count": len(result or []),
                    "selected_options": [
                        options[idx - 1] for idx in (result or []) if 1 <= idx <= len(options)
                    ] + [
                        options[idx] for idx in (result or []) if 0 <= idx < len(options)
                    ],
                },
                action_log="AI 正在分析图片并匹配可点击按钮",
                empty_result_log="AI 未返回可点击选项",
                result_empty_check=lambda r: bool(r),
            )
            if result_indexes is None:
                return False
            clicked = 0
            for result_index in result_indexes:
                if result_index == 0:
                    selected_idx = 0
                elif 1 <= result_index <= len(options):
                    selected_idx = result_index - 1
                elif 0 <= result_index < len(options):
                    selected_idx = result_index
                else:
                    self.log(f"AI 返回了非法选项序号: {result_index}", level="WARNING")
                    return False
                button_kind, target_btn, result = clickable_buttons[selected_idx]
                self.log(f"AI 选择并点击选项 | index={selected_idx + 1} | preview={safe_text_preview(result, 60)}", level="DEBUG")
                if button_kind == "inline":
                    if await self._click_inline_button(message, target_btn):
                        clicked += 1
                else:
                    kwargs = {}
                    message_thread_id = self._resolve_message_thread_id(message)
                    if message_thread_id is not None:
                        kwargs["message_thread_id"] = message_thread_id
                    await self.send_message(message.chat.id, result, **kwargs)
                    clicked += 1
                await asyncio.sleep(0.3)
            return clicked > 0
        return False


    async def wait_for(
        self,
        chat: SignChatV3,
        action: ActionT,
        timeout=None,
        *,
        next_action: Optional[ActionT] = None,
    ):
        if timeout is None:
            timeout = read_positive_float_env("SIGN_TASK_ACTION_TIMEOUT", 25.0, 5.0)
        kwargs = {}
        if chat.message_thread_id is not None:
            kwargs["message_thread_id"] = chat.message_thread_id
        history_limit = read_positive_int_env("SIGN_TASK_HISTORY_LOOKBACK", 12, 3)
        if isinstance(action, SendTextAction):
            # 必须在 send 前快照，否则 bot 若已秒回会漏检
            before_state = await self._chat_state_snapshot(
                chat, history_limit=history_limit
            )
            result = await self.send_message(
                chat.chat_id, action.text, chat.delete_after, **kwargs
            )
            await self._maybe_stop_after_send(
                chat, before_state=before_state, history_limit=history_limit
            )
            return result
        elif isinstance(action, SendDiceAction):
            before_state = await self._chat_state_snapshot(
                chat, history_limit=history_limit
            )
            result = await self.send_dice(
                chat.chat_id, action.dice, chat.delete_after, **kwargs
            )
            await self._maybe_stop_after_send(
                chat, before_state=before_state, history_limit=history_limit
            )
            return result
        elif isinstance(action, KeywordNotifyAction):
            self.log("关键词监听通知动作为后台常驻监听配置，当前运行时跳过")
            return True
        self.context.last_callback_answer = None
        start = time.perf_counter()
        last_message = None
        try:
            if isinstance(action, ClickKeyboardByTextAction):
                next_history_scan = 0.0
                while time.perf_counter() - start < timeout:
                    messages_dict = self.context.chat_messages.get(chat.chat_id) or {}
                    for message in reversed(list(messages_dict.values())):
                        if message is None:
                            continue
                        if not self._message_matches_chat_thread(message, chat):
                            continue
                        if not self._message_is_actionable_target(message):
                            continue
                        self._log_received_target_message(message)
                        self.context.waiting_message = message

                        before_click_state: dict[int, tuple] = {}

                        async def remember_before_click():
                            nonlocal before_click_state
                            before_click_state = await self._chat_state_snapshot(
                                chat,
                                history_limit=history_limit,
                            )

                        ok, matched = await self._click_keyboard_by_text_result(
                            action,
                            message,
                            message_thread_id=chat.message_thread_id,
                            before_click=remember_before_click,
                            log_not_found=False,
                        )
                        if ok:
                            if next_action is not None:
                                follow_timeout = min(6.0, timeout)
                                await self._handle_post_click_followup(
                                    chat,
                                    action_text=action.text,
                                    next_action=next_action,
                                    before_click_state=before_click_state,
                                    history_limit=history_limit,
                                    timeout=follow_timeout,
                                )
                            self.context.chat_messages[chat.chat_id][message.id] = None
                            return True
                        if matched:
                            self.context.waiting_message = None
                            follow_timeout = min(6.0, timeout)
                            if next_action is not None:
                                followup_state = await self._handle_post_click_followup(
                                    chat,
                                    action_text=action.text,
                                    next_action=next_action,
                                    before_click_state=before_click_state,
                                    history_limit=history_limit,
                                    timeout=follow_timeout,
                                )
                                if followup_state in {"success", "next"}:
                                    return True
                                self.log(
                                    "按钮点击返回异常，且未检测到下一步动作，准备重试完整流程",
                                    level="WARNING",
                                )
                                return False
                            if await self._wait_for_terminal_success(
                                chat,
                                before_click_state,
                                history_limit=history_limit,
                                timeout=follow_timeout,
                            ):
                                self.log(
                                    f"按钮「{action.text}」回调未确认，但已检测到成功回复，判定该步骤完成"
                                )
                                return True
                            self.log(
                                "按钮点击返回异常，且未检测到明确成功消息，准备重试完整流程",
                                level="WARNING",
                            )
                            return False

                    now_ts = time.perf_counter()
                    if now_ts >= next_history_scan:
                        next_history_scan = now_ts + 1.5
                        try:
                            history_messages = []
                            async for message in self.app.get_chat_history(
                                chat.chat_id,
                                limit=history_limit,
                            ):
                                history_messages.append(message)

                            for message in history_messages:
                                if message is None:
                                    continue
                                if not self._message_matches_chat_thread(message, chat):
                                    continue
                                if not self._message_is_actionable_target(message):
                                    continue
                                self._log_received_target_message(message)

                                before_click_state: dict[int, tuple] = {}

                                async def remember_before_click():
                                    nonlocal before_click_state
                                    before_click_state = await self._chat_state_snapshot(
                                        chat,
                                        history_limit=history_limit,
                                    )

                                ok, matched = await self._click_keyboard_by_text_result(
                                    action,
                                    message,
                                    message_thread_id=chat.message_thread_id,
                                    before_click=remember_before_click,
                                    log_not_found=False,
                                )
                                if ok:
                                    if next_action is not None:
                                        follow_timeout = min(6.0, timeout)
                                        await self._handle_post_click_followup(
                                            chat,
                                            action_text=action.text,
                                            next_action=next_action,
                                            before_click_state=before_click_state,
                                            history_limit=history_limit,
                                            timeout=follow_timeout,
                                        )
                                    return True
                                if matched:
                                    self.context.waiting_message = None
                                    follow_timeout = min(6.0, timeout)
                                    if next_action is not None:
                                        followup_state = await self._handle_post_click_followup(
                                            chat,
                                            action_text=action.text,
                                            next_action=next_action,
                                            before_click_state=before_click_state,
                                            history_limit=history_limit,
                                            timeout=follow_timeout,
                                        )
                                        if followup_state in {"success", "next"}:
                                            return True
                                        self.log(
                                            "按钮点击返回异常，且未检测到下一步动作，准备重试完整流程",
                                            level="WARNING",
                                        )
                                        return False
                                    if await self._wait_for_terminal_success(
                                        chat,
                                        before_click_state,
                                        history_limit=history_limit,
                                        timeout=follow_timeout,
                                    ):
                                        self.log(
                                            f"按钮「{action.text}」回调未确认，但已检测到成功回复，判定该步骤完成"
                                        )
                                        return True
                                    self.log(
                                        "按钮点击返回异常，且未检测到明确成功消息，准备重试完整流程",
                                        level="WARNING",
                                    )
                                    return False
                        except Exception as e:
                            self.log(f"最近消息按钮查找失败: {e}", level="WARNING")

                    await asyncio.sleep(0.3)

                self.log(
                    f"未在 {timeout}s 内找到可点击按钮，不再直接发送按钮文本: {action.text}",
                    level="WARNING",
                )
                return False

            while time.perf_counter() - start < timeout:
                await asyncio.sleep(0.3)
                messages_dict = self.context.chat_messages.get(chat.chat_id)
                if not messages_dict:
                    continue
                messages = list(messages_dict.values())
                # 暂无新消息
                if messages[-1] == last_message:
                    continue
                last_message = messages[-1]
                for message in messages:
                    if message is None:
                        continue
                    if not self._message_matches_chat_thread(message, chat):
                        continue
                    if not self._message_is_actionable_target(message):
                        continue
                    self.context.waiting_message = message
                    self._log_received_target_message(message)
                    ok = False
                    if isinstance(action, ClickKeyboardByTextAction):
                        ok = await self._click_keyboard_by_text(
                            action,
                            message,
                            message_thread_id=chat.message_thread_id,
                        )
                    elif isinstance(action, ReplyByCalculationProblemAction):
                        ok = await self._reply_by_calculation_problem(action, message)
                    elif isinstance(action, ChooseOptionByImageAction):
                        ok = await self._choose_option_by_image(action, message)
                    elif isinstance(action, ReplyByImageRecognitionAction):
                        ok = await self._reply_by_image_recognition(action, message)
                    elif isinstance(action, ClickButtonByCalculationProblemAction):
                        ok = await self._click_button_by_calculation_problem(action, message)
                    if ok:
                        # 将消息ID对应value置为None，保证收到消息的编辑时消息所处的顺序
                        self.context.chat_messages[chat.chat_id][message.id] = None
                        return None
            # Fallback: try recent history in case message handlers missed the reply.
            if isinstance(
                action,
                (
                    ClickKeyboardByTextAction,
                    ReplyByCalculationProblemAction,
                    ChooseOptionByImageAction,
                    ReplyByImageRecognitionAction,
                    ClickButtonByCalculationProblemAction,
                ),
            ):
                try:
                    self.log("等待超时，尝试从最近消息回退处理当前步骤", level="WARNING")
                    async for message in self.app.get_chat_history(chat.chat_id, limit=history_limit):
                        if not self._message_matches_chat_thread(message, chat):
                            continue
                        if not self._message_is_actionable_target(message):
                            continue
                        self._log_received_target_message(message)
                        if isinstance(action, ClickKeyboardByTextAction):
                            ok = await self._click_keyboard_by_text(
                                action,
                                message,
                                message_thread_id=chat.message_thread_id,
                            )
                        elif isinstance(action, ReplyByCalculationProblemAction):
                            ok = await self._reply_by_calculation_problem(action, message)
                        elif isinstance(action, ChooseOptionByImageAction):
                            ok = await self._choose_option_by_image(action, message)
                        elif isinstance(action, ReplyByImageRecognitionAction):
                            ok = await self._reply_by_image_recognition(action, message)
                        else:
                            ok = await self._click_button_by_calculation_problem(
                                action, message
                            )
                        if ok:
                            return None
                except Exception as e:
                    self.log(f"历史消息回退失败: {e}", level="WARNING")

            self.log(
                f"{self._current_action_step_label()}等待超时：{self._describe_action(action)}",
                level="WARNING",
            )
            raise RuntimeError(
                f"Action did not complete within {timeout}s. chat_id={chat.chat_id}, action={action}"
            )
        finally:
            self.context.waiting_message = None
            self.context.last_callback_answer = None


    async def request_callback_answer(
        self,
        client: Client,
        chat_id: Union[int, str],
        message_id: int,
        callback_data: Union[str, bytes],
        **kwargs,
    ):
        max_retries = 5
        for attempt in range(1, max_retries + 1):
            try:
                answer = await client.request_callback_answer(
                    chat_id, message_id, callback_data=callback_data, **kwargs
                )
                callback_message = self._normalize_log_text(
                    getattr(answer, "message", None), 220
                )
                callback_url = self._normalize_log_text(getattr(answer, "url", None), 220)
                self.context.last_callback_answer = callback_message or None
                self.log("点击完成")
                if callback_message:
                    self.log(f"收到回复（按钮提示）：{callback_message}")
                if callback_url:
                    self.log(f"按钮回调跳转：{callback_url}")
                return answer
            except errors.FloodWait as e:
                wait_seconds = max(int(getattr(e, "value", 1) or 1), 1)
                self.log(
                    f"触发 FloodWait，{wait_seconds}s 后重试 ({attempt}/{max_retries})",
                    level="WARNING",
                )
                if attempt >= max_retries:
                    self.log(e, level="ERROR")
                    return None
                await asyncio.sleep(wait_seconds)
            except (TimeoutError, asyncio.TimeoutError, OSError, ConnectionError) as e:
                backoff = compute_backoff(attempt, cap=8, shift=1)
                self.log(
                    f"按钮回调暂未响应，{backoff}s 后重试确认 ({attempt}/{max_retries})",
                    level="WARNING",
                )
                if attempt >= max_retries:
                    self.log(e, level="ERROR")
                    return None
                try:
                    await self._ensure_app_ready()
                except Exception as reconnect_exc:
                    self.log(
                        f"按钮回调重连失败: {type(reconnect_exc).__name__}: {reconnect_exc}",
                        level="WARNING",
                    )
                await asyncio.sleep(backoff)
            except errors.BadRequest as e:
                if _is_callback_data_invalid(e):
                    self.log(
                        "Telegram 返回 DATA_INVALID，按钮点击结果无法由 callback API 确认，将改用后续消息判断",
                        level="WARNING",
                    )
                    return None
                if _is_callback_confirmation_unavailable(e):
                    self.log(
                        f"Telegram 无法确认按钮回调({type(e).__name__})，将改用后续消息判断",
                        level="WARNING",
                    )
                    return None
                self.log(e, level="ERROR")
                return None
        return None


    async def schedule_messages(
        self,
        chat_id: Union[int, str],
        text: str,
        crontab: str = None,
        next_times: int = 1,
        random_seconds: int = 0,
    ):
        now = get_now()
        it = croniter(crontab, start_time=now)
        if self.user is None:
            await self.login(print_chat=False)
        results = []
        async with self.app:
            for n in range(next_times):
                next_dt: datetime = it.next(ret_type=datetime) + timedelta(
                    seconds=random.randint(0, random_seconds)
                )
                results.append({"at": next_dt.isoformat(), "text": text})
                await self._call_with_retry(
                    lambda _next_dt=next_dt: self.app.send_message(
                        chat_id,
                        text,
                        schedule_date=_next_dt,
                    ),
                    operation=f"计划发送消息到 {chat_id}",
                )
                await asyncio.sleep(0.1)
                print_to_user(f"已配置次数：{n + 1}")
        self.log(f"已配置定时发送消息，次数{next_times}")
        return results


    async def get_schedule_messages(self, chat_id):
        if self.user is None:
            await self.login(print_chat=False)
        async with self.app:
            messages = await self.app.get_scheduled_messages(chat_id)
            for message in messages:
                print_to_user(f"{message.date}: {message.text}")




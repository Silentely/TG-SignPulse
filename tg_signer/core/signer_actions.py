"""UserSigner 动作执行器 Mixin（从 runtime.py 拆分）。

动作类型对应的点击/发送/AI 调用执行逻辑；判定工具见 signer_matchers.py。
方法经 self 解析，跨 Mixin 方法（_log_received_target_message 等）运行时可用。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import random
import time
from datetime import datetime, timedelta
from typing import Any, Optional, Union

from croniter import croniter

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
    PluginAction,
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
from tg_signer.core.plugin_host import PluginProcessHost
from tg_signer.core.plugins import PluginContext, PluginRegistry, PluginTimeoutError
from tg_signer.core.signer_config import FLOOD_WAIT_RETRY_MAX_SECONDS
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


def _get_message_text(message: Any) -> str:
    """提取消息的题干文本，优先 text，回退 caption，缺失返回空字符串"""
    if not message:
        return ""
    text = getattr(message, "text", None) or getattr(message, "caption", None) or ""
    return str(text).strip()


def _normalize_button_text(text: Any) -> str:
    """归一化按钮与选项文本，消除空白字符并小写化，实现高容错匹配"""
    if not text:
        return ""
    return "".join(str(text).split()).lower()


class SignerActionsMixin:
    _get_message_text = staticmethod(_get_message_text)
    _normalize_button_text = staticmethod(_normalize_button_text)

    async def _click_inline_button(self, message: Message, btn) -> bool:
        callback_data = getattr(btn, "callback_data", None)
        chat = getattr(message, "chat", None)
        msg_id = getattr(message, "id", None)
        if callback_data is not None and chat is not None and msg_id is not None:
            ans = await self.request_callback_answer(
                self.app,
                chat.id,
                msg_id,
                callback_data,
            )
            if ans is not None:
                return True
            strict_confirm = (
                read_positive_int_env("TG_SIGNER_STRICT_CALLBACK_CONFIRMATION", 0, 0)
                == 1
            )
            if not strict_confirm and getattr(
                getattr(self, "context", None), "last_callback_unconfirmed", False
            ):
                self.log(
                    "按钮点击已发送至 Telegram，未收到 API 显式回调（Bot 通常以发送新消息或编辑方式响应），继续推进流程",
                    level="INFO",
                )
                return True
            return False

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
                        self.log(
                            f"成功匹配到并点击按钮: [{btn.text}] (匹配词: {action.text})"
                        )
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
                        btn_text = (
                            btn if isinstance(btn, str) else getattr(btn, "text", "")
                        )
                        if not btn_text:
                            continue
                        btn_text_clean = clean_text_for_match(btn_text)
                        if button_text_matches(target_text, btn_text_clean):
                            self.log(
                                f"成功匹配并发送回复键盘文本: [{btn_text}] (匹配词: {action.text})"
                            )
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
        _meta = (
            result_meta(result, _elapsed)
            if callable(result_meta)
            else dict(result_meta)
        )
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
        question_text = _get_message_text(message)
        if question_text:
            self._log_received_target_message(message)
            self.log("AI 正在分析计算题")
            self.log(f"题目内容：{self._normalize_log_text(question_text, 220)}")
            ai_prompt = action.ai_prompt if (action.ai_prompt or "").strip() else None
            if ai_prompt:
                self.log("当前 AI 动作使用自定义提示词")
            model = self.get_ai_tools().default_model
            answer = await self._execute_ai_action(
                method="calculate_problem",
                ai_call=lambda: self.get_ai_tools().calculate_problem(
                    question_text,
                    system_prompt=ai_prompt,
                ),
                model=model,
                request_meta={
                    "query_chars": len(question_text),
                    "custom_prompt": bool(ai_prompt),
                    "question_preview": question_text,
                },
                result_meta=lambda result, _elapsed_ms: {
                    "response_chars": len(result or ""),
                    "selected_options": [],
                },
                action_log="AI 正在分析计算题",
                empty_result_log="AI 未返回有效答案",
                result_empty_check=lambda r: (r or "").strip(),
                success_log=lambda r: (
                    f"AI 计算完成 | answer_chars={len(r)} | 预览: {safe_text_preview(r, 80)}"
                ),
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
        image_buffer = await self.app.download_media(
            message.photo.file_id, in_memory=True
        )
        if not image_buffer:
            self.log("下载图片数据为空", level="WARNING")
            return False
        if hasattr(image_buffer, "seek"):
            image_buffer.seek(0)
        image_bytes = image_buffer.read() if hasattr(image_buffer, "read") else (bytes(image_buffer) if isinstance(image_buffer, (bytes, bytearray)) else b"")
        if not image_bytes:
            self.log("图片数据读取为空", level="WARNING")
            return False
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
            success_log=lambda r: (
                f"AI OCR 完成 | text_chars={len(r)} | 预览: {safe_text_preview(r, 80)}"
            ),
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
        question_text = _get_message_text(message)
        if not question_text:
            return False
        clickable_buttons = collect_clickable_buttons(message)
        options = [btn_text for _, _, btn_text in clickable_buttons]
        if options:
            query_text = (
                f"{question_text}\n\n"
                f"可选答案：{json.dumps(options, ensure_ascii=False)}\n"
                f"请只从可选答案中选择最匹配的一项，并原样回复该选项文本。"
            )
        else:
            query_text = question_text

        self._log_received_target_message(message)
        self.log("AI 正在计算按钮答案")
        ai_prompt = action.ai_prompt if (action.ai_prompt or "").strip() else None
        if ai_prompt:
            self.log("当前 AI 动作使用自定义提示词")
        model = self.get_ai_tools().default_model
        answer = await self._execute_ai_action(
            method="calculate_problem",
            ai_call=lambda: self.get_ai_tools().calculate_problem(
                query_text,
                system_prompt=ai_prompt,
            ),
            model=model,
            request_meta={
                "query_chars": len(query_text),
                "custom_prompt": bool(ai_prompt),
                "question_preview": question_text,
            },
            result_meta=lambda result, _elapsed_ms: {
                "response_chars": len(result or ""),
                "selected_options": [],
            },
            action_log="AI 正在计算按钮答案",
            empty_result_log="AI 未返回可用于点击的答案",
            result_empty_check=lambda r: (r or "").strip(),
            success_log=lambda r: (
                f"AI 计算完成 | answer_chars={len(r)} | 预览: {safe_text_preview(r, 80)}"
            ),
        )
        if answer is None:
            return False
        answer = answer.strip()
        if not answer:
            return False

        proxy_action = ClickKeyboardByTextAction(text=answer)
        if await self._click_keyboard_by_text(proxy_action, message):
            return True

        norm_answer = _normalize_button_text(answer)
        if norm_answer:
            matched_btn_info = None
            # 第一轮：归一化后精确匹配（消除按钮文案中的空白/大小写差异）
            for btn_kind, btn, btn_text in clickable_buttons:
                if _normalize_button_text(btn_text) == norm_answer:
                    matched_btn_info = (btn_kind, btn, btn_text)
                    break
            # 第二轮：宽松子串匹配兜底；双方均为纯数字时要求整串相等，
            # 避免答案 "1" 误命中编号按钮 "10"
            if not matched_btn_info:
                for btn_kind, btn, btn_text in clickable_buttons:
                    norm_btn = _normalize_button_text(btn_text)
                    if norm_answer.isdigit() and norm_btn.isdigit():
                        continue
                    if (len(norm_answer) >= 2 and norm_answer in norm_btn) or (
                        len(norm_btn) >= 2 and norm_btn in norm_answer
                    ):
                        matched_btn_info = (btn_kind, btn, btn_text)
                        break

            if matched_btn_info:
                btn_kind, btn, btn_text = matched_btn_info
                self.log(f"宽松匹配到按钮: [{btn_text}] (AI答案: {answer})")
                if btn_kind == "inline":
                    return await self._click_inline_button(message, btn)
                else:
                    kwargs = {}
                    message_thread_id = (
                        self._resolve_message_thread_id(message)
                        if hasattr(self, "_resolve_message_thread_id")
                        else None
                    )
                    if message_thread_id is not None:
                        kwargs["message_thread_id"] = message_thread_id
                    await self.send_message(message.chat.id, btn_text, **kwargs)
                    return True

        return False

    def _find_previous_photo_message(
        self,
        messages: Optional[list[Any]],
        message: Any,
        *,
        max_backtrack: int = 20,
        max_age_seconds: float = 120.0,
    ) -> Any | None:
        """从历史消息快照中逆序回溯查找当前按钮消息之前最近的一条包含 photo 的有效消息。

        - 过滤掉非相同发送者的消息（防群聊其他成员插播干扰）
        - 限制查找跨度不超过 max_backtrack 条有效消息
        - 限制候选消息与当前消息时间差不超过 max_age_seconds
        - 忽略已被置为 None 的已消费缓存项
        """
        if messages is None:
            chat_id = getattr(getattr(message, "chat", None), "id", None)
            if hasattr(self, "context") and hasattr(self.context, "chat_messages") and chat_id is not None:
                messages_snapshot = list((self.context.chat_messages.get(chat_id) or {}).values())
            else:
                messages_snapshot = []
        else:
            messages_snapshot = list(messages)

        target_idx = None
        for idx, m in enumerate(messages_snapshot):
            if m is message:
                target_idx = idx
                break
            if m is not None and getattr(message, "id", None) is not None:
                if getattr(m, "id", None) == message.id:
                    target_idx = idx
                    break

        if target_idx is not None:
            candidate_slice = messages_snapshot[:target_idx]
        else:
            msg_id = getattr(message, "id", None)
            if isinstance(msg_id, int):
                candidate_slice = [
                    m for m in messages_snapshot
                    if m is not None and (getattr(m, "id", None) is None or m.id < msg_id)
                ]
            else:
                candidate_slice = [m for m in messages_snapshot if m is not message]

        def _get_sender_identity(msg: Any) -> tuple[str, Any] | None:
            if msg is None:
                return None
            from_user = getattr(msg, "from_user", None)
            if from_user is not None and getattr(from_user, "id", None) is not None:
                return ("user", from_user.id)
            sender_chat = getattr(msg, "sender_chat", None)
            if sender_chat is not None and getattr(sender_chat, "id", None) is not None:
                return ("chat", sender_chat.id)
            return None

        curr_sender = _get_sender_identity(message)
        curr_date = getattr(message, "date", None)

        backtrack_count = 0
        for cand in reversed(candidate_slice):
            if cand is None:
                continue

            backtrack_count += 1
            if backtrack_count > max_backtrack:
                break

            if not getattr(cand, "photo", None):
                continue

            # 时效检查：message.date - prev.date <= max_age_seconds
            cand_date = getattr(cand, "date", None)
            if curr_date is not None and cand_date is not None:
                age: Optional[float] = None
                if isinstance(curr_date, datetime) and isinstance(cand_date, datetime):
                    age = (curr_date - cand_date).total_seconds()
                elif isinstance(curr_date, (int, float)) and isinstance(cand_date, (int, float)):
                    age = float(curr_date) - float(cand_date)
                else:
                    try:
                        c_ts = curr_date.timestamp() if isinstance(curr_date, datetime) else float(curr_date)
                        p_ts = cand_date.timestamp() if isinstance(cand_date, datetime) else float(cand_date)
                        age = c_ts - p_ts
                    except Exception:
                        age = None
                if age is not None and age > max_age_seconds:
                    continue

            # 发送者一致性检查
            cand_sender = _get_sender_identity(cand)
            if curr_sender is not None and cand_sender is not None:
                if curr_sender != cand_sender:
                    continue
            elif curr_sender is None and cand_sender is None:
                self.log(
                    "分离式验证码：图片消息与按钮消息均无明确发送者标识（匿名场景），允许回溯匹配",
                    level="WARNING",
                )
            else:
                continue

            return cand

        return None

    async def _choose_option_by_image(self, action: ChooseOptionByImageAction, message):
        clickable_buttons = collect_clickable_buttons(message)
        if not clickable_buttons:
            return False

        target_photo_msg = message if getattr(message, "photo", None) else None
        if target_photo_msg is None:
            chat_id = getattr(getattr(message, "chat", None), "id", None)
            messages_snapshot: list[Any] = []
            if hasattr(self, "context") and hasattr(self.context, "chat_messages") and chat_id is not None:
                messages_snapshot = list((self.context.chat_messages.get(chat_id) or {}).values())
            target_photo_msg = self._find_previous_photo_message(messages_snapshot, message)
            if not target_photo_msg or not getattr(target_photo_msg, "photo", None):
                self.log("分离式验证码：未找到可供匹配的前序图片消息", level="WARNING")
                return False
            self.log(
                f"分离式验证码：成功回溯到前序图片消息 (id={getattr(target_photo_msg, 'id', None)})，将使用该图片匹配当前按钮",
                level="INFO",
            )

        self._log_received_target_message(message)
        self.log("AI 正在分析图片并匹配可点击按钮")
        options = [button_text for _, _, button_text in clickable_buttons]
        if not options:
            self.log("未找到可供点击的按钮", level="WARNING")
            return False

        photo_obj = getattr(target_photo_msg, "photo", None)
        file_id = getattr(photo_obj, "file_id", None) if photo_obj else None
        if not file_id:
            self.log("图片消息中未找到有效的 photo.file_id", level="WARNING")
            return False

        image_buffer = await self.app.download_media(
            file_id, in_memory=True
        )
        if not image_buffer:
            self.log("下载图片数据为空", level="WARNING")
            return False
        if hasattr(image_buffer, "seek"):
            image_buffer.seek(0)
        image_bytes = image_buffer.read() if hasattr(image_buffer, "read") else (bytes(image_buffer) if isinstance(image_buffer, (bytes, bytearray)) else b"")
        if not image_bytes:
            self.log("图片数据读取为空", level="WARNING")
            return False
        question_text = (
            getattr(message, "caption", None)
            or getattr(message, "text", None)
            or getattr(target_photo_msg, "caption", None)
            or getattr(target_photo_msg, "text", None)
            or ""
        ).strip()
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
                    options[0]
                    if idx == 0
                    else (
                        options[idx - 1]
                        if 1 <= idx <= len(options)
                        else options[idx]
                    )
                    for idx in (result or [])
                    if idx == 0
                    or (1 <= idx <= len(options))
                    or (0 <= idx < len(options))
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
            self.log(
                f"AI 选择并点击选项 | index={selected_idx + 1} | preview={safe_text_preview(result, 60)}",
                level="DEBUG",
            )
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


    def _record_plugin_task_execution(
        self,
        plugin_name: str,
        start_ts: float,
        success: bool,
        error: Optional[str] = None,
        trigger_type: str = "active",
    ) -> None:
        """记录正式任务执行路径的插件指标（仅进程内执行需要本层记录）。"""
        try:
            PluginRegistry.record_execution(
                plugin_name,
                duration_ms=(time.perf_counter() - start_ts) * 1000,
                success=success,
                error=error,
                trigger_type=trigger_type,
            )
        except Exception as exc:  # 指标记录失败不应影响任务执行
            self.log(f"记录插件「{plugin_name}」执行指标失败: {exc}", level="DEBUG")

    async def _dispatch_reactive_plugin_message(
        self,
        action: PluginAction,
        chat: SignChatV3,
        message: Message,
        eff_timeout: float,
        is_history: bool = False,
    ) -> bool:
        # 快速短路：若为 reactive 且消息完全无内容
        if not getattr(message, "text", None) and not getattr(message, "caption", None):
            return False

        plugin = PluginRegistry.get(action.plugin_name)
        if not plugin:
            self.log(
                f"自定义插件「{action.plugin_name}」未注册或未成功加载", level="ERROR"
            )
            raise RuntimeError(
                f"Plugin '{action.plugin_name}' not found in PluginRegistry"
            )
        if not getattr(plugin, "enabled", True) or not PluginRegistry.is_enabled(action.plugin_name):
            self.log(f"自定义插件「{action.plugin_name}」已被停用，跳过响应", level="WARNING")
            return False
        ctx = PluginContext(
            app=self.app,
            chat_id=chat.chat_id,
            message_thread_id=chat.message_thread_id,
            message=message,
            params=action.params,
            logger=self,
            plugin_name=action.plugin_name,
        )

        engine = os.getenv("PLUGIN_ISOLATION_ENGINE", "auto").lower()
        use_subprocess = engine == "process" or (
            engine == "auto" and not inspect.iscoroutinefunction(plugin.handler)
        )

        if use_subprocess:
            host = PluginProcessHost(
                plugin_name=action.plugin_name,
                ctx=ctx,
                timeout=eff_timeout,
                trigger_type="reactive",
            )
            try:
                res = await host.execute()
                return bool(res)
            except TimeoutError:
                msg_kind = "单条历史消息" if is_history else "单条消息"
                self.log(
                    f"插件「{action.plugin_name}」处理{msg_kind}超时", level="WARNING"
                )
                return False
            except Exception as e:
                msg_kind = "历史消息" if is_history else "消息"
                self.log(
                    f"插件「{action.plugin_name}」处理{msg_kind}异常: {e}",
                    level="WARNING",
                )
                return False
        else:
            handler_call = (
                plugin.handler(ctx)
                if asyncio.iscoroutinefunction(plugin.handler)
                else asyncio.to_thread(plugin.handler, ctx)
            )
            start_ts = time.perf_counter()
            try:
                res = await asyncio.wait_for(handler_call, timeout=eff_timeout)
                # 进程内路径由本层记录指标（reactive 模式返回 False 仅表示未命中，
                # 仍属正常执行完成）；子进程路径由 PluginProcessHost 记录
                self._record_plugin_task_execution(
                    action.plugin_name, start_ts, success=True, trigger_type="reactive"
                )
                return bool(res)
            except asyncio.TimeoutError:
                self._record_plugin_task_execution(
                    action.plugin_name,
                    start_ts,
                    success=False,
                    error=f"执行超时（{eff_timeout}s）",
                    trigger_type="reactive",
                )
                msg_kind = "单条历史消息" if is_history else "单条消息"
                self.log(
                    f"插件「{action.plugin_name}」处理{msg_kind}超时", level="WARNING"
                )
                return False
            except Exception as e:
                self._record_plugin_task_execution(
                    action.plugin_name,
                    start_ts,
                    success=False,
                    error=str(e),
                    trigger_type="reactive",
                )
                msg_kind = "历史消息" if is_history else "消息"
                self.log(
                    f"插件「{action.plugin_name}」处理{msg_kind}异常: {e}",
                    level="WARNING",
                )
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
        eff_timeout = timeout
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
        elif isinstance(action, PluginAction):
            plugin = PluginRegistry.get(action.plugin_name)
            if not plugin:
                self.log(
                    f"自定义插件「{action.plugin_name}」未注册或未成功加载",
                    level="ERROR",
                )
                raise RuntimeError(
                    f"Plugin '{action.plugin_name}' not found in PluginRegistry"
                )
            if not getattr(plugin, "enabled", True) or not PluginRegistry.is_enabled(action.plugin_name):
                self.log(f"自定义插件「{action.plugin_name}」已被停用，跳过执行", level="WARNING")
                return False
            eff_timeout = action.timeout if action.timeout is not None else timeout

            effective_mode = action.mode
            if getattr(plugin, "mode", None) == "active":
                effective_mode = "active"

            if effective_mode == "active":
                ctx = PluginContext(
                    app=self.app,
                    chat_id=chat.chat_id,
                    message_thread_id=chat.message_thread_id,
                    message=None,
                    params=action.params,
                    logger=self,
                    plugin_name=action.plugin_name,
                )
                engine = os.getenv("PLUGIN_ISOLATION_ENGINE", "auto").lower()
                use_subprocess = engine == "process" or (
                    engine == "auto" and not inspect.iscoroutinefunction(plugin.handler)
                )

                if use_subprocess:
                    host = PluginProcessHost(
                        plugin_name=action.plugin_name,
                        ctx=ctx,
                        timeout=eff_timeout,
                        trigger_type="active",
                    )
                    try:
                        res = await host.execute()
                    except TimeoutError as exc:
                        self.log(
                            f"插件「{action.plugin_name}」执行超时（{eff_timeout}s）",
                            level="ERROR",
                        )
                        raise PluginTimeoutError(
                            f"Plugin '{action.plugin_name}' timed out after {eff_timeout}s and was killed"
                        ) from exc
                    except Exception as exc:
                        self.log(
                            f"插件「{action.plugin_name}」执行异常: {exc}",
                            level="ERROR",
                        )
                        raise
                else:
                    handler_call = (
                        plugin.handler(ctx)
                        if asyncio.iscoroutinefunction(plugin.handler)
                        else asyncio.to_thread(plugin.handler, ctx)
                    )
                    start_ts = time.perf_counter()
                    try:
                        res = await asyncio.wait_for(handler_call, timeout=eff_timeout)
                    except asyncio.TimeoutError as exc:
                        self._record_plugin_task_execution(
                            action.plugin_name,
                            start_ts,
                            success=False,
                            error=f"执行超时（{eff_timeout}s）",
                            trigger_type="active",
                        )
                        self.log(
                            f"插件「{action.plugin_name}」执行超时（{eff_timeout}s）",
                            level="ERROR",
                        )
                        raise PluginTimeoutError(
                            f"Plugin '{action.plugin_name}' timed out after {eff_timeout}s"
                        ) from exc
                    except Exception as exc:
                        self._record_plugin_task_execution(
                            action.plugin_name,
                            start_ts,
                            success=False,
                            error=str(exc),
                            trigger_type="active",
                        )
                        self.log(
                            f"插件「{action.plugin_name}」执行异常: {exc}",
                            level="ERROR",
                        )
                        raise
                    # active 模式下返回 False 即业务语义的执行失败
                    self._record_plugin_task_execution(
                        action.plugin_name,
                        start_ts,
                        success=res is not False,
                        error="插件返回执行失败" if res is False else None,
                        trigger_type="active",
                    )

                if res is False:
                    self.log(
                        f"插件「{action.plugin_name}」返回执行失败", level="WARNING"
                    )
                    return False
                return True
            else:
                timeout = eff_timeout
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
                                    before_click_state = (
                                        await self._chat_state_snapshot(
                                            chat,
                                            history_limit=history_limit,
                                        )
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
                                        followup_state = (
                                            await self._handle_post_click_followup(
                                                chat,
                                                action_text=action.text,
                                                next_action=next_action,
                                                before_click_state=before_click_state,
                                                history_limit=history_limit,
                                                timeout=follow_timeout,
                                            )
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
                        ok = await self._click_button_by_calculation_problem(
                            action, message
                        )
                    elif isinstance(action, PluginAction):
                        ok = await self._dispatch_reactive_plugin_message(
                            action, chat, message, eff_timeout, is_history=False
                        )
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
                    PluginAction,
                ),
            ):
                try:
                    self.log(
                        "等待超时，尝试从最近消息回退处理当前步骤", level="WARNING"
                    )
                    async for message in self.app.get_chat_history(
                        chat.chat_id, limit=history_limit
                    ):
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
                            ok = await self._reply_by_calculation_problem(
                                action, message
                            )
                        elif isinstance(action, ChooseOptionByImageAction):
                            ok = await self._choose_option_by_image(action, message)
                        elif isinstance(action, ReplyByImageRecognitionAction):
                            ok = await self._reply_by_image_recognition(action, message)
                        elif isinstance(action, ClickButtonByCalculationProblemAction):
                            ok = await self._click_button_by_calculation_problem(
                                action, message
                            )
                        elif isinstance(action, PluginAction):
                            ok = await self._dispatch_reactive_plugin_message(
                                action, chat, message, eff_timeout, is_history=True
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
        timeout = kwargs.pop(
            "timeout",
            read_positive_float_env("TG_SIGNER_CALLBACK_TIMEOUT", 5.0, 1.0),
        )
        max_retries = read_positive_int_env("TG_SIGNER_CALLBACK_MAX_RETRIES", 2, 1)
        if hasattr(self, "context"):
            self.context.last_callback_unconfirmed = False

        for attempt in range(1, max_retries + 1):
            try:
                answer = await client.request_callback_answer(
                    chat_id,
                    message_id,
                    callback_data=callback_data,
                    timeout=int(timeout),
                    **kwargs,
                )
                callback_message = self._normalize_log_text(
                    getattr(answer, "message", None), 220
                )
                callback_url = self._normalize_log_text(
                    getattr(answer, "url", None), 220
                )
                if hasattr(self, "context"):
                    self.context.last_callback_answer = callback_message or None
                    self.context.last_callback_unconfirmed = False
                self.log("点击完成")
                if callback_message:
                    self.log(f"收到回复（按钮提示）：{callback_message}")
                if callback_url:
                    self.log(f"按钮回调跳转：{callback_url}")
                return answer
            except errors.FloodWait as e:
                wait_seconds = max(int(getattr(e, "value", 1) or 1), 1)
                if wait_seconds > FLOOD_WAIT_RETRY_MAX_SECONDS:
                    self.log(
                        f"触发长时 FloodWait ({wait_seconds}s > {FLOOD_WAIT_RETRY_MAX_SECONDS}s)，放弃重试以避免阻塞调度",
                        level="WARNING",
                    )
                    # 上抛而非返回 None：让 runner 走失败历史与 FloodWait 冷却登记，
                    # 否则本次运行会被记为成功而实际上并未点击成功。
                    raise
                self.log(
                    f"触发 FloodWait，{wait_seconds}s 后重试 ({attempt}/{max_retries})",
                    level="WARNING",
                )
                if attempt >= max_retries:
                    self.log(e, level="ERROR")
                    return None
                await asyncio.sleep(wait_seconds)
            except (TimeoutError, asyncio.TimeoutError):
                # MTProto 请求已成功由底层 socket 发出，但 Bot 未调用 answerCallbackQuery
                if attempt < max_retries:
                    self.log(
                        f"按钮回调暂未响应，1s 后重试确认 ({attempt}/{max_retries})",
                        level="WARNING",
                    )
                    await asyncio.sleep(1.0)
                else:
                    self.log(
                        "按钮回调在预期时间内未收到 API 显式应答（Bot 通常以发送新消息或编辑方式响应），点击请求已发出",
                        level="INFO",
                    )
                    if hasattr(self, "context"):
                        self.context.last_callback_unconfirmed = True
                    return None
            except (ConnectionError, OSError) as e:
                self.log(
                    f"网络连接异常，尝试重连 ({attempt}/{max_retries}): {e}",
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
                await asyncio.sleep(1.0)
            except errors.BadRequest as e:
                if _is_callback_data_invalid(e):
                    self.log(
                        "Telegram 返回 DATA_INVALID，按钮点击结果无法由 callback API 确认，将改用后续消息判断",
                        level="WARNING",
                    )
                    if hasattr(self, "context"):
                        self.context.last_callback_unconfirmed = True
                    return None
                if _is_callback_confirmation_unavailable(e):
                    self.log(
                        f"Telegram 无法确认按钮回调({type(e).__name__})，将改用后续消息判断",
                        level="WARNING",
                    )
                    if hasattr(self, "context"):
                        self.context.last_callback_unconfirmed = True
                    return None
                self.log(e, level="ERROR")
                return None
            except Exception as e:
                self.log(f"按钮回调发生未知异常: {e}", level="ERROR")
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

UserSignerActionsMixin = SignerActionsMixin

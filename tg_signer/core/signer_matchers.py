"""UserSigner 判定/等待工具 Mixin（从 runtime.py 拆分）。

纯判定、状态标记、日志摘要与等待轮询助手；动作执行见 signer_actions.py。
方法经 self 解析，不依赖本模块之外的 Mixin 实现。
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Optional

from tg_signer.compat import (
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    button_text_matches,
    clean_text_for_match,
    collect_clickable_buttons,
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


class SignerMatchersMixin:

    def _message_matches_chat_thread(self, message: Message, chat: SignChatV3) -> bool:
        if message is None:
            return False
        if chat.message_thread_id is None:
            return True
        msg_thread_id = getattr(message, "message_thread_id", None) or getattr(
            message, "reply_to_top_message_id", None
        )
        return msg_thread_id == chat.message_thread_id

    @staticmethod

    def _normalize_log_text(text: Optional[str], limit: int = 280) -> str:
        value = " / ".join(
            line.strip() for line in str(text or "").splitlines() if line.strip()
        )
        if len(value) > limit:
            return value[: limit - 3] + "..."
        return value


    def _describe_chat_run(self, chat: SignChatV3) -> str:
        parts = [f"开始执行任务对象: Chat ID={chat.chat_id}"]
        if chat.message_thread_id is not None:
            parts.append(f"话题ID={chat.message_thread_id}")
        if chat.name:
            parts.append(f"名称={self._normalize_log_text(chat.name, 60)}")
        parts.append(f"动作数={len(chat.actions)}")
        return " | ".join(parts)


    def _describe_action(self, action: ActionT) -> str:
        if isinstance(action, SendTextAction):
            return f"发送文本消息：{self._normalize_log_text(action.text, 120)}"
        if isinstance(action, SendDiceAction):
            return f"发送骰子：{self._normalize_log_text(str(action.dice), 40)}"
        if isinstance(action, ClickKeyboardByTextAction):
            return f"点击文字按钮：{self._normalize_log_text(action.text, 80)}"
        if isinstance(action, ChooseOptionByImageAction):
            return "识图后点按钮"
        if isinstance(action, ReplyByCalculationProblemAction):
            return "识别计算题并发送答案"
        if isinstance(action, ReplyByImageRecognitionAction):
            return "识图后发送文本"
        if isinstance(action, ClickButtonByCalculationProblemAction):
            return "计算答案后点击按钮"
        if isinstance(action, KeywordNotifyAction):
            keywords = ", ".join(
                self._normalize_log_text(keyword, 24) for keyword in action.keywords[:3]
            )
            if len(action.keywords) > 3:
                keywords += ", ..."
            return f"关键词监听：{keywords or '未配置关键词'}"
        return str(action)


    def _current_action_step_label(self) -> str:
        index = getattr(self.context, "current_action_index", None)
        total = getattr(self.context, "current_action_total", None)
        if index and total:
            return f"第 {index}/{total} 步"
        if index:
            return f"第 {index} 步"
        return "当前步骤"


    def _set_current_action_context(
        self,
        index: int,
        total: int,
        action: ActionT,
    ) -> str:
        description = self._describe_action(action)
        self.context.current_action_index = index
        self.context.current_action_total = total
        self.context.current_action_description = description
        self.context.logged_action_message_markers.clear()
        return description


    def _clear_current_action_context(self) -> None:
        self.context.current_action_index = None
        self.context.current_action_total = None
        self.context.current_action_description = ""
        self.context.logged_action_message_markers.clear()


    def _log_received_target_message(
        self,
        message: Optional[Message],
        *,
        prefix: Optional[str] = None,
        allow_duplicate: bool = False,
    ) -> None:
        if message is None:
            return

        marker = self._message_state_marker(message)
        if not allow_duplicate:
            markers = getattr(self.context, "logged_action_message_markers", None)
            if markers is not None:
                if marker in markers:
                    return
                markers.add(marker)

        summary = self._summarize_target_message(message)
        if not summary:
            return

        if prefix is None:
            if getattr(message, "photo", None):
                prefix = "收到图片"
            elif getattr(message, "text", None) or getattr(message, "caption", None):
                prefix = "收到回复"
            else:
                prefix = "收到任务对象消息"
        self.log(f"{prefix}：{summary}")


    def _summarize_target_message(self, message: Optional[Message]) -> str:
        if message is None:
            return ""

        parts: list[str] = []
        text = self._normalize_log_text(
            getattr(message, "text", None) or getattr(message, "caption", None)
        )
        if text:
            parts.append(text)
        elif getattr(message, "photo", None):
            parts.append("[图片消息]")
        elif getattr(message, "media", None):
            parts.append(f"[{getattr(message.media, 'value', 'media')}]")

        reply_markup = getattr(message, "reply_markup", None)
        button_texts: list[str] = []
        if isinstance(reply_markup, InlineKeyboardMarkup):
            for row in reply_markup.inline_keyboard:
                for button in row:
                    label = self._normalize_log_text(getattr(button, "text", None), 40)
                    if label:
                        button_texts.append(label)
        elif isinstance(reply_markup, ReplyKeyboardMarkup):
            for row in reply_markup.keyboard:
                for button in row:
                    raw_text = button if isinstance(button, str) else getattr(
                        button, "text", ""
                    )
                    label = self._normalize_log_text(raw_text, 40)
                    if label:
                        button_texts.append(label)

        if button_texts:
            preview = " | ".join(button_texts[:4])
            if len(button_texts) > 4:
                preview += " | ..."
            parts.append(f"按钮: {preview}")

        summary = " | ".join(part for part in parts if part).strip()
        if not summary:
            summary = f"message_id={getattr(message, 'id', '-')}"
        return summary


    def _log_target_message(
        self,
        message: Optional[Message],
        *,
        prefix: str = "任务对象消息",
        level: str = "INFO",
    ) -> None:
        summary = self._summarize_target_message(message)
        if summary:
            self.log(f"{prefix}: {summary}", level=level)


    def _reply_markup_marker(self, reply_markup):
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


    def _message_state_marker(self, message: Message):
        return (
            getattr(message, "id", None),
            getattr(message, "text", None),
            getattr(message, "caption", None),
            getattr(message, "edit_date", None),
            self._reply_markup_marker(getattr(message, "reply_markup", None)),
        )


    async def _chat_state_snapshot(
        self,
        chat: SignChatV3,
        *,
        history_limit: int,
    ) -> dict[int, tuple]:
        state: dict[int, tuple] = {}
        messages_dict = self.context.chat_messages.get(chat.chat_id) or {}
        for message in messages_dict.values():
            if not self._message_matches_chat_thread(message, chat):
                continue
            state[message.id] = self._message_state_marker(message)

        try:
            async for message in self.app.get_chat_history(
                chat.chat_id,
                limit=history_limit,
            ):
                if not self._message_matches_chat_thread(message, chat):
                    continue
                state[message.id] = self._message_state_marker(message)
        except Exception as e:
            self.log(f"点击前消息状态快照失败: {e}", level="WARNING")
        return state


    async def _wait_for_chat_advance(
        self,
        chat: SignChatV3,
        before_state: dict[int, tuple],
        *,
        history_limit: int,
        timeout: float,
    ) -> bool:
        deadline = time.perf_counter() + max(timeout, 0.5)
        while time.perf_counter() < deadline:
            await asyncio.sleep(0.25)
            current_state = await self._chat_state_snapshot(
                chat,
                history_limit=history_limit,
            )
            for message_id, marker in current_state.items():
                if before_state.get(message_id) != marker:
                    return True
        return False


    def _message_has_button_text(
        self,
        message: Message,
        text: str,
    ) -> bool:
        target_text = clean_text_for_match(text)
        if not target_text:
            return False
        for _, _, button_text in collect_clickable_buttons(message):
            if button_text_matches(target_text, clean_text_for_match(button_text)):
                return True
        return False


    def _resolve_message_thread_id(self, message: Message) -> Optional[int]:
        return getattr(message, "message_thread_id", None) or getattr(
            message, "reply_to_top_message_id", None
        )


    def _message_supports_next_action(self, action: ActionT, message: Message) -> bool:
        if message is None:
            return False
        reply_markup = getattr(message, "reply_markup", None)
        if isinstance(action, ClickKeyboardByTextAction):
            return self._message_has_button_text(message, action.text)
        if isinstance(action, ChooseOptionByImageAction):
            return bool(message.photo and collect_clickable_buttons(message))
        if isinstance(action, ReplyByCalculationProblemAction):
            return bool(message.text or message.caption)
        if isinstance(action, ReplyByImageRecognitionAction):
            return bool(message.photo)
        if isinstance(action, ClickButtonByCalculationProblemAction):
            return bool((message.text or message.caption) and reply_markup)
        return False


    async def _chat_has_action_candidate(
        self,
        chat: SignChatV3,
        action: ActionT,
        *,
        history_limit: int,
    ) -> bool:
        messages_dict = self.context.chat_messages.get(chat.chat_id) or {}
        for message in reversed(list(messages_dict.values())):
            if self._message_matches_chat_thread(message, chat) and (
                self._message_supports_next_action(action, message)
            ):
                return True

        try:
            async for message in self.app.get_chat_history(
                chat.chat_id,
                limit=history_limit,
            ):
                if self._message_matches_chat_thread(message, chat) and (
                    self._message_supports_next_action(action, message)
                ):
                    return True
        except Exception as e:
            self.log(f"下一步动作候选消息检查失败: {e}", level="WARNING")
        return False


    async def _wait_for_next_action_candidate(
        self,
        chat: SignChatV3,
        next_action: ActionT,
        before_state: dict[int, tuple],
        *,
        history_limit: int,
        timeout: float,
    ) -> bool:
        deadline = time.perf_counter() + max(timeout, 0.5)
        while time.perf_counter() < deadline:
            await asyncio.sleep(0.3)
            current_state = await self._chat_state_snapshot(
                chat,
                history_limit=history_limit,
            )
            changed_ids = {
                message_id
                for message_id, marker in current_state.items()
                if before_state.get(message_id) != marker
            }

            messages_dict = self.context.chat_messages.get(chat.chat_id) or {}
            for message in messages_dict.values():
                if (
                    self._message_matches_chat_thread(message, chat)
                    and getattr(message, "id", None) in changed_ids
                    and self._message_supports_next_action(next_action, message)
                ):
                    return True

            try:
                async for message in self.app.get_chat_history(
                    chat.chat_id,
                    limit=history_limit,
                ):
                    if (
                        self._message_matches_chat_thread(message, chat)
                        and getattr(message, "id", None) in changed_ids
                        and self._message_supports_next_action(next_action, message)
                    ):
                        return True
            except Exception as e:
                self.log(f"下一步动作候选消息检查失败: {e}", level="WARNING")
        return False


    def _text_has_terminal_success_text(self, text: Optional[str]) -> bool:
        normalized = str(text or "").strip().lower()
        if not normalized:
            return False
        strong_success_markers = (
            "签到成功",
            "已签到",
            "已经签到",
            "已经签到过",
            "今天已经签到",
            "今日已签到",
            "今日已经签到",
            "您今天已经签到",
            "您今日已签到",
            "签到过了",
            "重复签到",
            "签到机会已用完",
            "机会已用完",
            "今天不能再签到",
            "任务完成",
            "执行完成",
            "操作完成",
        )
        failure_markers = (
            "失败",
            "错误",
            "异常",
            "未成功",
            "未签到",
            "没有签到",
            "无法",
            "failed",
            "failure",
            "error",
            "invalid",
        )
        additional_action_markers = (
            "请完成",
            "请先",
            "请根据",
            "请回答",
            "请填写",
            "请发送",
            "请点击",
            "请选择",
            "进行验证",
            "完成验证",
            "验证后",
            "诗句填空",
            "填空",
            "答题",
            "作答",
            "输入答案",
            "发送答案",
            "验证码",
            "口令",
            "滑块",
            "拖动",
        )
        # 按行切分后逐行判断：同一行内失败/动作标记优先于成功标记
        # 但后续独立行的明确成功可覆盖之前行的失败（如"验证码错误\n签到成功"）
        lines = [line.strip() for line in normalized.splitlines() if line.strip()]
        has_any_success_line = False
        for line in lines:
            line_has_success = any(m in line for m in strong_success_markers)
            line_has_failure = any(m in line for m in failure_markers)
            line_has_action = any(m in line for m in additional_action_markers)
            if line_has_success and not line_has_failure and not line_has_action:
                # 纯成功行：标记存在，后续可覆盖
                has_any_success_line = True
            elif line_has_success and (line_has_failure or line_has_action):
                # 矛盾行（如"签到失败，签到成功"、"请完成验证后签到成功"）：不视为成功
                continue
        if has_any_success_line:
            return True
        # 全局检查：无强成功标记时，回退到通用成功 + 上下文匹配
        if any(marker in normalized for marker in failure_markers):
            return False
        if any(marker in normalized for marker in additional_action_markers):
            return False
        generic_success_markers = (
            "成功",
            "完成",
            "success",
            "successful",
            "done",
            "completed",
        )
        success_context_markers = (
            "签到",
            "任务",
            "执行",
            "操作",
            "领取",
            "打卡",
            "run",
            "task",
            "checkin",
            "check-in",
            "sign",
        )
        return any(marker in normalized for marker in generic_success_markers) and any(
            marker in normalized for marker in success_context_markers
        )


    def _callback_text_has_terminal_success_text(self, text: Optional[str]) -> bool:
        normalized = str(text or "").strip().lower()
        if not normalized:
            return False
        if not self._text_has_terminal_success_text(normalized):
            return False
        callback_success_markers = (
            "签到成功",
            "已签到",
            "已经签到",
            "已经签到过",
            "今天已经签到",
            "今日已签到",
            "今日已经签到",
            "您今天已经签到",
            "您今日已签到",
            "签到过了",
            "重复签到",
            "签到机会已用完",
            "机会已用完",
            "今天不能再签到",
            "任务完成",
            "执行完成",
            "操作完成",
            "success",
            "successful",
            "done",
            "completed",
        )
        return any(marker in normalized for marker in callback_success_markers)


    def _message_has_terminal_success_text(self, message: Message) -> bool:
        text = "\n".join(
            item
            for item in [
                getattr(message, "text", None),
                getattr(message, "caption", None),
            ]
            if item
        )
        return self._text_has_terminal_success_text(text)


    def _message_is_actionable_target(self, message: Optional[Message]) -> bool:
        """当前步骤是否应处理该消息。

        跳过已终态成功文案（避免对历史「签到成功」再点按钮/识图），
        以及群聊中非 bot 用户消息（避免误点他人气泡）。
        from_user 为空（频道帖等）仍允许处理。
        """
        if message is None:
            return False
        if self._message_has_terminal_success_text(message):
            return False
        from_user = getattr(message, "from_user", None)
        if from_user is not None and not getattr(from_user, "is_bot", False):
            return False
        return True


    def _post_send_terminal_timeout(self) -> float:
        """发送文本/骰子后等待 bot 终态回复的秒数；0 表示不等待。"""
        raw = os.getenv("SIGN_TASK_POST_SEND_TERMINAL_TIMEOUT")
        if raw is None or str(raw).strip() == "":
            return 3.0
        try:
            return max(float(raw), 0.0)
        except (TypeError, ValueError):
            return 3.0


    async def _maybe_stop_after_send(
        self,
        chat: SignChatV3,
        *,
        before_state: dict,
        history_limit: int,
    ) -> None:
        """发送后短等 bot 终态（已签到/签到成功），命中则停止后续步骤。

        before_state 必须在 send 之前快照；仅认发送后的消息变更，不会把未变更的历史成功当完成。
        """
        timeout = self._post_send_terminal_timeout()
        if timeout <= 0:
            return
        if await self._wait_for_terminal_success(
            chat,
            before_state,
            history_limit=history_limit,
            timeout=timeout,
        ):
            self.context.stop_after_current_action = True
            reason = (self.context.stop_reason or "").strip()
            self.log(
                "发送后检测到任务完成响应，将停止后续动作"
                + (f": {reason}" if reason else "")
            )


    async def _wait_for_terminal_success(
        self,
        chat: SignChatV3,
        before_state: dict[int, tuple],
        *,
        history_limit: int,
        timeout: float,
    ) -> bool:
        deadline = time.perf_counter() + max(timeout, 0.5)
        while time.perf_counter() < deadline:
            await asyncio.sleep(0.3)
            current_state = await self._chat_state_snapshot(
                chat,
                history_limit=history_limit,
            )
            changed_ids = {
                message_id
                for message_id, marker in current_state.items()
                if before_state.get(message_id) != marker
            }

            messages_dict = self.context.chat_messages.get(chat.chat_id) or {}
            for message in messages_dict.values():
                if (
                    self._message_matches_chat_thread(message, chat)
                    and getattr(message, "id", None) in changed_ids
                    and self._message_has_terminal_success_text(message)
                ):
                    self.context.stop_reason = self._summarize_target_message(message)
                    self._log_received_target_message(message, prefix="收到回复")
                    return True

            try:
                async for message in self.app.get_chat_history(
                    chat.chat_id,
                    limit=history_limit,
                ):
                    if (
                        self._message_matches_chat_thread(message, chat)
                        and getattr(message, "id", None) in changed_ids
                        and self._message_has_terminal_success_text(message)
                    ):
                        self.context.stop_reason = self._summarize_target_message(message)
                        self._log_received_target_message(message, prefix="收到回复")
                        return True
            except Exception as e:
                self.log(f"最终成功消息检查失败: {e}", level="WARNING")
        return False


    async def _handle_post_click_followup(
        self,
        chat: SignChatV3,
        *,
        action_text: str,
        next_action: Optional[ActionT],
        before_click_state: dict[int, tuple],
        history_limit: int,
        timeout: float,
    ) -> str:
        callback_text = (self.context.last_callback_answer or "").strip()
        if self._callback_text_has_terminal_success_text(callback_text):
            self.context.stop_after_current_action = True
            self.context.stop_reason = callback_text
            self.log(
                f"按钮「{action_text}」回调提示表明任务已完成，将跳过后续动作: {callback_text}"
            )
            return "success"

        if await self._wait_for_terminal_success(
            chat,
            before_click_state,
            history_limit=history_limit,
            timeout=timeout,
        ):
            self.context.stop_after_current_action = True
            self.log(f"按钮「{action_text}」后已检测到任务完成响应，将跳过后续动作")
            return "success"

        if next_action is not None and await self._wait_for_next_action_candidate(
            chat,
            next_action,
            before_click_state,
            history_limit=history_limit,
            timeout=timeout,
        ):
            self.log(f"按钮「{action_text}」后已检测到下一步动作可执行，继续流程")
            return "next"

        return "none"


"""UserSigner 执行编排 Mixin（从 runtime.py 拆分）。

任务对象执行主流程（sign_a_chat / normal_run / 定时调度）与消息入口；
CLI 配置见 signer_config.py，动作执行见 signer_actions.py。
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from datetime import datetime, timedelta
from typing import Optional, Union

from croniter import croniter

from tg_signer.compat import (
    EditedMessageHandler,
    Message,
    MessageHandler,
    errors,
    filters,
)
from tg_signer.config import (
    ClickKeyboardByTextAction,
    PluginAction,
    SendTextAction,
    SignChatV3,
)
from tg_signer.context_vars import task_retry_count_var
from tg_signer.core.client import Client, get_now
from tg_signer.core.template import render_template, render_template_recursive
from tg_signer.log_utils import safe_text_preview
from tg_signer.utils import read_positive_float_env, read_positive_int_env

logger = logging.getLogger("tg_signer.runtime.runner")
def _copy_action_with(action, **kwargs):
    if hasattr(action, "model_copy"):
        return action.model_copy(update=kwargs)
    elif hasattr(action, "copy"):
        return action.copy(update=kwargs)
    return action



class SignerRunnerMixin:

    async def sign_a_chat(
        self,
        chat: SignChatV3,
    ):
        try:
            # 预热会话，确保 peer/access_hash 可用
            await self.app.get_chat(chat.chat_id)
        except Exception as e:
            # 兼容历史配置：部分会话可能保存了缺失负号的 chat_id
            try:
                from pyrogram.errors import ChannelInvalid, PeerIdInvalid
                is_peer_invalid = isinstance(e, (PeerIdInvalid, ChannelInvalid))
            except Exception:
                is_peer_invalid = any(x in str(e) for x in ("PEER_ID_INVALID", "CHANNEL_INVALID"))

            if is_peer_invalid and isinstance(chat.chat_id, int):
                last_error = e
                resolved_peer = False

                # Historical configs may store a user/bot id before Pyrogram knows
                # its access hash. get_users warms the local peer cache.
                if chat.chat_id > 0:
                    try:
                        await self.app.get_users(chat.chat_id)
                        self.log(
                            f"已通过 get_users 预热会话：chat_id={chat.chat_id}",
                            level="WARNING",
                        )
                        resolved_peer = True
                        last_error = None
                    except Exception as e2:
                        last_error = e2

                if not resolved_peer:
                    cached = self._find_cached_chat(chat.chat_id, chat.name)
                    if cached:
                        username = cached.get("username")
                        cached_id = cached.get("id")
                        if username:
                            try:
                                resolved = await self.app.get_chat(username)
                                self.log(
                                    f"已通过缓存用户名预热会话：chat_id={chat.chat_id} -> @{username}",
                                    level="WARNING",
                                )
                                chat.chat_id = resolved.id
                                resolved_peer = True
                                last_error = None
                            except Exception as e2:
                                last_error = e2
                        if (
                            not resolved_peer
                            and cached_id
                            and cached_id != chat.chat_id
                        ):
                            try:
                                await self.app.get_chat(cached_id)
                                self.log(
                                    f"已通过缓存记录预热会话：chat_id={chat.chat_id} -> {cached_id}",
                                    level="WARNING",
                                )
                                chat.chat_id = cached_id
                                resolved_peer = True
                                last_error = None
                            except Exception as e2:
                                last_error = e2

                if not resolved_peer:
                    candidates = []
                    if chat.chat_id > 0:
                        candidates.append(-chat.chat_id)
                        candidates.append(int(f"-100{chat.chat_id}"))
                    elif chat.chat_id < 0 and not str(chat.chat_id).startswith("-100"):
                        candidates.append(int(f"-100{abs(chat.chat_id)}"))

                    for candidate in candidates:
                        if candidate == chat.chat_id:
                            continue
                        try:
                            await self.app.get_chat(candidate)
                            self.log(
                                f"已通过候选 chat_id 预热会话：chat_id={chat.chat_id} -> {candidate}",
                                level="WARNING",
                            )
                            chat.chat_id = candidate
                            resolved_peer = True
                            last_error = None
                            break
                        except Exception as e2:
                            last_error = e2
                            continue

                if not resolved_peer:
                    self.log(
                        f"预热会话失败: chat_id={chat.chat_id}, error={type(last_error).__name__}: {last_error}",
                        level="ERROR",
                    )
                    raise RuntimeError(
                        f"预热会话失败 chat_id={chat.chat_id}: {last_error}"
                    ) from last_error
            else:
                self.log(
                    f"预热会话失败: chat_id={chat.chat_id}, error={type(e).__name__}: {e}",
                    level="ERROR",
                )
                raise RuntimeError(
                    f"预热会话失败 chat_id={chat.chat_id}: {e}"
                ) from e
        self.log(self._describe_chat_run(chat))
        total_actions = len(chat.actions)
        if total_actions == 0:
            raise RuntimeError("任务没有配置任何执行动作")
        # 不扫历史预跳过：手动/定时均直接执行动作流；
        # 执行中由 bot 回调/新消息（已签到、签到成功等）触发 stop_after_current_action。
        max_flow_attempts = read_positive_int_env("SIGN_TASK_FLOW_RETRY_ATTEMPTS", 1, 1)
        # 优先从上下文变量读取任务级重试次数（backend 执行器写入），回退到环境变量
        try:
            _ctx_val = task_retry_count_var.get()
            if _ctx_val and _ctx_val > 0:
                max_flow_attempts = _ctx_val
        except (ImportError, LookupError):
            pass
        retry_backoff_steps = read_positive_int_env("SIGN_TASK_RETRY_BACKOFF_STEPS", 0, 0)
        last_error: Optional[Exception] = None
        last_successful_index = 0

        for flow_attempt in range(1, max_flow_attempts + 1):
            # 从失败步骤开始回退，而非从最后成功步骤；retry_backoff_steps=0 表示从失败步骤原地重试
            failed_index = last_successful_index + 1 if last_successful_index > 0 else 1
            start_index = max(1, failed_index - retry_backoff_steps) if flow_attempt > 1 else 1
            if max_flow_attempts > 1:
                if flow_attempt > 1 and start_index > 1:
                    self.log(f"开始第 {flow_attempt}/{max_flow_attempts} 次脚本流程尝试，从第 {start_index} 步继续")
                else:
                    self.log(f"开始第 {flow_attempt}/{max_flow_attempts} 次脚本流程尝试")
            try:
                if start_index == 1:
                    if chat.chat_id in self.context.chat_messages:
                        self.context.chat_messages[chat.chat_id].clear()
                    else:
                        self.context.chat_messages[chat.chat_id] = {}
                    self.context.step_outputs = {}
                    self.context.last_output = ""
                    self.context.last_received_text = ""
                self.context.stop_after_current_action = False
                self.context.stop_reason = None
                self.context.last_callback_answer = None
                for index in range(start_index, total_actions + 1):
                    action = chat.actions[index - 1]

                    # 1. 检查 skip_if_matched 条件跳过
                    if getattr(action, "skip_if_matched", None):
                        skip_pat = str(action.skip_if_matched).strip()
                        match_src = str(
                            getattr(self.context, "last_output", "")
                            or getattr(self.context, "last_received_text", "")
                            or ""
                        )
                        matched = False
                        if skip_pat and match_src:
                            if skip_pat in match_src:
                                matched = True
                            else:
                                try:
                                    if re.search(skip_pat, match_src, re.IGNORECASE):
                                        matched = True
                                except re.error:
                                    pass
                        if matched:
                            self.log(
                                f"{self._current_action_step_label()}满足跳过条件（skip_if_matched='{skip_pat}'），跳过此步骤"
                            )
                            last_successful_index = index
                            continue

                    # 2. 构建模板上下文并渲染动态宏变量
                    me_user = getattr(self, "me", None)
                    tmpl_ctx = {
                        "account": {
                            "name": str(getattr(self, "_account", "") or ""),
                            "phone": getattr(me_user, "phone_number", ""),
                            "username": getattr(me_user, "username", ""),
                            "first_name": getattr(me_user, "first_name", ""),
                        },
                        "chat": {
                            "id": chat.chat_id,
                            "name": getattr(chat, "name", ""),
                        },
                        "step": getattr(self.context, "step_outputs", {}),
                        "prev_output": getattr(self.context, "last_output", "") or "",
                        "prev": {"output": getattr(self.context, "last_output", "") or ""},
                        "last_message": getattr(self.context, "last_received_text", "") or "",
                    }

                    exec_action = action
                    if isinstance(action, SendTextAction):
                        rendered_text = render_template(action.text, tmpl_ctx)
                        if rendered_text != action.text:
                            exec_action = _copy_action_with(action, text=rendered_text)
                    elif isinstance(action, ClickKeyboardByTextAction):
                        rendered_text = render_template(action.text, tmpl_ctx)
                        if rendered_text != action.text:
                            exec_action = _copy_action_with(action, text=rendered_text)
                    elif isinstance(action, PluginAction):
                        rendered_params = render_template_recursive(action.params, tmpl_ctx)
                        exec_action = _copy_action_with(action, params=rendered_params)
                    elif hasattr(action, "ai_prompt") and action.ai_prompt:
                        rendered_prompt = render_template(action.ai_prompt, tmpl_ctx)
                        if rendered_prompt != action.ai_prompt:
                            exec_action = _copy_action_with(action, ai_prompt=rendered_prompt)

                    action_description = self._set_current_action_context(
                        index,
                        total_actions,
                        exec_action,
                    )
                    action_delay = self._resolve_action_delay(
                        exec_action,
                        float(chat.action_interval or 0) if index > 1 else 0.0,
                    )
                    try:
                        if action_delay > 0:
                            self.log(
                                f"{self._current_action_step_label()}将在 {action_delay:g} 秒后执行：{action_description}"
                            )
                        self.log(
                            f"正在执行{self._current_action_step_label()}：{action_description}"
                        )
                        if action_delay > 0:
                            await asyncio.sleep(action_delay)
                        next_action = (
                            chat.actions[index] if index < total_actions else None
                        )
                        _step_max_retries = 2
                        result = None
                        step_failed = False
                        for _step_attempt in range(1, _step_max_retries + 1):
                            try:
                                result = await self.wait_for(
                                    chat,
                                    exec_action,
                                    next_action=next_action,
                                )
                                break
                            except Exception as step_exc:
                                if self._is_transient_step_error(step_exc) and _step_attempt < _step_max_retries:
                                    self.log(
                                        f"{self._current_action_step_label()}瞬时错误，"
                                        f"{_step_attempt}/{_step_max_retries} 次重试: "
                                        f"{type(step_exc).__name__}: {safe_text_preview(step_exc, 120)}",
                                        level="WARNING",
                                    )
                                    await asyncio.sleep(1.0)
                                    continue
                                if getattr(action, "continue_on_error", False):
                                    self.log(
                                        f"{self._current_action_step_label()}出现错误，已配置容错继续（continue_on_error）: {step_exc}",
                                        level="WARNING",
                                    )
                                    step_failed = True
                                    result = None
                                    break
                                raise

                        if result is False and not step_failed:
                            if getattr(action, "continue_on_error", False):
                                self.log(
                                    f"{self._current_action_step_label()}执行返回失败，已配置容错继续（continue_on_error）",
                                    level="WARNING",
                                )
                                step_failed = True
                            else:
                                raise RuntimeError(
                                    f"{self._current_action_step_label()}执行失败：{action_description}"
                                )

                        if not step_failed:
                            self.log(
                                f"{self._current_action_step_label()}执行完成：{action_description}"
                            )
                        last_successful_index = index

                        # 记录动作执行产出至上下文供管道引用
                        out_val = ""
                        if isinstance(exec_action, (SendTextAction, ClickKeyboardByTextAction)):
                            out_val = getattr(exec_action, "text", "")
                        elif isinstance(result, str):
                            out_val = result
                        elif result is not None and result is not True and result is not False:
                            out_val = str(result)

                        if not hasattr(self.context, "step_outputs") or not isinstance(self.context.step_outputs, dict):
                            self.context.step_outputs = {}
                        self.context.step_outputs[index] = {"output": out_val}
                        self.context.step_outputs[str(index)] = {"output": out_val}
                        self.context.last_output = out_val
                        if self.context.stop_after_current_action:
                            stop_reason = (self.context.stop_reason or "").strip()
                            self.log(
                                "检测到任务已完成，停止执行后续动作"
                                + (f": {stop_reason}" if stop_reason else "")
                            )
                            self.context.stop_after_current_action = False
                            self.context.stop_reason = None
                            self.context.last_callback_answer = None
                            return
                    finally:
                        self.context.waiting_message = None
                        self._clear_current_action_context()
                return
            except Exception as exc:
                last_error = exc
                self.context.waiting_message = None
                if flow_attempt >= max_flow_attempts:
                    break
                _resume_idx = max(1, (last_successful_index + 1) - retry_backoff_steps) if last_successful_index > 0 else 1
                backoff_info = f"，从第 {_resume_idx} 步继续" if _resume_idx > 1 else "，将从第 1 步重新开始"
                self.log(
                    f"脚本流程第 {flow_attempt}/{max_flow_attempts} 次尝试失败"
                    f"{backoff_info}: {exc}",
                    level="WARNING",
                )
                base_interval = float(chat.action_interval or 0)
                if base_interval > 0:
                    exp_delay = min(base_interval * (2 ** (flow_attempt - 1)), 60.0)
                    jitter = random.uniform(0.5, 1.5)
                    retry_sleep = round(exp_delay + jitter, 1)
                else:
                    retry_sleep = read_positive_float_env("SIGN_TASK_RETRY_DELAY", 1.0, 0.01)
                self.log(
                    f"触发重试退避，将在 {retry_sleep:g} 秒后进行第 {flow_attempt + 1}/{max_flow_attempts} 次重试...",
                    level="INFO",
                )
                await asyncio.sleep(retry_sleep)

        raise RuntimeError(
            f"脚本流程尝试 {max_flow_attempts} 次仍失败: {last_error}"
        ) from last_error


    async def run(
        self, num_of_dialogs=20, only_once: bool = False, force_rerun: bool = False
    ):
        if self.app.in_memory or self.app.session_string:
            return await self.in_memory_run(
                num_of_dialogs, only_once=only_once, force_rerun=force_rerun
            )
        return await self.normal_run(
            num_of_dialogs, only_once=only_once, force_rerun=force_rerun
        )


    async def in_memory_run(
        self, num_of_dialogs=20, only_once: bool = False, force_rerun: bool = False
    ):
        # Use the proper async context manager to integrate with ref counting
        # This avoids "Client is already terminated" when normal_run's internal
        # login() also uses 'async with app' which decrements refs to 0
        async with self.app:
            await self.normal_run(
                num_of_dialogs, only_once=only_once, force_rerun=force_rerun
            )


    async def _run_config_chats(self, config) -> int:
        success_count = 0
        for chat in config.chats:
            self.context.sign_chats[chat.chat_id].append(chat)
            try:
                await self.sign_a_chat(chat)
                success_count += 1
            except Exception as exc:
                self.log(
                    f"签到失败: {exc} (chat_id={chat.chat_id})",
                    level="WARNING",
                )
                logger.warning(
                    "Sign chat failed for chat_id=%s",
                    chat.chat_id,
                    exc_info=True,
                )
                continue
            finally:
                # Always clear chat messages to prevent memory accumulation
                self.context.chat_messages[chat.chat_id].clear()

            await asyncio.sleep(config.sign_interval)

        return success_count


    async def normal_run(
        self, num_of_dialogs=20, only_once: bool = False, force_rerun: bool = False
    ):
        if self.user is None:
            await self.login(num_of_dialogs, print_chat=True)

        config = self.load_config(self.cfg_cls)
        if config.requires_ai:
            self.ensure_ai_cfg()
        if not config.chats:
            raise RuntimeError("任务没有配置任何会话")

        sign_record = self.load_sign_record()
        chat_ids = [c.chat_id for c in config.chats]
        need_update_handlers = bool(getattr(config, "requires_updates", True))
        message_handler_ref = None
        edited_handler_ref = None


        async def sign_once():
            success_count = await self._run_config_chats(config)
            if success_count == 0 and len(config.chats) > 0:
                raise RuntimeError("所有会话均执行失败（详细请看运行日志）")

            sign_record[str(now.date())] = now.isoformat()
            try:
                from backend.utils.atomic_io import write_json_atomic

                write_json_atomic(self.sign_record_file, sign_record)
            except Exception:
                with open(self.sign_record_file, "w", encoding="utf-8") as fp:
                    json.dump(sign_record, fp)


        def need_sign(last_date_str):
            if force_rerun:
                return True
            if last_date_str not in sign_record:
                return True
            _last_sign_at = datetime.fromisoformat(sign_record[last_date_str])
            _cron_it = croniter(self._validate_sign_at(config.sign_at), _last_sign_at)
            _next_run: datetime = _cron_it.next(datetime)
            if _next_run > now:
                return False
            return True

        try:
            while True:
                if need_update_handlers and message_handler_ref is None:
                    message_handler_ref = self.app.add_handler(
                        MessageHandler(self.on_message, filters.chat(chat_ids))
                    )
                    edited_handler_ref = self.app.add_handler(
                        EditedMessageHandler(self.on_edited_message, filters.chat(chat_ids))
                    )
                try:
                    started_here = False
                    if not getattr(self.app, "is_connected", False):
                        await self.app.start()
                        started_here = True
                    try:
                        now = get_now()
                        now_date_str = str(now.date())
                        self.context = self.ensure_ctx()
                        if need_sign(now_date_str):
                            if only_once and config.random_seconds > 0:
                                delay = random.randint(0, int(config.random_seconds))
                                if delay > 0:
                                    self.log(f"单次执行随机延迟: {delay} 秒")
                                    await asyncio.sleep(delay)
                            await sign_once()
                    finally:
                        if started_here:
                            try:
                                if getattr(self.app, "is_connected", False):
                                    await self.app.stop()
                            except Exception:
                                # Already terminated or stopped - ignore
                                pass

                except (OSError, errors.Unauthorized) as e:
                    logger.exception(e)
                    await asyncio.sleep(30)
                    continue

                if only_once:
                    break
                cron_it = croniter(self._validate_sign_at(config.sign_at), now)
                next_run: datetime = cron_it.next(datetime) + timedelta(
                    seconds=random.randint(0, int(config.random_seconds))
                )
                self.log(f"下次运行时间: {next_run}")
                sleep_secs = max(0.0, (next_run - now).total_seconds())
                await asyncio.sleep(sleep_secs)
        finally:
            # Always clean up handlers, even on exception
            if message_handler_ref:
                try:
                    if isinstance(message_handler_ref, tuple):
                        self.app.remove_handler(*message_handler_ref)
                    else:
                        self.app.remove_handler(message_handler_ref)
                except Exception:
                    pass
            if edited_handler_ref:
                try:
                    if isinstance(edited_handler_ref, tuple):
                        self.app.remove_handler(*edited_handler_ref)
                    else:
                        self.app.remove_handler(edited_handler_ref)
                except Exception:
                    pass
            # Clear context to release message references
            if hasattr(self, 'context') and self.context is not None:
                self.context.chat_messages.clear()
                self.context.sign_chats.clear()


    async def run_once(self, num_of_dialogs):
        return await self.run(num_of_dialogs, only_once=True, force_rerun=True)


    async def send_text(
        self, chat_id: int, text: str, delete_after: int = None, **kwargs
    ):
        if self.user is None:
            await self.login(print_chat=False)
        async with self.app:
            await self.send_message(chat_id, text, delete_after, **kwargs)


    async def send_dice_cli(
        self,
        chat_id: Union[str, int],
        emoji: str = "🎲",
        delete_after: int = None,
        **kwargs,
    ):
        if self.user is None:
            await self.login(print_chat=False)
        async with self.app:
            await self.send_dice(chat_id, emoji, delete_after, **kwargs)


    async def _on_message(self, client: Client, message: Message):
        chats = self.context.sign_chats.get(message.chat.id)
        if not chats:
            self.log("忽略意料之外的聊天", level="WARNING")
            return
        message_thread_id = getattr(message, "message_thread_id", None) or getattr(
            message, "reply_to_top_message_id", None
        )
        topic_matched = False
        for chat in chats:
            if chat.message_thread_id is None or chat.message_thread_id == message_thread_id:
                topic_matched = True
                break
        if not topic_matched:
            self.log(
                f"忽略非目标话题消息: chat_id={message.chat.id}, thread_id={message_thread_id}",
                level="WARNING",
            )
            return
        chat_msgs = self.context.chat_messages[message.chat.id]
        chat_msgs[message.id] = message
        # Bound message cache per chat to prevent memory growth
        if len(chat_msgs) > 200:
            oldest_keys = sorted(chat_msgs.keys())[:100]
            for k in oldest_keys:
                chat_msgs.pop(k, None)


    async def on_message(self, client: Client, message: Message):
        await self._on_message(client, message)


    async def on_edited_message(self, client, message: Message):
        await self._on_message(client, message)



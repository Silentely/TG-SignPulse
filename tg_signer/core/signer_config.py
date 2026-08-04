"""UserSigner 配置交互 Mixin（从 runtime.py 拆分）。

CLI 配置询问、签名记录与聊天缓存；执行编排见 signer_runner.py。
"""
from __future__ import annotations

import asyncio
import json
import random
from collections import defaultdict
from datetime import time as dt_time
from typing import List, Optional

from croniter import CroniterBadCronError, croniter
from pydantic import ValidationError

from tg_signer.config import (
    ActionT,
    ChooseOptionByImageAction,
    ClickButtonByCalculationProblemAction,
    ClickKeyboardByTextAction,
    ReplyByCalculationProblemAction,
    ReplyByImageRecognitionAction,
    SendDiceAction,
    SendTextAction,
    SignChatV3,
    SignConfigV3,
    SupportAction,
)
from tg_signer.core.client import OPENAI_USE_PROMPT, make_dirs
from tg_signer.core.context import UserSignerWorkerContext
from tg_signer.pydantic_compat import model_validate
from tg_signer.utils import UserInput, print_to_user


class SignerConfigMixin:

    def ensure_ctx(self) -> UserSignerWorkerContext:
        return UserSignerWorkerContext(
            sign_chats=defaultdict(list),
            chat_messages=defaultdict(dict),
            waiting_message=None,
            stop_after_current_action=False,
            stop_reason=None,
            last_callback_answer=None,
            current_action_index=None,
            current_action_total=None,
            current_action_description="",
            logged_action_message_markers=set(),
        )

    @staticmethod

    def _resolve_action_delay(action, fallback_delay: float) -> float:
        raw_delay = getattr(action, "delay", None)
        if raw_delay is None:
            return max(float(fallback_delay or 0), 0.0)

        delay_text = str(raw_delay).strip()
        if not delay_text:
            return max(float(fallback_delay or 0), 0.0)

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
            return max(float(fallback_delay or 0), 0.0)


    def _load_chat_cache(self) -> List[dict]:
        try:
            cache_file = self.tasks_dir / self._account / "chats_cache.json"
            if not cache_file.exists():
                return []
            with open(cache_file, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            return data if isinstance(data, list) else []
        except Exception:
            return []


    def _find_cached_chat(self, chat_id: int, name: Optional[str]) -> Optional[dict]:
        entries = self._load_chat_cache()

        candidate_ids = {chat_id}
        if isinstance(chat_id, int):
            candidate_ids.add(-chat_id)
            try:
                candidate_ids.add(int(f"-100{abs(chat_id)}"))
            except Exception:
                pass


        def _search_entries(cache_entries: List[dict]) -> Optional[dict]:
            for entry in cache_entries:
                try:
                    if entry.get("id") in candidate_ids:
                        return entry
                except Exception:
                    continue
            if name:
                name_key = name.strip().lower().lstrip("@")
                for entry in cache_entries:
                    username = (entry.get("username") or "").strip().lower()
                    title = (entry.get("title") or "").strip().lower()
                    if username and username == name_key:
                        return entry
                    if title and title == name.strip().lower():
                        return entry
            return None

        # 1. Search current account cache
        found = _search_entries(entries)
        if found:
            return found

        # 2. Search all other accounts caches
        try:
            for account_dir in self.tasks_dir.iterdir():
                if not account_dir.is_dir() or account_dir.name == self._account:
                    continue
                other_cache_file = account_dir / "chats_cache.json"
                if other_cache_file.exists():
                    try:
                        with open(other_cache_file, "r", encoding="utf-8") as fp:
                            other_data = json.load(fp)
                        if isinstance(other_data, list):
                            found = _search_entries(other_data)
                            if found:
                                return found
                    except Exception:
                        continue
        except Exception:
            pass

        return None

    @property

    def sign_record_file(self):
        sign_record_dir = self.task_dir / str(self.user.id)
        make_dirs(sign_record_dir)
        return sign_record_dir / "sign_record.json"


    def _ask_actions(
        self, input_: UserInput, available_actions: List[SupportAction] = None
    ) -> List[ActionT]:
        print_to_user(f"{input_.index_str}开始配置<动作>，请按照实际签到顺序配置。")
        available_actions = available_actions or list(SupportAction)
        actions = []
        while True:
            try:
                local_input_ = UserInput()
                print_to_user(f"第{len(actions) + 1}个动作: ")
                for action in available_actions:
                    print_to_user(f"  {action.value}: {action.desc}")
                print_to_user()
                action_str = local_input_("输入对应的数字选择动作: ").strip()
                action = SupportAction(int(action_str))
                if action not in available_actions:
                    raise ValueError(f"不支持的动作: {action}")
                if len(actions) == 0 and action not in [
                    SupportAction.SEND_TEXT,
                    SupportAction.SEND_DICE,
                ]:
                    raise ValueError(
                        f"第一个动作必须为「{SupportAction.SEND_TEXT.desc}」或「{SupportAction.SEND_DICE.desc}」"
                    )
                if action == SupportAction.SEND_TEXT:
                    text = local_input_("输入要发送的文本: ")
                    actions.append(SendTextAction(text=text))
                elif action == SupportAction.SEND_DICE:
                    dice = local_input_("输入要发送的骰子（如 🎲, 🎯）: ")
                    actions.append(SendDiceAction(dice=dice))
                elif action == SupportAction.CLICK_KEYBOARD_BY_TEXT:
                    text_of_btn_to_click = local_input_("键盘中需要点击的按钮文本: ")
                    actions.append(ClickKeyboardByTextAction(text=text_of_btn_to_click))
                elif action == SupportAction.CHOOSE_OPTION_BY_IMAGE:
                    print_to_user(
                        "图片识别将使用大模型回答，请确保大模型支持图片识别。"
                    )
                    actions.append(ChooseOptionByImageAction())
                elif action == SupportAction.REPLY_BY_CALCULATION_PROBLEM:
                    print_to_user("计算题将使用大模型回答。")
                    actions.append(ReplyByCalculationProblemAction())
                elif action == SupportAction.REPLY_BY_IMAGE_RECOGNITION:
                    print_to_user("AI will recognize text from image and send it automatically.")
                    actions.append(ReplyByImageRecognitionAction())
                elif action == SupportAction.CLICK_BUTTON_BY_CALCULATION_PROBLEM:
                    print_to_user("AI will calculate the answer and click the matching button.")
                    actions.append(ClickButtonByCalculationProblemAction())
                else:
                    raise ValueError(f"不支持的动作: {action}")
                if local_input_("是否继续添加动作？(y/N)：").strip().lower() != "y":
                    break
            except (ValueError, ValidationError) as e:
                print_to_user("错误: ")
                print_to_user(e)
        input_.incr()
        return actions


    def ask_one(self) -> SignChatV3:
        input_ = UserInput(numbering_lang="chinese_simple")
        chat_id = int(input_("Chat ID（登录时最近对话输出中的ID）: "))
        name = input_("Chat名称（可选）: ")
        actions = self._ask_actions(input_)
        delete_after = (
            input_(
                "等待N秒后删除消息（发送消息后等待进行删除, '0'表示立即删除, 不需要删除直接回车）, N: "
            )
            or None
        )
        if delete_after:
            delete_after = int(delete_after)
        cfgs = {
            "chat_id": chat_id,
            "name": name,
            "delete_after": delete_after,
            "actions": actions,
        }

        return model_validate(SignChatV3, cfgs)


    def ask_for_config(self) -> "SignConfigV3":
        chats = []
        i = 1
        print_to_user(f"开始配置任务<{self.task_name}>\n")
        while True:
            print_to_user(f"第{i}个任务: ")
            try:
                chat = self.ask_one()
                print_to_user(chat)
                print_to_user(f"第{i}个任务配置成功\n")
                chats.append(chat)
            except Exception as e:
                print_to_user(e)
                print_to_user("配置失败")
                i -= 1
            continue_ = input("继续配置任务？(y/N)：")
            if continue_.strip().lower() != "y":
                break
            i += 1
        sign_at_prompt = "签到时间（time或crontab表达式，如'06:00:00'或'0 6 * * *'）: "
        sign_at_str = input(sign_at_prompt) or "06:00:00"
        while not (sign_at := self._validate_sign_at(sign_at_str)):
            print_to_user("请输入正确的时间格式")
            sign_at_str = input(sign_at_prompt) or "06:00:00"

        random_seconds_str = input("签到时间误差随机秒数（默认为0）: ") or "0"
        random_seconds = int(float(random_seconds_str))

        config = model_validate(
            SignConfigV3,
            {
                "chats": chats,
                "sign_at": sign_at,
                "random_seconds": random_seconds,
            }
        )
        if config.requires_ai:
            print_to_user(OPENAI_USE_PROMPT)
        return config

    @classmethod

    def _validate_sign_at(cls, sign_at_str: str) -> Optional[str]:
        sign_at_str = sign_at_str.replace("：", ":").strip()

        try:
            sign_at = dt_time.fromisoformat(sign_at_str)
            crontab_expr = cls._time_to_crontab(sign_at)
        except ValueError:
            try:
                croniter(sign_at_str)
                crontab_expr = sign_at_str
            except CroniterBadCronError:
                return None
        return crontab_expr

    @staticmethod
    def _time_to_crontab(sign_at: dt_time) -> str:
        return f"{sign_at.minute} {sign_at.hour} * * *"


    def load_sign_record(self):
        sign_record = {}
        if not self.sign_record_file.is_file():
            with open(self.sign_record_file, "w", encoding="utf-8") as fp:
                json.dump(sign_record, fp)
        else:
            with open(self.sign_record_file, "r", encoding="utf-8") as fp:
                sign_record = json.load(fp)
        return sign_record

    @staticmethod

    def _is_transient_step_error(exc: Exception) -> bool:
        """判断步骤级错误是否为瞬时故障（值得在当前步骤重试）。
        仅用于流程内步级重试，避免因单步瞬时失败而重启整个脚本流程。
        配额耗尽、计费限制等永久错误不视为瞬时故障。
        """
        if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
            return True
        text = str(exc).lower()
        # 永久错误优先排除，避免 "429 Too Many Requests: insufficient_quota" 被误判
        permanent_markers = (
            "quota exceeded",
            "resource_exhausted",
            "insufficient_quota",
            "billing hard limit",
            "out of quota",
            "exceeded your current quota",
            "check your plan and billing",
            "invalid api key",
            "invalid_request_error",
            "authentication",
            "permission denied",
        )
        if any(marker in text for marker in permanent_markers):
            return False
        transient_markers = (
            "timeout",
            "timed out",
            "connection reset",
            "connection refused",
            "connection aborted",
            "temporary failure",
            "service unavailable",
            "bad gateway",
            "gateway timeout",
            "too many requests",
            "rate limit",
            "floodwait",
            "flood_wait",
            "flood wait",
            "network is unreachable",
        )
        return any(marker in text for marker in transient_markers)


"""UserSigner（从 core 拆分）。"""
from __future__ import annotations

from tg_signer.core.worker import *  # noqa: F403

class UserSigner(BaseUserWorker[SignConfigV3]):
    _workdir = ".signer"
    _tasks_dir = "signs"
    cfg_cls = SignConfigV3
    context: UserSignerWorkerContext

    def ensure_ctx(self) -> UserSignerWorkerContext:
        return UserSignerWorkerContext(
            waiter=Waiter(),
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
        return SignChatV3.parse_obj(cfgs)

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
        config = SignConfigV3.parse_obj(
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
    def _time_to_crontab(sign_at: time) -> str:
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
                            f"Preheated peer with get_users: {chat.chat_id}",
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
                                    f"Preheated peer with cached username: {chat.chat_id} -> @{username}",
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
                                    f"Preheated peer with cached chat_id: {chat.chat_id} -> {cached_id}",
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
                                f"Preheated peer with fallback chat_id: {chat.chat_id} -> {candidate}",
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
                        f"Failed to preheat chat_id={chat.chat_id}, error={type(last_error).__name__}: {last_error}",
                        level="ERROR",
                    )
                    raise RuntimeError(
                        f"Failed to preheat chat_id {chat.chat_id}: {last_error}"
                    ) from last_error
            else:
                self.log(
                    f"预热会话失败: chat_id={chat.chat_id}, error={type(e).__name__}: {e}",
                    level="ERROR",
                )
                raise RuntimeError(
                    f"Failed to preheat chat_id {chat.chat_id}: {e}"
                ) from e
        self.log(self._describe_chat_run(chat))
        total_actions = len(chat.actions)
        if total_actions == 0:
            raise RuntimeError("任务没有配置任何执行动作")
        # 不扫历史预跳过：手动/定时均直接执行动作流；
        # 执行中由 bot 回调/新消息（已签到、签到成功等）触发 stop_after_current_action。
        max_flow_attempts = _read_positive_int_env("SIGN_TASK_FLOW_RETRY_ATTEMPTS", 1, 1)
        # 优先从上下文变量读取任务级重试次数，回退到环境变量读取结果
        try:
            from backend.services.sign_tasks import _task_retry_count_var
            _ctx_val = _task_retry_count_var.get()
            if _ctx_val and _ctx_val > 0:
                max_flow_attempts = _ctx_val
        except (ImportError, LookupError):
            pass
        retry_backoff_steps = _read_positive_int_env("SIGN_TASK_RETRY_BACKOFF_STEPS", 0, 0)
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
                    self.context.chat_messages[chat.chat_id].clear()
                self.context.stop_after_current_action = False
                self.context.stop_reason = None
                self.context.last_callback_answer = None
                for index in range(start_index, total_actions + 1):
                    action = chat.actions[index - 1]
                    action_description = self._set_current_action_context(
                        index,
                        total_actions,
                        action,
                    )
                    action_delay = self._resolve_action_delay(
                        action,
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
                        # 步级重试：对瞬时错误（AI 超时、网络抖动等）在当前步骤内重试一次，
                        # 避免升级为流程级重试导致已完成的步骤（如 /checkin）被重复执行。
                        # 总尝试 2 次（1 次首次 + 1 次重试），与 AI 工具层内部重试不叠加过度。
                        _step_max_retries = 2
                        for _step_attempt in range(1, _step_max_retries + 1):
                            try:
                                result = await self.wait_for(
                                    chat,
                                    action,
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
                                raise
                        if result is False:
                            raise RuntimeError(
                                f"{self._current_action_step_label()}执行失败：{action_description}"
                            )
                        self.log(
                            f"{self._current_action_step_label()}执行完成：{action_description}"
                        )
                        last_successful_index = index
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
                await asyncio.sleep(max(float(chat.action_interval or 0), 1.0))

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
            raise RuntimeError("Task config has no chats to execute")

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
                            except ConnectionError:
                                # Already terminated - ignore
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
                await asyncio.sleep((next_run - now).total_seconds())
        finally:
            # Always clean up handlers, even on exception
            if message_handler_ref:
                try:
                    self.app.remove_handler(*message_handler_ref)
                except Exception:
                    pass
            if edited_handler_ref:
                try:
                    self.app.remove_handler(*edited_handler_ref)
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

    def _clean_text_for_match(self, text: str) -> str:
        if not text:
            return ""
        text = unicodedata.normalize("NFKC", str(text))
        return "".join(
            ch
            for ch in text.lower()
            if not unicodedata.category(ch).startswith(("P", "S", "Z", "C"))
        )

    def _button_text_matches(self, target_text: str, button_text: str) -> bool:
        if not target_text or not button_text:
            return False
        if target_text == button_text or target_text in button_text:
            return True
        return len(button_text) >= 2 and button_text in target_text

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
        target_text = self._clean_text_for_match(text)
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
                button_text = (
                    button if isinstance(button, str) else getattr(button, "text", "")
                )
                if not button_text:
                    continue
                if self._button_text_matches(
                    target_text,
                    self._clean_text_for_match(button_text),
                ):
                    return True
        return False

    def _resolve_message_thread_id(self, message: Message) -> Optional[int]:
        return getattr(message, "message_thread_id", None) or getattr(
            message, "reply_to_top_message_id", None
        )

    def _collect_clickable_buttons(self, message: Message) -> list[tuple[str, Any, str]]:
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
                    button_text = (
                        button if isinstance(button, str) else getattr(button, "text", "")
                    )
                    if button_text:
                        clickable_buttons.append(("reply", button, button_text))
        return clickable_buttons

    def _message_supports_next_action(self, action: ActionT, message: Message) -> bool:
        if message is None:
            return False
        reply_markup = getattr(message, "reply_markup", None)
        if isinstance(action, ClickKeyboardByTextAction):
            return self._message_has_button_text(message, action.text)
        if isinstance(action, ChooseOptionByImageAction):
            return bool(message.photo and self._collect_clickable_buttons(message))
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
            for args, kwargs in (
                ((getattr(btn, "text", None),), {}),
                ((), {"text": getattr(btn, "text", None)}),
            ):
                try:
                    await click(*args, **kwargs)
                    self.log("点击完成")
                    return True
                except TypeError:
                    continue
                except Exception as e:
                    if _is_callback_data_invalid(e):
                        self.log(
                            "Message.click 也无法确认按钮回调，继续等待机器人后续消息确认",
                            level="WARNING",
                        )
                    else:
                        self.log(f"Message.click 无法确认按钮回调: {e}", level="WARNING")
                    break

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
        target_text = self._clean_text_for_match(action.text)
        if not target_text:
            self.log("Click button action has empty target text after cleaning", level="WARNING")
            return False, False

        if reply_markup := message.reply_markup:
            if isinstance(reply_markup, InlineKeyboardMarkup):
                flat_buttons = (b for row in reply_markup.inline_keyboard for b in row)
                for btn in flat_buttons:
                    if not btn.text:
                        continue
                    btn_text_clean = self._clean_text_for_match(btn.text)
                    if self._button_text_matches(target_text, btn_text_clean):
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
                        btn_text_clean = self._clean_text_for_match(btn_text)
                        if self._button_text_matches(target_text, btn_text_clean):
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
            self.log(f"AI 请求 | {safe_ai_request_meta(method='calculate_problem', model=model, query_chars=len(message.text), custom_prompt=bool(ai_prompt), question_preview=message.text)}")
            _start = time.monotonic()
            try:
                answer = await self.get_ai_tools().calculate_problem(
                    message.text,
                    system_prompt=ai_prompt,
                )
                _elapsed = (time.monotonic() - _start) * 1000
                answer = (answer or "").strip()
                self.log(f"AI 响应 | {safe_ai_result_meta(method='calculate_problem', model=model, elapsed_ms=_elapsed, response_chars=len(answer), selected_options=[answer] if answer else [])}")
            except Exception as e:
                _elapsed = (time.monotonic() - _start) * 1000
                self.log(f"AI 调用失败 | method=calculate_problem model={model} elapsed_ms={_elapsed:.0f} error={type(e).__name__}: {safe_text_preview(e, 200)}", level="ERROR")
                raise
            if not answer:
                self.log("AI 未返回有效答案", level="WARNING")
                return False
            self.log(f"AI 计算完成 | answer_chars={len(answer)} | 预览: {safe_text_preview(answer, 80)}", level="DEBUG")
            await self.send_message(message.chat.id, answer)
            return True
        return False

    async def _reply_by_image_recognition(
        self, action: ReplyByImageRecognitionAction, message
    ):
        if not message.photo:
            return False
        if self._collect_clickable_buttons(message):
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
        self.log(f"AI 请求 | {safe_ai_request_meta(method='extract_text_by_image', model=model, has_image=True, image_bytes=len(image_bytes), custom_prompt=bool(ai_prompt))}")
        _start = time.monotonic()
        try:
            text = await self.get_ai_tools().extract_text_by_image(
                image_bytes,
                system_prompt=ai_prompt,
            )
            _elapsed = (time.monotonic() - _start) * 1000
            text = (text or "").strip()
            self.log(f"AI 响应 | {safe_ai_result_meta(method='extract_text_by_image', model=model, elapsed_ms=_elapsed, response_chars=len(text), selected_options=[text] if text else [])}")
        except Exception as e:
            _elapsed = (time.monotonic() - _start) * 1000
            self.log(f"AI 调用失败 | method=extract_text_by_image model={model} elapsed_ms={_elapsed:.0f} error={type(e).__name__}: {safe_text_preview(e, 200)}", level="ERROR")
            raise
        if not text:
            self.log("AI 未识别到可发送文本", level="WARNING")
            return False
        self.log(f"AI OCR 完成 | text_chars={len(text)} | 预览: {safe_text_preview(text, 80)}", level="DEBUG")
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
        self.log(f"AI 请求 | {safe_ai_request_meta(method='calculate_problem', model=model, query_chars=len(message.text), custom_prompt=bool(ai_prompt), question_preview=message.text)}")
        _start = time.monotonic()
        try:
            answer = await self.get_ai_tools().calculate_problem(
                message.text,
                system_prompt=ai_prompt,
            )
            _elapsed = (time.monotonic() - _start) * 1000
            answer = (answer or "").strip()
            self.log(f"AI 响应 | {safe_ai_result_meta(method='calculate_problem', model=model, elapsed_ms=_elapsed, response_chars=len(answer), selected_options=[answer] if answer else [])}")
        except Exception as e:
            _elapsed = (time.monotonic() - _start) * 1000
            self.log(f"AI 调用失败 | method=calculate_problem model={model} elapsed_ms={_elapsed:.0f} error={type(e).__name__}: {safe_text_preview(e, 200)}", level="ERROR")
            raise
        if not answer:
            self.log("AI 未返回可用于点击的答案", level="WARNING")
            return False
        self.log(f"AI 计算完成 | answer_chars={len(answer)} | 预览: {safe_text_preview(answer, 80)}", level="DEBUG")
        proxy_action = ClickKeyboardByTextAction(text=answer)
        return await self._click_keyboard_by_text(proxy_action, message)

    async def _choose_option_by_image(self, action: ChooseOptionByImageAction, message):
        if not message.photo:
            return False
        clickable_buttons = self._collect_clickable_buttons(message)
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
            self.log(f"AI 请求 | {safe_ai_request_meta(method='choose_options_by_image', model=model, has_image=True, image_bytes=len(image_bytes), query_chars=len(question_text), options_count=len(options), custom_prompt=bool(ai_prompt), question_preview=question_text, options_preview=options)}")
            _start = time.monotonic()
            try:
                result_indexes = await self.get_ai_tools().choose_options_by_image(
                    image_bytes,
                    question_text,
                    list(enumerate(options, start=1)),
                    system_prompt=ai_prompt,
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
                self.log(f"AI 响应 | {safe_ai_result_meta(method='choose_options_by_image', model=model, elapsed_ms=_elapsed, result_type='list', result_count=len(result_indexes or []), selected_options=selected_options)}")
            except Exception as e:
                _elapsed = (time.monotonic() - _start) * 1000
                self.log(f"AI 调用失败 | method=choose_options_by_image model={model} elapsed_ms={_elapsed:.0f} error={type(e).__name__}: {safe_text_preview(e, 200)}", level="ERROR")
                raise
            if not result_indexes:
                self.log("AI 未返回可点击选项", level="WARNING")
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
            timeout = _read_positive_float_env("SIGN_TASK_ACTION_TIMEOUT", 25.0, 5.0)
        kwargs = {}
        if chat.message_thread_id is not None:
            kwargs["message_thread_id"] = chat.message_thread_id
        if isinstance(action, SendTextAction):
            return await self.send_message(chat.chat_id, action.text, chat.delete_after, **kwargs)
        elif isinstance(action, SendDiceAction):
            return await self.send_dice(chat.chat_id, action.dice, chat.delete_after, **kwargs)
        elif isinstance(action, KeywordNotifyAction):
            self.log("关键词监听通知动作为后台常驻监听配置，当前运行时跳过")
            return True
        history_limit = _read_positive_int_env("SIGN_TASK_HISTORY_LOOKBACK", 12, 3)
        self.context.waiter.add(chat.chat_id)
        start = time.perf_counter()
        last_message = None
        self.context.last_callback_answer = None
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
            self.context.waiter.discard(chat.chat_id)
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
                backoff = min(2**attempt, 8)
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



"""Telegram Bot 双向 ChatOps 运维机器人服务。

支持通过 Telegram 聊天窗口直接管理与监控系统：
- /status: 查看系统总览与运行状态
- /tasks: 列出可用任务
- /run <task_name>: 触发任务立即运行
- /cooldown: 查看处于 FloodWait 限频冷却中的账号
- /help: 查看帮助说明
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import re
from typing import Any, Dict, Optional

import httpx

from backend.services.flood_backoff import get_flood_backoff_manager
from backend.services.push_notifications import (
    _html_escape,
    sanitize_push_error,
    send_telegram_bot_message,
)

logger = logging.getLogger("backend.chatops_bot")


def _parse_admin_user_ids(raw: Any) -> set[str]:
    """解析管理员 user_id 白名单（逗号/分号/空白分隔）。"""
    if not raw:
        return set()
    if isinstance(raw, (list, tuple, set)):
        parts = [str(item) for item in raw]
    else:
        parts = re.split(r"[;,;\s]+", str(raw))
    return {p.strip() for p in parts if p and p.strip()}


def _extract_sender_user_id(message: dict) -> str:
    """从 Telegram Update 的 message 中取出发送者 user_id（字符串形式，空串表示缺失）。"""
    sender = message.get("from") or {}
    if not isinstance(sender, dict):
        return ""
    user_id = sender.get("id")
    if user_id is None or user_id == "":
        return ""
    return str(user_id).strip()


def _extract_telegram_retry_after(resp: Any) -> Optional[float]:
    """安全解析 Telegram API 响应中的 retry_after 秒数（支持 HTTP 429 与 JSON ok=False 载荷）。"""
    try:
        data = resp.json()
        if isinstance(data, dict):
            params = data.get("parameters")
            if isinstance(params, dict):
                val = params.get("retry_after")
                if isinstance(val, (int, float)) and val > 0:
                    return min(float(val), 300.0)
    except Exception:
        pass
    if hasattr(resp, "headers") and resp.headers:
        header_val = resp.headers.get("Retry-After")
        if header_val:
            try:
                sec = float(header_val)
                if sec > 0:
                    return min(sec, 300.0)
            except ValueError:
                pass
    return None


class TelegramChatOpsWorker:
    """基于 Telegram getUpdates 的轻量非阻塞 ChatOps 服务。"""

    def __init__(self) -> None:
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_update_id: int = 0
        self._background_tasks: set[asyncio.Task] = set()

    def _on_background_task_done(self, task: asyncio.Task) -> None:
        """后台任务执行完毕回调：清理强引用并安全检索异常，避免日志泄露或异常丢失。"""
        self._background_tasks.discard(task)
        try:
            exc = task.exception()
            if exc and not isinstance(exc, asyncio.CancelledError):
                logger.warning("ChatOps 后台任务执行异常: %s", sanitize_push_error(exc))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("ChatOps 检索后台任务异常失败: %s", sanitize_push_error(e))

    async def handle_command(
        self,
        bot_token: str,
        chat_id: str,
        text: str,
        settings: Dict[str, Any],
    ) -> None:
        """处理解析收到的命令。"""
        parts = text.strip().split()
        if not parts:
            return
        cmd = parts[0].lower()
        if "@" in cmd:
            cmd = cmd.split("@")[0]

        if cmd in ("/start", "/help"):
            reply = (
                "🤖 <b>TG-SignPulse ChatOps 指令指南</b>\n\n"
                "• <code>/status</code>: 查看系统运行状态与总览\n"
                "• <code>/tasks</code>: 查看已启用的任务列表\n"
                "• <code>/cooldown</code>: 查看处于限频冷却保护中的账号\n"
                "• <code>/run &lt;task_name&gt;</code>: 立即触发指定任务执行\n"
                "• <code>/ping</code>: 测试 ChatOps 机器人连通性\n"
                "• <code>/help</code>: 显示此帮助信息"
            )
            await send_telegram_bot_message(
                bot_token=bot_token, chat_id=chat_id, text=reply, parse_mode="HTML"
            )
            return

        if cmd == "/status":
            from backend.services.sign_tasks import get_sign_task_service
            from backend.services.telegram import get_telegram_service

            svc = get_sign_task_service()
            acc_svc = get_telegram_service()
            all_accounts = acc_svc.list_accounts()
            all_tasks = svc.list_tasks()
            active_runs = svc.list_active_runs()
            cooling = get_flood_backoff_manager().get_all_cooling_accounts()

            reply = (
                "📊 <b>TG-SignPulse 系统运行状态</b>\n\n"
                f"• <b>总账号数</b>: <code>{len(all_accounts)}</code>\n"
                f"• <b>总任务数</b>: <code>{len(all_tasks)}</code>\n"
                f"• <b>活跃运行中任务</b>: <code>{len(active_runs)}</code>\n"
                f"• <b>FloodWait 保护账号</b>: <code>{len(cooling)}</code>\n"
            )
            if active_runs:
                reply += "\n<b>正在运行:</b>\n"
                for r in active_runs[:5]:
                    reply += (
                        f"• <code>{_html_escape(r.get('task_name'))}</code> "
                        f"({_html_escape(r.get('account_name'))})\n"
                    )

            await send_telegram_bot_message(
                bot_token=bot_token, chat_id=chat_id, text=reply, parse_mode="HTML"
            )
            return

        if cmd == "/tasks":
            from backend.services.sign_tasks import get_sign_task_service

            svc = get_sign_task_service()
            all_tasks = svc.list_tasks()
            enabled_tasks = [t for t in all_tasks if t.get("enabled", True)]

            if not enabled_tasks:
                reply = "ℹ️ 当前没有启用的签到任务。"
            else:
                reply = f"📋 <b>已启用任务列表 ({len(enabled_tasks)}):</b>\n\n"
                for t in enabled_tasks[:20]:
                    name = t.get("name", "未命名")
                    acc = t.get("account_name") or "通用"
                    reply += (
                        f"• <code>{_html_escape(name)}</code> ({_html_escape(acc)})\n"
                    )
                if len(enabled_tasks) > 20:
                    reply += f"\n<i>...以及另外 {len(enabled_tasks) - 20} 个任务</i>"

            await send_telegram_bot_message(
                bot_token=bot_token, chat_id=chat_id, text=reply, parse_mode="HTML"
            )
            return

        if cmd == "/cooldown":
            cooling = get_flood_backoff_manager().get_all_cooling_accounts()
            if not cooling:
                reply = "✅ 当前没有账号处于 FloodWait 限频冷却状态。"
            else:
                reply = f"⏳ <b>处于限频退避中的账号 ({len(cooling)}):</b>\n\n"
                for acc, info in cooling.items():
                    rem = info.get("remaining_seconds", 0)
                    reason = info.get("reason", "未知原因")
                    reply += (
                        f"• <b>{_html_escape(acc)}</b>: 剩余 <code>{rem}s</code> "
                        f"({_html_escape(reason)})\n"
                    )

            await send_telegram_bot_message(
                bot_token=bot_token, chat_id=chat_id, text=reply, parse_mode="HTML"
            )
            return

        if cmd == "/run":
            if len(parts) < 2:
                reply = "⚠️ 请指定任务名称，例如: <code>/run 每日签到</code>"
                await send_telegram_bot_message(
                    bot_token=bot_token, chat_id=chat_id, text=reply, parse_mode="HTML"
                )
                return

            target_task = parts[1]
            from backend.services.sign_tasks import get_sign_task_service

            svc = get_sign_task_service()
            all_tasks = svc.list_tasks()
            matched = [
                t
                for t in all_tasks
                if t.get("name") == target_task and t.get("enabled", True)
            ]
            if not matched:
                reply = f"❌ 未找到名称为 <code>{_html_escape(target_task)}</code> 的已启用任务。"
                await send_telegram_bot_message(
                    bot_token=bot_token, chat_id=chat_id, text=reply, parse_mode="HTML"
                )
                return

            # 触发后台执行，保持强引用并注册异常回收
            task_obj = matched[0]
            acc_name = (
                task_obj.get("account_name")
                or (task_obj.get("account_names") or [""])[0]
            )
            if not acc_name:
                reply = (
                    f"❌ 任务 <code>{_html_escape(target_task)}</code> 未关联有效账号。"
                )
                await send_telegram_bot_message(
                    bot_token=bot_token, chat_id=chat_id, text=reply, parse_mode="HTML"
                )
                return

            bg_task = asyncio.create_task(svc.run_task_with_logs(acc_name, target_task))
            self._background_tasks.add(bg_task)
            bg_task.add_done_callback(self._on_background_task_done)

            reply = (
                "🚀 <b>已触发任务执行</b>\n\n"
                f"• 任务: <code>{_html_escape(target_task)}</code>\n"
                f"• 账号: <code>{_html_escape(acc_name)}</code>\n"
                "结果将在完成后推送通知。"
            )
            await send_telegram_bot_message(
                bot_token=bot_token, chat_id=chat_id, text=reply, parse_mode="HTML"
            )
            return

        if cmd == "/ping":
            reply = "🏓 <b>Pong!</b> TG-SignPulse ChatOps 服务运行正常。"
            await send_telegram_bot_message(
                bot_token=bot_token, chat_id=chat_id, text=reply, parse_mode="HTML"
            )
            return

        if cmd.startswith("/"):
            reply = (
                f"❓ 未知指令 <code>{_html_escape(cmd)}</code>。\n\n"
                "输入 <code>/help</code> 查看可用指令列表。"
            )
            await send_telegram_bot_message(
                bot_token=bot_token, chat_id=chat_id, text=reply, parse_mode="HTML"
            )
            return

    async def _poll_loop(self) -> None:
        """非阻塞轮询 Telegram Updates，复用长连接池（支持动态代理、429 指数退避与热切换）。"""
        current_proxy: Optional[str] = None
        client: Optional[httpx.AsyncClient] = None
        consecutive_failures: int = 0
        try:
            while self._running:
                try:
                    from backend.services.config import get_config_service
                    from backend.utils.proxy import format_proxy_url

                    cfg_svc = get_config_service()
                    settings = cfg_svc.get_global_settings()

                    bot_token = (settings.get("telegram_bot_token") or "").strip()
                    allowed_chat_id = str(
                        settings.get("telegram_bot_chat_id") or ""
                    ).strip()
                    # 默认关闭：未显式配置 chatops_enabled 时按未启用处理（fail-closed）
                    chatops_enabled = settings.get(
                        "telegram_bot_chatops_enabled", False
                    )

                    if not bot_token or not allowed_chat_id or not chatops_enabled:
                        if client is not None and not getattr(
                            client, "is_closed", True
                        ):
                            await client.aclose()
                            client = None
                            current_proxy = None
                        consecutive_failures = 0
                        await asyncio.sleep(10.0)
                        continue

                    needed_proxy = format_proxy_url(cfg_svc.get_global_proxy())
                    if (
                        client is None
                        or getattr(client, "is_closed", True)
                        or current_proxy != needed_proxy
                    ):
                        if client is not None and not getattr(
                            client, "is_closed", True
                        ):
                            await client.aclose()
                        client = httpx.AsyncClient(proxy=needed_proxy, timeout=35.0)
                        current_proxy = needed_proxy
                        consecutive_failures = 0

                    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
                    params = {
                        "offset": self._last_update_id + 1,
                        "timeout": 20,
                        "allowed_updates": ["message"],
                    }

                    resp = await client.get(url, params=params)

                    # 检查 HTTP 429 状态码
                    if resp.status_code == 429:
                        consecutive_failures += 1
                        retry_after = _extract_telegram_retry_after(resp) or 5.0
                        logger.warning(
                            "Telegram getUpdates 触发 429 频控，退避等待 %.1f 秒",
                            retry_after,
                        )
                        await asyncio.sleep(retry_after)
                        continue

                    if resp.status_code == 200:
                        data = resp.json()
                        # 检查业务层 ok=False 与 error_code=429
                        if data.get("ok") is False:
                            consecutive_failures += 1
                            if data.get("error_code") == 429:
                                retry_after = _extract_telegram_retry_after(resp) or 5.0
                                logger.warning(
                                    "Telegram API 返回 429 限流，退避等待 %.1f 秒",
                                    retry_after,
                                )
                                await asyncio.sleep(retry_after)
                                continue
                            backoff = min(
                                30.0, 1.0 * (2 ** min(consecutive_failures, 5))
                            )
                            jitter = random.uniform(0.1, 1.0)
                            sleep_time = min(30.0, backoff + jitter)
                            err_code = data.get("error_code")
                            err_desc = sanitize_push_error(
                                str(data.get("description") or "")
                            )
                            logger.warning(
                                "Telegram API 返回业务错误 [code=%s]: %s，退避 %.1f 秒",
                                err_code,
                                err_desc,
                                sleep_time,
                            )
                            await asyncio.sleep(sleep_time)
                            continue

                        consecutive_failures = 0
                        updates = data.get("result") or []
                        for u in updates:
                            update_id = u.get("update_id", 0)
                            if update_id > self._last_update_id:
                                self._last_update_id = update_id

                            msg = u.get("message") or {}
                            chat = msg.get("chat") or {}
                            chat_id = str(chat.get("id") or "")
                            text = msg.get("text") or ""

                            # 鉴权必须同时满足容器与发送者两个维度：
                            # chat_id 匹配只证明消息来自管理员的会话容器，
                            # 同群/同频道的任何成员都能在其中发言，
                            # 故还需校验发送者 user_id 在白名单内。
                            sender_id = _extract_sender_user_id(msg)
                            allowed_sender_ids = _parse_admin_user_ids(
                                settings.get("telegram_bot_admin_user_ids")
                            )
                            if (
                                chat_id == allowed_chat_id
                                and text.startswith("/")
                                and sender_id
                                and sender_id in allowed_sender_ids
                            ):
                                try:
                                    await self.handle_command(
                                        bot_token, chat_id, text, settings
                                    )
                                except Exception as exc:
                                    # 命令处理可能抛出含 Bot Token URL 的推送异常，脱敏后再落日志
                                    logger.warning(
                                        "处理 ChatOps 命令 [%s] 出错: %s",
                                        text,
                                        sanitize_push_error(exc),
                                    )
                            elif chat_id == allowed_chat_id and text.startswith("/"):
                                logger.warning(
                                    "拒绝非白名单发送者的 ChatOps 命令: chat_id=%s sender_id=%s",
                                    chat_id,
                                    sender_id or "<缺失>",
                                )
                    else:
                        consecutive_failures += 1
                        backoff = min(30.0, 1.0 * (2 ** min(consecutive_failures, 5)))
                        jitter = random.uniform(0.1, 1.0)
                        sleep_time = min(30.0, backoff + jitter)
                        logger.debug(
                            "Telegram getUpdates 返回非 200 状态码 (%d)，退避 %.1f 秒",
                            resp.status_code,
                            sleep_time,
                        )
                        await asyncio.sleep(sleep_time)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    consecutive_failures += 1
                    backoff = min(30.0, 1.0 * (2 ** min(consecutive_failures, 5)))
                    jitter = random.uniform(0.1, 1.0)
                    sleep_time = min(30.0, backoff + jitter)
                    logger.debug(
                        "ChatOps 轮询异常: %s，退避 %.1f 秒",
                        sanitize_push_error(e),
                        sleep_time,
                    )
                    await asyncio.sleep(sleep_time)
        finally:
            if client is not None and not getattr(client, "is_closed", True):
                try:
                    await client.aclose()
                except Exception:
                    pass

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Telegram ChatOps 服务已启动")

    async def stop(self, timeout: float = 15.0) -> None:
        """异步停止 ChatOps 服务并优雅清理轮询与后台任务。"""
        self._running = False
        if self._task:
            if not self._task.done():
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    try:
                        await asyncio.wait_for(self._task, timeout=5.0)
                    except (asyncio.TimeoutError, Exception):
                        pass
            else:
                # 已结束的任务：仅在未取消时取回异常，避免 "never retrieved" 告警
                # CancelledError 属 BaseException，suppress(Exception) 无法捕获
                if not self._task.cancelled():
                    with contextlib.suppress(Exception):
                        self._task.exception()
        # 取消正在执行的 ChatOps 后台任务
        active_tasks = [t for t in self._background_tasks if not t.done()]
        for t in active_tasks:
            t.cancel()
        if active_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*active_tasks, return_exceptions=True),
                    timeout=max(1.0, timeout),
                )
            except (asyncio.TimeoutError, Exception) as exc:
                logger.debug(
                    "ChatOps 等待后台任务超时或异常: %s", sanitize_push_error(exc)
                )
        self._background_tasks.clear()
        logger.info("Telegram ChatOps 服务已停止")

    def stop_sync(self) -> None:
        """向后兼容的同步停止入口。"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        for t in list(self._background_tasks):
            if not t.done():
                t.cancel()
        self._background_tasks.clear()
        logger.info("Telegram ChatOps 服务已停止")


# 单例
_chatops_worker: Optional[TelegramChatOpsWorker] = None


def get_chatops_worker() -> TelegramChatOpsWorker:
    global _chatops_worker
    if _chatops_worker is None:
        _chatops_worker = TelegramChatOpsWorker()
    return _chatops_worker

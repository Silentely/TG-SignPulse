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
import logging
from typing import Any, Dict, Optional

import httpx

from backend.services.flood_backoff import get_flood_backoff_manager
from backend.services.push_notifications import send_telegram_bot_message

logger = logging.getLogger("backend.chatops_bot")


class TelegramChatOpsWorker:
    """基于 Telegram getUpdates 的轻量非阻塞 ChatOps 服务。"""

    def __init__(self) -> None:
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_update_id: int = 0

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
                "• <code>/help</code>: 显示此帮助信息"
            )
            await send_telegram_bot_message(bot_token=bot_token, chat_id=chat_id, text=reply, parse_mode="HTML")
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
                    reply += f"• <code>{r.get('task_name')}</code> ({r.get('account_name')})\n"

            await send_telegram_bot_message(bot_token=bot_token, chat_id=chat_id, text=reply, parse_mode="HTML")
            return

        if cmd == "/tasks":
            from backend.services.sign_tasks import get_sign_task_service
            tasks = get_sign_task_service().list_tasks()
            if not tasks:
                reply = "暂无任务配置。"
            else:
                reply = "📋 <b>任务列表:</b>\n\n"
                for t in tasks[:15]:
                    name = t.get("name") or "-"
                    status = "✅ 启用" if t.get("enabled", True) else "⏸️ 禁用"
                    mode = t.get("execution_mode") or "fixed"
                    reply += f"• <code>{name}</code> [{status}] ({mode})\n"
                if len(tasks) > 15:
                    reply += f"\n<i>...以及其余 {len(tasks) - 15} 个任务</i>"

            await send_telegram_bot_message(bot_token=bot_token, chat_id=chat_id, text=reply, parse_mode="HTML")
            return

        if cmd == "/cooldown":
            cooling = get_flood_backoff_manager().get_all_cooling_accounts()
            if not cooling:
                reply = "🛡️ 当前没有任何账号处于 FloodWait 限频冷却中，运行状态良好。"
            else:
                reply = "⏳ <b>处于限频退避保护中的账号:</b>\n\n"
                for name, info in cooling.items():
                    reply += f"• <b>{name}</b>: 剩余 <code>{info['remaining_seconds']}</code> 秒 ({info['reason']})\n"

            await send_telegram_bot_message(bot_token=bot_token, chat_id=chat_id, text=reply, parse_mode="HTML")
            return

        if cmd == "/run":
            if len(parts) < 2:
                reply = "⚠️ 请指定任务名称，例如: <code>/run my_task</code>"
                await send_telegram_bot_message(bot_token=bot_token, chat_id=chat_id, text=reply, parse_mode="HTML")
                return
            target_task = parts[1]
            from backend.services.sign_tasks import get_sign_task_service
            svc = get_sign_task_service()
            matched = [t for t in svc.list_tasks() if t.get("name") == target_task]
            if not matched:
                reply = f"❌ 未找到名为 <code>{target_task}</code> 的任务。使用 <code>/tasks</code> 查看可用列表。"
                await send_telegram_bot_message(bot_token=bot_token, chat_id=chat_id, text=reply, parse_mode="HTML")
                return

            # 触发后台执行
            task_obj = matched[0]
            acc_name = task_obj.get("account_name") or (task_obj.get("account_names") or [""])[0]
            if not acc_name:
                reply = f"❌ 任务 <code>{target_task}</code> 未关联有效账号。"
                await send_telegram_bot_message(bot_token=bot_token, chat_id=chat_id, text=reply, parse_mode="HTML")
                return

            asyncio.create_task(svc.run_task_with_logs(acc_name, target_task))
            reply = f"🚀 <b>已触发任务执行</b>\n\n• 任务: <code>{target_task}</code>\n• 账号: <code>{acc_name}</code>\n结果将在完成后推送通知。"
            await send_telegram_bot_message(bot_token=bot_token, chat_id=chat_id, text=reply, parse_mode="HTML")
            return

    async def _poll_loop(self) -> None:
        """非阻塞轮询 Telegram Updates，复用长连接池（支持动态代理与热切换）。"""
        current_proxy: Optional[str] = None
        client: Optional[httpx.AsyncClient] = None
        try:
            while self._running:
                try:
                    from backend.services.config import get_config_service
                    from backend.utils.proxy import format_proxy_url

                    cfg_svc = get_config_service()
                    settings = cfg_svc.get_global_settings()

                    bot_token = (settings.get("telegram_bot_token") or "").strip()
                    allowed_chat_id = str(settings.get("telegram_bot_chat_id") or "").strip()
                    chatops_enabled = settings.get("telegram_bot_chatops_enabled", True)

                    if not bot_token or not allowed_chat_id or not chatops_enabled:
                        if client is not None and not getattr(client, "is_closed", True):
                            await client.aclose()
                            client = None
                            current_proxy = None
                        await asyncio.sleep(10.0)
                        continue

                    needed_proxy = format_proxy_url(cfg_svc.get_global_proxy())
                    if client is None or getattr(client, "is_closed", True) or current_proxy != needed_proxy:
                        if client is not None and not getattr(client, "is_closed", True):
                            await client.aclose()
                        client = httpx.AsyncClient(proxy=needed_proxy, timeout=35.0)
                        current_proxy = needed_proxy

                    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
                    params = {
                        "offset": self._last_update_id + 1,
                        "timeout": 20,
                        "allowed_updates": ["message"],
                    }

                    resp = await client.get(url, params=params)
                    if resp.status_code == 200:
                        data = resp.json()
                        updates = data.get("result") or []
                        for u in updates:
                            update_id = u.get("update_id", 0)
                            if update_id > self._last_update_id:
                                self._last_update_id = update_id

                            msg = u.get("message") or {}
                            chat = msg.get("chat") or {}
                            chat_id = str(chat.get("id") or "")
                            text = msg.get("text") or ""

                            # 鉴权：严格校验发送方 chat_id 是否与配置的管理员 chat_id 一致
                            if chat_id == allowed_chat_id and text.startswith("/"):
                                try:
                                    await self.handle_command(bot_token, chat_id, text, settings)
                                except Exception as exc:
                                    logger.warning("处理 ChatOps 命令 [%s] 出错: %s", text, exc)
                    else:
                        await asyncio.sleep(5.0)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.debug("ChatOps 轮询异常: %s", e)
                    await asyncio.sleep(5.0)
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

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("Telegram ChatOps 服务已停止")


# 单例
_chatops_worker: Optional[TelegramChatOpsWorker] = None


def get_chatops_worker() -> TelegramChatOpsWorker:
    global _chatops_worker
    if _chatops_worker is None:
        _chatops_worker = TelegramChatOpsWorker()
    return _chatops_worker

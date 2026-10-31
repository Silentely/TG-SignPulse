"""TG-SignPulse Community Plugin: Chat Cleaner."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from tg_signer.core.plugins import (
    PluginContext,
    PluginMessageNotFoundError,
    PluginRegistry,
)

VERSION = "1.0.0"
AUTHOR = "TG-SignPulse"

PARAMS_SCHEMA: List[Dict[str, Any]] = [
    {
        "name": "delay_seconds",
        "label": "清理延迟秒数",
        "type": "number",
        "default": 3.0,
        "required": False,
        "description": "清理消息前的等待缓冲时间（秒）",
    },
    {
        "name": "delete_bot_reply",
        "label": "删除 Bot 回复",
        "type": "boolean",
        "default": True,
        "required": False,
        "description": "是否删除 Bot 响应发出的消息",
    },
    {
        "name": "delete_trigger_command",
        "label": "删除触发口令",
        "type": "boolean",
        "default": True,
        "required": False,
        "description": "是否删除用户发送的签到/触发命令消息",
    },
]


@PluginRegistry.register(
    name="chat_cleaner",
    mode="reactive",
    description="在响应式任务末尾自动延迟清理用户触发口令与 Bot 回复消息，保持聊天会话整洁。",
    version=VERSION,
    author=AUTHOR,
    context_version=2,
    plugin_api="2.0",
    min_app_version="1.9.0",
    permissions=["telegram_send"],
    params_schema=PARAMS_SCHEMA,
)
async def handle_chat_cleaner(ctx: PluginContext) -> bool:
    """Reactive plugin: cleans up bot reply and trigger command message after delay."""
    if not ctx.message:
        ctx.log("[chat_cleaner] 当前上下文中无消息，跳过清理")
        return True

    params = ctx.params or {}
    try:
        delay_seconds = float(params.get("delay_seconds", 3.0) or 0.0)
    except (ValueError, TypeError):
        delay_seconds = 3.0

    delete_bot_reply = bool(params.get("delete_bot_reply", True))
    delete_trigger = bool(params.get("delete_trigger_command", True))

    if delay_seconds > 0:
        clamped_delay = max(0.0, min(300.0, delay_seconds))
        ctx.log(f"[chat_cleaner] 缓冲等待 {clamped_delay} 秒后开始清理消息痕迹...")
        await asyncio.sleep(clamped_delay)

    # 1. Delete bot reply
    bot_msg_id = getattr(ctx.message, "id", None)
    if delete_bot_reply and bot_msg_id:
        try:
            await ctx.delete_message(message_id=bot_msg_id)
            ctx.log(f"[chat_cleaner] 成功清理 Bot 回复消息: {bot_msg_id}")
        except PluginMessageNotFoundError:
            ctx.log(
                f"[chat_cleaner] Bot 回复消息 {bot_msg_id} 已不存在或已删除，安全忽略"
            )
        except Exception as exc:
            ctx.log(f"[chat_cleaner] 清理 Bot 回复消息异常: {exc}", level="WARNING")

    # 2. Delete user trigger command
    trigger_id = getattr(ctx.message, "reply_to_message_id", None)
    if delete_trigger:
        if trigger_id:
            try:
                await ctx.delete_message(message_id=trigger_id)
                ctx.log(f"[chat_cleaner] 成功清理触发命令消息: {trigger_id}")
            except PluginMessageNotFoundError:
                ctx.log(
                    f"[chat_cleaner] 触发命令消息 {trigger_id} 已不存在或已删除，安全忽略"
                )
            except Exception as exc:
                ctx.log(f"[chat_cleaner] 清理触发命令消息异常: {exc}", level="WARNING")
        else:
            ctx.log(
                "[chat_cleaner] 未检测到关联的触发口令消息 (reply_to_message_id 为空)"
            )

    return True

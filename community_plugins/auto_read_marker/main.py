"""TG-SignPulse Community Plugin: Auto Read Marker."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from pyrogram.errors import FloodWait

from tg_signer.core.plugins import (
    PluginContext,
    PluginFloodWaitError,
    PluginRegistry,
)

VERSION = "1.0.0"
AUTHOR = "TG-SignPulse"

PARAMS_SCHEMA: List[Dict[str, Any]] = [
    {
        "name": "delay_seconds",
        "label": "等待时长(秒)",
        "type": "number",
        "default": 0.0,
        "required": False,
        "description": "标记已读前等待的秒数 (0 为立即标记)",
    },
    {
        "name": "private_only",
        "label": "仅私聊生效",
        "type": "boolean",
        "default": False,
        "required": False,
        "description": "是否仅对一对一私聊生效，群组和频道跳过",
    },
]


@PluginRegistry.register(
    name="auto_read_marker",
    mode="active",
    description="在打卡动作执行前主动清除未读红点，还原真人点击会话并阅读的自然行为。",
    version=VERSION,
    author=AUTHOR,
    context_version=2,
    plugin_api="2.0",
    min_app_version="1.9.0",
    permissions=["telegram_read"],
    params_schema=PARAMS_SCHEMA,
)
async def handle_auto_read_marker(ctx: PluginContext) -> bool:
    """Active action plugin: mark conversation history as read."""
    private_only = bool(ctx.params.get("private_only", False))

    if private_only:
        is_private = False
        if (
            ctx.message
            and hasattr(ctx.message, "chat")
            and hasattr(ctx.message.chat, "type")
        ):
            is_private = str(ctx.message.chat.type).lower().endswith("private")
        else:
            is_private = ctx.chat_id > 0

        if not is_private:
            ctx.log("[auto_read_marker] 当前会话非私聊，按配置跳过标记已读")
            return True

    try:
        delay = float(ctx.params.get("delay_seconds", 0.0) or 0.0)
    except (ValueError, TypeError):
        delay = 0.0

    if delay > 0:
        clamped_delay = max(0.0, min(60.0, delay))
        ctx.log(f"[auto_read_marker] 模拟阅读等待 {clamped_delay}s...")
        await asyncio.sleep(clamped_delay)

    ctx.log("[auto_read_marker] 正在清除会话未读红点...")
    try:
        await ctx.read_chat_history(max_id=0)
        ctx.log("[auto_read_marker] 成功标记会话历史为已读")
        return True
    except (PluginFloodWaitError, FloodWait):
        raise
    except Exception as exc:
        ctx.log(f"[auto_read_marker] 标记已读失败: {exc}")
        return False

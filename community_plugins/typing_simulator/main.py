"""TG-SignPulse Community Plugin: Typing Simulator."""

from __future__ import annotations

import asyncio
import random
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
        "name": "duration_seconds",
        "label": "打字持续时间(秒)",
        "type": "number",
        "default": 3.0,
        "required": False,
        "description": "模拟打字持续时间，范围 0.5 - 15.0 秒",
    },
    {
        "name": "randomize",
        "label": "随机浮动抖动",
        "type": "boolean",
        "default": True,
        "required": False,
        "description": "是否在基础打字时长上引入随机抖动浮动",
    },
    {
        "name": "action_type",
        "label": "动作类型",
        "type": "select",
        "default": "typing",
        "required": False,
        "description": "Telegram 会话动作类型",
        "options": [
            {"label": "打字中 (typing)", "value": "typing"},
            {"label": "挑选贴纸 (choose_sticker)", "value": "choose_sticker"},
            {"label": "录制语音 (record_voice)", "value": "record_voice"},
            {"label": "上传照片 (upload_photo)", "value": "upload_photo"},
        ],
    },
]


@PluginRegistry.register(
    name="typing_simulator",
    mode="active",
    description="模拟真实用户在发送消息前的打字状态动画，提高防封与拟人化安全。",
    version=VERSION,
    author=AUTHOR,
    context_version=2,
    plugin_api="2.0",
    min_app_version="1.9.0",
    permissions=["telegram_send"],
    params_schema=PARAMS_SCHEMA,
)
async def handle_typing_simulator(ctx: PluginContext) -> bool:
    """Active action plugin: simulate chat action (e.g. typing) for natural human behavior."""
    try:
        raw_duration = float(ctx.params.get("duration_seconds", 3.0))
    except (ValueError, TypeError):
        raw_duration = 3.0

    randomize = bool(ctx.params.get("randomize", True))
    action_type = str(ctx.params.get("action_type", "typing")).strip() or "typing"

    # Clamp base duration strictly between 0.5s and 15.0s
    clamped_duration = max(0.5, min(15.0, raw_duration))

    if randomize:
        # Add a subtle +/- 20% jitter while strictly respecting the [0.5, 15.0] bounds
        jitter_ratio = random.uniform(-0.2, 0.2)
        final_duration = round(clamped_duration * (1.0 + jitter_ratio), 2)
        final_duration = max(0.5, min(15.0, final_duration))
    else:
        final_duration = clamped_duration

    ctx.log(
        f"[typing_simulator] 正在发送 '{action_type}' 状态并持续 {final_duration}s..."
    )
    try:
        await ctx.send_chat_action(action_type)
    except (PluginFloodWaitError, FloodWait):
        raise
    except Exception as exc:
        ctx.log(f"[typing_simulator] 发送动作 '{action_type}' 失败: {exc}")
        return False

    await asyncio.sleep(final_duration)
    ctx.log(f"[typing_simulator] 完成 '{action_type}' 状态模拟 ({final_duration}s)")
    return True

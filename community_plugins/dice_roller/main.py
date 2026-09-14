"""TG-SignPulse Community Plugin: Dice Roller."""

from __future__ import annotations

import random
import re

from tg_signer.core.plugins import PluginContext, PluginRegistry

VERSION = "1.0.0"
AUTHOR = "GameMaster"


@PluginRegistry.register(
    name="dice_roller",
    mode="reactive",
    description="响应 /roll 或 /dice 口令并掷骰子",
    version=VERSION,
    author=AUTHOR,
    params_schema=[
        {
            "name": "max_sides",
            "label": "骰子面数上限",
            "type": "number",
            "default": 100,
            "required": False,
        },
        {
            "name": "reply_prefix",
            "label": "回复引导词",
            "type": "string",
            "default": "🎲 骰子掷出了：",
            "required": False,
        },
    ],
)
async def handle_dice_roll(ctx: PluginContext) -> bool:
    """Reactive plugin: roll random dice on command match."""
    message = ctx.message
    if not message or not getattr(message, "text", None):
        return False

    text = str(message.text).strip()
    match = re.search(r"^/(?:roll|dice)(?:\s+(\d+))?", text, re.IGNORECASE)
    if not match:
        return False

    cfg_max = int(ctx.params.get("max_sides", 100) or 100)
    user_sides = match.group(1)
    sides = int(user_sides) if user_sides and int(user_sides) > 1 else max(2, cfg_max)
    prefix = str(ctx.params.get("reply_prefix", "🎲 骰子掷出了：")).strip()

    result = random.randint(1, sides)
    reply_content = f"{prefix} {result} (1~{sides})"
    ctx.log(f"[dice_roller] 命中口令，掷出点数: {result}/{sides}")

    try:
        await ctx.reply(reply_content)
        return True
    except Exception as exc:
        ctx.log(f"[dice_roller] 回复失败: {exc}")
        return False

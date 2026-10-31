"""TG-SignPulse Community Plugin: Checkin Observer & Cleaner Guard."""

from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timedelta, timezone
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
        "name": "balance_pattern",
        "label": "余额/总积分提取正则",
        "type": "string",
        "default": r"(?:总积分|当前积分|余额|剩余积分|Points|Balance)[:：\s]*([0-9]+(?:\.[0-9]+)?)",
        "required": False,
        "description": "从回复消息中提取总积分或当前余额的正则表达式（带数字捕获组）",
    },
    {
        "name": "gain_pattern",
        "label": "单次奖励积分提取正则",
        "type": "string",
        "default": r"(?:获得|增加|奖励|\+)\s*([0-9]+(?:\.[0-9]+)?)\s*(?:分|点|积分|Points)?",
        "required": False,
        "description": "从回复消息中提取本次打卡获得积分的正则表达式（带数字捕获组）",
    },
    {
        "name": "streak_pattern",
        "label": "连续签到天数提取正则",
        "type": "string",
        "default": r"(?:已连续签到|连续签到|连签|Streak)[:：\s]*([0-9]+)\s*天?",
        "required": False,
        "description": "从回复消息中提取连续签到天数的正则表达式（带整数捕获组）",
    },
    {
        "name": "enable_points",
        "label": "启用积分变动持久化",
        "type": "boolean",
        "default": True,
        "required": False,
        "description": "是否解析积分变动并原子持久化到 ledger:latest_balance",
    },
    {
        "name": "enable_streak",
        "label": "启用连续签到校准",
        "type": "boolean",
        "default": True,
        "required": False,
        "description": "是否校准自然日连续签到并更新 streak:current 与 streak:last_date",
    },
    {
        "name": "enable_cleanup",
        "label": "启用消息自动清理",
        "type": "boolean",
        "default": False,
        "required": False,
        "description": "打卡完成后是否自动延迟清理 Bot 回复及触发口令消息",
    },
    {
        "name": "delay_seconds",
        "label": "清理等待时长(秒)",
        "type": "number",
        "default": 3.0,
        "required": False,
        "description": "执行消息清理前的缓冲等待秒数",
    },
]


@PluginRegistry.register(
    name="checkin_observer",
    mode="reactive",
    description="原子聚合积分变动解析、自然日连续签到校准与可选延迟消息清理，杜绝多插件争抢。",
    version=VERSION,
    author=AUTHOR,
    context_version=2,
    plugin_api="2.0",
    min_app_version="1.9.0",
    permissions=["storage", "telegram_send"],
    params_schema=PARAMS_SCHEMA,
)
async def handle_checkin_observer(ctx: PluginContext) -> bool:
    """Reactive plugin: parses points, calibrates streak, and cleans up messages."""
    if not ctx.message or not hasattr(ctx.message, "id") or ctx.message.id is None:
        ctx.log("[checkin_observer] 当前上下文无有效消息，跳过处理")
        return False

    msg_id = ctx.message.id
    seen_key = f"seen:{msg_id}"

    # 1. Idempotency guard: avoid duplicate processing for the same message
    if await ctx.storage.get(seen_key):
        ctx.log(f"[checkin_observer] 消息 {msg_id} 已处理过，跳过重复执行")
        return True

    text = ctx.message.text or ctx.message.caption or ""
    if not text:
        ctx.log("[checkin_observer] 消息无文本内容，跳过解析")
        return False

    params = ctx.params or {}
    enable_points = bool(params.get("enable_points", True))
    enable_streak = bool(params.get("enable_streak", True))
    enable_cleanup = bool(params.get("enable_cleanup", False))

    try:
        delay_seconds = float(params.get("delay_seconds", 3.0) or 0.0)
    except (ValueError, TypeError):
        delay_seconds = 3.0

    balance_pat = str(
        params.get("balance_pattern")
        or r"(?:总积分|当前积分|余额|剩余积分|Points|Balance)[:：\s]*([0-9]+(?:\.[0-9]+)?)"
    )
    gain_pat = str(
        params.get("gain_pattern")
        or r"(?:获得|增加|奖励|\+)\s*([0-9]+(?:\.[0-9]+)?)\s*(?:分|点|积分|Points)?"
    )
    streak_pat = str(
        params.get("streak_pattern")
        or r"(?:已连续签到|连续签到|连签|Streak)[:：\s]*([0-9]+)\s*天?"
    )

    points_parsed = False
    streak_parsed = False

    # 2. Atomic points parsing & persistence
    if enable_points:
        balance_match = re.search(balance_pat, text, re.IGNORECASE)
        if balance_match:
            raw_val = balance_match.group(1)
            balance = float(raw_val) if "." in raw_val else int(raw_val)
            await ctx.storage.set("ledger:latest_balance", balance)
            ctx.log(f"[checkin_observer] 成功解析最新积分余额: {balance}")
            points_parsed = True

        gain_match = re.search(gain_pat, text, re.IGNORECASE)
        if gain_match:
            raw_gain = gain_match.group(1)
            gain = float(raw_gain) if "." in raw_gain else int(raw_gain)
            await ctx.storage.set("ledger:last_gain", gain)
            ctx.log(f"[checkin_observer] 成功解析单次获得积分: {gain}")
            points_parsed = True

    # 3. Calendar streak calibration & persistence
    if enable_streak:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        streak_match = re.search(streak_pat, text, re.IGNORECASE)
        if streak_match:
            streak_days = int(streak_match.group(1))
            await ctx.storage.set("streak:current", streak_days)
            await ctx.storage.set("streak:last_date", today_str)
            ctx.log(f"[checkin_observer] 文本校准连续签到天数: {streak_days} 天")
            streak_parsed = True
        else:
            is_checkin_success = bool(
                re.search(r"(?:签到|打卡|领取|check-?in)\s*成功", text, re.IGNORECASE)
            )
            if is_checkin_success:
                last_date = await ctx.storage.get("streak:last_date")
                prev_streak = await ctx.storage.get("streak:current", 0) or 0
                yesterday_str = (date.today() - timedelta(days=1)).isoformat()
                if last_date == yesterday_str:
                    new_streak = int(prev_streak) + 1
                elif last_date == today_str:
                    new_streak = int(prev_streak) if prev_streak else 1
                else:
                    new_streak = 1
                await ctx.storage.set("streak:current", new_streak)
                await ctx.storage.set("streak:last_date", today_str)
                ctx.log(f"[checkin_observer] 自然日递增连续签到天数: {new_streak} 天")
                streak_parsed = True

    # 4. Non-destructive safety check: if parsing fails, do NOT alter or delete messages
    success = False
    if enable_points and enable_streak:
        success = points_parsed or streak_parsed
    elif enable_points:
        success = points_parsed
    elif enable_streak:
        success = streak_parsed
    else:
        success = bool(
            re.search(r"(?:签到|打卡|领取|check-?in)\s*成功", text, re.IGNORECASE)
        )

    if not success:
        ctx.log(
            "[checkin_observer] 消息未匹配到有效的签到变动或解析失败，保留消息并不触发清理",
            level="INFO",
        )
        return False

    # Mark idempotency key upon successful parsing
    await ctx.storage.set(seen_key, True)

    # 5. Message cleanup when enable_cleanup=True
    if enable_cleanup:
        if delay_seconds > 0:
            clamped_delay = max(0.0, min(300.0, delay_seconds))
            ctx.log(f"[checkin_observer] 消息清理等待 {clamped_delay} 秒...")
            await asyncio.sleep(clamped_delay)

        # Delete bot reply
        try:
            await ctx.delete_message(message_id=msg_id)
            ctx.log(f"[checkin_observer] 已清理 Bot 回复消息: {msg_id}")
        except PluginMessageNotFoundError:
            ctx.log(f"[checkin_observer] Bot 回复消息 {msg_id} 已不存在，安全忽略")
        except Exception as exc:
            ctx.log(f"[checkin_observer] 删除 Bot 回复消息异常: {exc}", level="WARNING")

        # Delete trigger command
        trigger_id = getattr(ctx.message, "reply_to_message_id", None)
        if trigger_id:
            try:
                await ctx.delete_message(message_id=trigger_id)
                ctx.log(f"[checkin_observer] 已清理用户触发口令消息: {trigger_id}")
            except PluginMessageNotFoundError:
                ctx.log(
                    f"[checkin_observer] 触发口令消息 {trigger_id} 已不存在，安全忽略"
                )
            except Exception as exc:
                ctx.log(
                    f"[checkin_observer] 删除触发口令消息异常: {exc}", level="WARNING"
                )

    return True

"""TG-SignPulse 官方标准插件：日常签到辅助与连签打卡 (daily_checkin_helper)。

匹配签到回复中的内联签到/领取按钮，
并使用持久化 KV 存储（ctx.storage）自动记录签到总次数与最后签到时间。
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from tg_signer.core.plugins import PluginContext, PluginRegistry

VERSION = "1.0.0"
UPDATED_AT = "2026-09-11"
AUTHOR = "TG-SignPulse Team"

PARAMS_SCHEMA: List[Dict[str, Any]] = [
    {
        "name": "button_keywords",
        "label": "按钮关键词",
        "type": "string",
        "default": "签到,打卡,领取,Claim,Checkin",
        "placeholder": "逗号分隔的关键词列表",
        "description": "检测并点击匹配内联按钮的关键词",
    },
    {
        "name": "track_stats",
        "label": "记录签到统计",
        "type": "bool",
        "default": True,
        "description": "是否在本地持久化存储中记录该对话的签到计数与时间",
    },
]


@PluginRegistry.register(
    name="daily_checkin_helper",
    version=VERSION,
    updated_at=UPDATED_AT,
    author=AUTHOR,
    mode="reactive",
    description="日常签到助手：智能点击签到回复中的内联按钮，并自动累计签到统计",
    params_schema=PARAMS_SCHEMA,
)
async def daily_checkin_helper_handler(ctx: PluginContext) -> bool:
    """响应签到回复消息：匹配并点击内联签到按钮，成功后累计签到统计。"""
    params: Dict[str, Any] = ctx.params or {}
    button_kw_str = str(params.get("button_keywords") or "签到,打卡,领取,Claim,Checkin")
    track_stats = bool(params.get("track_stats", True))
    keywords = [k.strip() for k in button_kw_str.split(",") if k.strip()]

    # 处理前置签到指令产生的响应消息；发送指令由前置 SendText 动作完成。
    clicked_keyword: Optional[str] = None
    if ctx.message:
        for kw in keywords:
            try:
                await ctx.click(kw)
                clicked_keyword = kw
                ctx.log(f"[daily_checkin_helper] 成功匹配并点击签到按钮: {kw}")
                break
            except Exception:
                continue

    # 仅在成功点击按钮后累计统计，未命中消息不计入签到次数
    if track_stats and clicked_keyword is not None:
        now_iso = datetime.now(timezone.utc).isoformat()
        new_count = await ctx.storage.increment("checkin_total_count", 1)
        if new_count is None:
            ctx.log("[daily_checkin_helper] 签到统计写入失败", level="WARNING")
        else:
            await ctx.storage.set("last_checkin_time", now_iso)
            ctx.log(f"[daily_checkin_helper] 签到统计已更新，累计签到次数: {new_count}")

    # 未点中按钮时返回 False，交由等待循环继续接收后续消息直至超时
    return clicked_keyword is not None

"""TG-SignPulse 官方标准插件：日常签到辅助与连签打卡 (daily_checkin_helper)。

支持主动发送签到指令，智能匹配并点击内联键盘中的签到/领取按钮，
并使用持久化 KV 存储（ctx.storage）自动记录签到总次数与最后签到时间。
"""
from datetime import datetime, timezone
from typing import Any, Dict, List
from tg_signer.core.plugins import PluginContext, PluginRegistry

PARAMS_SCHEMA: List[Dict[str, Any]] = [
    {
        "name": "command",
        "label": "签到指令",
        "type": "string",
        "default": "/checkin",
        "placeholder": "例如：/checkin, /sign, 签到",
        "description": "执行主动签到时发送的指令",
    },
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
    mode="active",
    description="日常签到助手：发送签到指令、智能点击签到内联按钮，并自动累计签到统计",
    params_schema=PARAMS_SCHEMA,
)
async def daily_checkin_helper_handler(ctx: PluginContext) -> bool:
    """执行主动签到辅助流程。"""
    params: Dict[str, Any] = ctx.params or {}
    command = str(params.get("command") or "/checkin").strip() or "/checkin"
    button_kw_str = str(params.get("button_keywords") or "签到,打卡,领取,Claim,Checkin")
    track_stats = bool(params.get("track_stats", True))
    keywords = [k.strip() for k in button_kw_str.split(",") if k.strip()]

    # 1. 发送签到指令
    ctx.log(f"[daily_checkin_helper] 正在发送签到指令: {command}")
    await ctx.send_message(command)

    # 2. 若上文或当前消息含有内联按钮，尝试匹配关键词点击
    if ctx.message:
        for kw in keywords:
            try:
                await ctx.click(kw)
                ctx.log(f"[daily_checkin_helper] 成功匹配并点击签到按钮: {kw}")
                break
            except Exception:
                continue

    # 3. 持久化存储打卡统计
    if track_stats:
        now_iso = datetime.now(timezone.utc).isoformat()
        current_count = await ctx.storage.get("checkin_total_count", 0)
        new_count = (int(current_count) if isinstance(current_count, (int, float)) else 0) + 1
        await ctx.storage.set("checkin_total_count", new_count)
        await ctx.storage.set("last_checkin_time", now_iso)
        await ctx.storage.set("last_checkin_command", command)
        ctx.log(f"[daily_checkin_helper] 签到统计已更新，累计签到次数: {new_count}")

    return True

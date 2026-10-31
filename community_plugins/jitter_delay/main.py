"""TG-SignPulse Community Plugin: Jitter Delay."""

from __future__ import annotations

import asyncio
import random
from typing import Any, Dict, List

from tg_signer.core.plugins import (
    PluginContext,
    PluginRegistry,
)

VERSION = "1.0.0"
AUTHOR = "TG-SignPulse"

PARAMS_SCHEMA: List[Dict[str, Any]] = [
    {
        "name": "min_seconds",
        "label": "最小延迟(秒)",
        "type": "number",
        "default": 1.0,
        "required": False,
        "description": "随机延迟等待时长的下限",
    },
    {
        "name": "max_seconds",
        "label": "最大延迟(秒)",
        "type": "number",
        "default": 5.0,
        "required": False,
        "description": "随机延迟等待时长的上限",
    },
    {
        "name": "distribution",
        "label": "分布模型",
        "type": "select",
        "default": "uniform",
        "required": False,
        "description": "随机数采样概率分布模型",
        "options": [
            {"label": "均匀分布 (uniform)", "value": "uniform"},
            {"label": "高斯正态分布 (gaussian)", "value": "gaussian"},
        ],
    },
]


@PluginRegistry.register(
    name="jitter_delay",
    mode="active",
    description="在打卡指令执行前注入拟人化的随机停顿与思考延迟，消除定时请求特征。",
    version=VERSION,
    author=AUTHOR,
    context_version=2,
    plugin_api="2.0",
    min_app_version="1.9.0",
    permissions=[],
    params_schema=PARAMS_SCHEMA,
)
async def handle_jitter_delay(ctx: PluginContext) -> bool:
    """Active action plugin: inject randomized human-like jitter delay."""
    try:
        raw_min = float(ctx.params.get("min_seconds", 1.0))
    except (ValueError, TypeError):
        raw_min = 1.0

    try:
        raw_max = float(ctx.params.get("max_seconds", 5.0))
    except (ValueError, TypeError):
        raw_max = 5.0

    # Non-negative clamping
    clamped_min = max(0.0, raw_min)
    clamped_max = max(0.0, raw_max)

    # Safe swap handling to guarantee low <= high
    low = min(clamped_min, clamped_max)
    high = max(clamped_min, clamped_max)

    dist = str(ctx.params.get("distribution", "uniform")).strip().lower()

    if high <= low:
        delay = low
    elif dist in ("gaussian", "normal"):
        mean = (low + high) / 2.0
        std = (high - low) / 6.0
        sampled = random.gauss(mean, std)
        delay = round(max(low, min(high, sampled)), 2)
    else:
        sampled = random.uniform(low, high)
        delay = round(max(low, min(high, sampled)), 2)

    ctx.log(
        f"[jitter_delay] 正在执行拟人随机延迟 {delay}s (分布: {dist}, 区间: [{low}, {high}])..."
    )
    await asyncio.sleep(delay)
    ctx.log(f"[jitter_delay] 拟人随机延迟完成 ({delay}s)")
    return True

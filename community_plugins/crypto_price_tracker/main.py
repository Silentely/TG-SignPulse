"""TG-SignPulse Community Plugin: Crypto Price Tracker."""

from __future__ import annotations

import re
import time

from tg_signer.core.plugins import PluginContext, PluginRegistry

VERSION = "1.0.0"
AUTHOR = "BlockExplorer"


@PluginRegistry.register(
    name="crypto_price_tracker",
    mode="reactive",
    description="响应式解析消息中的加密货币价格并持久化跟踪",
    version=VERSION,
    author=AUTHOR,
    params_schema=[
        {
            "name": "target_symbol",
            "label": "监控币种符号",
            "type": "string",
            "default": "BTC",
            "required": True,
        },
        {
            "name": "track_history",
            "label": "记录最近行情到插件存储",
            "type": "boolean",
            "default": True,
            "required": False,
        },
    ],
)
async def handle_crypto_tracker(ctx: PluginContext) -> bool:
    """Reactive plugin: extract crypto price patterns from incoming message."""
    message = ctx.message
    if not message or not getattr(message, "text", None):
        return False

    symbol = str(ctx.params.get("target_symbol", "BTC")).strip().upper()
    track_history = bool(ctx.params.get("track_history", True))
    text = str(message.text)

    # Match patterns like BTC: $64,200.50 or BTC price: 64200 or 1 BTC = 64200 USDT
    pattern = rf"(?i)(?:{re.escape(symbol)}[^\d]*?[:=]?\s*[$¥]?\s*([0-9]{{1,3}}(?:,[0-9]{{3}})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?))"
    match = re.search(pattern, text)
    if not match:
        return False

    raw_price = match.group(1).replace(",", "")
    try:
        price = float(raw_price)
    except ValueError:
        return False

    ctx.log(f"[crypto_price_tracker] 检测到 {symbol} 报价: {price}")

    if track_history and ctx.storage:
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        ctx.storage.set("last_price", price)
        ctx.storage.set("last_updated", now)
        ctx.storage.set("symbol", symbol)
        ctx.log(f"[crypto_price_tracker] 已写入持久化存储: {symbol} = {price} @ {now}")

    return True

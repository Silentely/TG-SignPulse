"""TG-SignPulse 官方标准插件：商店 Bot 补货监控与自动抢购助手 (stock_sniper)。

模式：reactive (响应式)
调度方式：周期性轮询（配合 Cron 触发，如 */2 * * * *）
监听 Telegram 商店机器人发出的内联键盘菜单，智能监控目标商品按钮的库存状态。
支持状态反转防骚扰告警（缺货 -> 有货时才提醒）、多渠道 Webhook/Bark 通知，
以及可选的自动模拟点击秒杀。
"""

import hashlib
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from tg_signer.core.plugins import PluginContext, PluginRegistry

VERSION = "1.0.1"
UPDATED_AT = "2026-10-14"
AUTHOR = "TG-SignPulse Team"
CATEGORY = "shopping"
TAGS = ["monitor", "stock", "sniper", "telegram-bot"]
ICON = "shopping-bag"

# 显式声明插件所需核心能力，以顺利通过项目 AST 静态安全审计
PERMISSIONS = ["storage", "buttons", "network"]

PARAMS_SCHEMA: List[Dict[str, Any]] = [
    {
        "name": "target_keyword",
        "label": "目标商品关键词",
        "type": "string",
        "default": "31B Token",
        "placeholder": "例如：31B Token 或 27B Token",
        "description": "用于在内联键盘中定位商品按钮的关键词（忽略大小写）",
    },
    {
        "name": "sold_out_tag",
        "label": "缺货标识文本",
        "type": "string",
        "default": "Sold out",
        "placeholder": "例如：Sold out 或 缺货",
        "description": "按钮包含此文本时认定为缺货状态（忽略大小写）",
    },
    {
        "name": "notify_webhook",
        "label": "报警 Webhook / Bark URL",
        "type": "string",
        "default": "",
        "placeholder": "例如：https://api.day.app/YOUR_KEY/ 或 自建通知URL",
        "description": "补货时推送告警的完整 HTTP(S) 地址（可选，留空则仅在流程日志中输出）",
    },
    {
        "name": "auto_checkout",
        "label": "发现补货自动点击",
        "type": "bool",
        "default": False,
        "description": "发现有货时是否立即模拟点击该商品按钮进行抢购",
    },
]


class _SimulatedButton:
    """在无原生内联键盘或处于 Web 调试控制台时，将文本转换为轻量模拟按钮。"""

    def __init__(self, text: str):
        self.text = text


@PluginRegistry.register(
    name="stock_sniper",
    version=VERSION,
    updated_at=UPDATED_AT,
    author=AUTHOR,
    mode="reactive",
    description="商店 Bot 补货监控：智能识别内联键盘库存状态，支持补货报警与自动秒杀",
    params_schema=PARAMS_SCHEMA,
    permissions=PERMISSIONS,
)
async def stock_sniper_handler(ctx: PluginContext) -> bool:
    """监听 Bot 回复消息中的内联按钮，判断目标商品库存状态并执行告警或秒杀。

    设计说明：
    - 本插件设计配合任务定时调度（如 Cron 每 1~2 分钟执行一次）：
      每轮执行前置发送指令（如 /katalog），Bot 响应面板后由本插件核实库存。
    - 只要从 Bot 回复的菜单中定位并成功判读了目标商品状态（无论是缺货还是有货），
      均返回 True，代表本轮巡检动作顺利达成，避免动作超时等待。
    - 仅当收到的消息不含按钮或未包含目标商品时返回 False，以便等待后续消息。
    """
    msg = ctx.message
    if not msg:
        return False

    # 兼容原生 pyrogram.types.Message 与子进程沙箱 ProxyMessage
    buttons: Optional[List[List[Any]]] = getattr(msg, "buttons", None)
    if not buttons and hasattr(msg, "reply_markup"):
        buttons = getattr(msg.reply_markup, "inline_keyboard", None)

    # 调试与文本回退兼容：若无原生内联按钮（例如在 Web 控制台「调试」弹窗中模拟测试），
    # 则自动将消息文本逐行视作候选按钮文本进行检测与模拟点击
    if not buttons:
        raw_text = getattr(msg, "text", "") or getattr(msg, "caption", "") or ""
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        if lines:
            buttons = [[_SimulatedButton(line)] for line in lines]

    if not buttons:
        # 消息不包含任何内联键盘与文本，返回 False 交由等待循环继续接收后续菜单消息
        return False

    target_kw = (
        str(ctx.get_param("target_keyword", "31B Token") or "31B Token").strip().lower()
    )
    sold_out_kw = (
        str(ctx.get_param("sold_out_tag", "Sold out") or "Sold out").strip().lower()
    )
    notify_url = str(ctx.get_param("notify_webhook", "") or "").strip()
    auto_checkout = bool(ctx.get_param("auto_checkout", False, param_type=bool))

    # 1. 扫描内联按钮寻找目标商品
    target_btn = None
    for row in buttons:
        for btn in row:
            btn_text = getattr(btn, "text", "")
            if target_kw in btn_text.lower():
                target_btn = btn
                break
        if target_btn:
            break

    if not target_btn:
        ctx.log(
            f"[stock_sniper] 当前消息未找到包含关键词 '{target_kw}' 的商品按钮",
            level="INFO",
        )
        return False

    btn_text = getattr(target_btn, "text", "").strip()
    is_sold_out = sold_out_kw in btn_text.lower()

    # 存储 key 细分隔离：可读前缀 + 8位 sha256 摘要，保证同一对话内监控多款商品时无碰撞
    kw_slug = "".join(c if c.isalnum() else "_" for c in target_kw)
    kw_hash = hashlib.sha256(target_kw.encode("utf-8")).hexdigest()[:8]
    safe_kw_key = f"{kw_slug}_{kw_hash}"

    state_key = f"state:{safe_kw_key}"
    alerted_key = f"alerted:{safe_kw_key}"
    checkout_done_key = f"checkout_done:{safe_kw_key}"

    last_state = await ctx.storage.get(state_key, default="unknown")
    ctx.log(
        f"[stock_sniper] 目标按钮: [{btn_text}] | 上次状态: {last_state} | 当前状态: {'缺货 (Sold out)' if is_sold_out else '🔥 现货已补齐！'}"
    )

    # 2. 如果依然缺货：重置告警与购买标记，本轮巡检顺利完成
    if is_sold_out:
        await ctx.storage.set(state_key, "sold_out")
        await ctx.storage.delete(alerted_key)
        await ctx.storage.delete(checkout_done_key)
        ctx.log("[stock_sniper] 商品仍处于缺货状态，本轮巡检完成，等待下次调度")
        return True

    # 3. 发现有货！更新状态为 in_stock
    await ctx.storage.set(state_key, "in_stock")

    alert_title = "🎉【补货报警】您关注的商品已补货！"
    alert_body = f"商品: {btn_text}\n请立即前往 Telegram 商店 Bot 完成下单！"

    # 防重复轰炸：检查是否已经发送过报警
    has_alerted = await ctx.storage.get(alerted_key, default=False)
    if not has_alerted:
        ctx.log(f"[stock_sniper] {alert_title}\n{alert_body}", level="INFO")
        if notify_url and (
            notify_url.startswith("http://") or notify_url.startswith("https://")
        ):
            try:
                async with httpx.AsyncClient(
                    timeout=8.0, follow_redirects=True
                ) as client:
                    if "day.app" in notify_url:
                        # 兼容 iOS Bark 快速推送
                        clean_url = notify_url.rstrip("/")
                        bark_url = f"{clean_url}/{quote(alert_title)}/{quote(alert_body)}?group=StockSniper&sound=alarm"
                        resp = await client.get(bark_url)
                    else:
                        payload = {
                            "event": "stock_restock",
                            "title": alert_title,
                            "content": alert_body,
                            "button_text": btn_text,
                        }
                        resp = await client.post(notify_url, json=payload)
                    if resp.is_success:
                        await ctx.storage.set(alerted_key, True)
                        ctx.log(f"[stock_sniper] 告警推送成功: HTTP {resp.status_code}")
                    else:
                        ctx.log(
                            f"[stock_sniper] 告警推送返回非成功状态码: HTTP {resp.status_code}",
                            level="WARNING",
                        )
            except Exception as exc:
                ctx.log(f"[stock_sniper] 外部推送告警失败: {exc}", level="WARNING")
        else:
            # 未配置外部 webhook，仅在日志输出，并标记已告警
            await ctx.storage.set(alerted_key, True)
    else:
        ctx.log("[stock_sniper] 商品仍处于在售有货状态（此前已报警），本轮静默跳过推送")

    # 4. 可选：自动模拟点击秒杀（仅在未成功抢购过时尝试，失败时不写成功状态，允许下轮重试）
    if auto_checkout:
        has_checked_out = await ctx.storage.get(checkout_done_key, default=False)
        if not has_checked_out:
            ctx.log(f"[stock_sniper] 正在尝试自动点击商品按钮 [{btn_text}]...")
            try:
                await ctx.click(btn_text)
                await ctx.storage.set(checkout_done_key, True)
                ctx.log(f"[stock_sniper] 成功模拟点击商品按钮: [{btn_text}]")
            except Exception as exc:
                ctx.log(
                    f"[stock_sniper] 模拟点击按钮失败（下轮将继续重试）: {exc}",
                    level="ERROR",
                )
        else:
            ctx.log("[stock_sniper] 此前已完成自动点击抢购，本轮跳过点击")

    return True

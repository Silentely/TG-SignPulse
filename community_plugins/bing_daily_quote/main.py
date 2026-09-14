"""TG-SignPulse Community Plugin: Bing Daily Quote."""

from __future__ import annotations

import json
from urllib.request import Request, urlopen

from tg_signer.core.plugins import PluginContext, PluginRegistry

VERSION = "1.0.0"
AUTHOR = "TG-Community"


@PluginRegistry.register(
    name="bing_daily_quote",
    mode="active",
    description="主动获取必应每日一图背景格言并发送问候",
    version=VERSION,
    author=AUTHOR,
    params_schema=[
        {
            "name": "greeting_prefix",
            "label": "晨安问候前缀",
            "type": "string",
            "default": "☀️ 每日晨安名言：",
            "required": False,
        },
        {
            "name": "include_copyright",
            "label": "包含图片版权说明",
            "type": "boolean",
            "default": True,
            "required": False,
        },
    ],
)
async def handle_bing_daily(ctx: PluginContext) -> bool:
    """Active action plugin: fetch Bing daily story and send quote message."""
    greeting = str(ctx.params.get("greeting_prefix", "☀️ 每日晨安名言：")).strip()
    include_copyright = bool(ctx.params.get("include_copyright", True))

    ctx.log("[bing_daily_quote] 正在获取必应每日壁纸与格言...")
    title = "今日寄语"
    copyright_text = ""

    try:
        req = Request(
            "https://cn.bing.com/HPImageArchive.aspx?format=js&idx=0&n=1&mkt=zh-CN",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        with urlopen(req, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
            images = data.get("images", [])
            if images:
                first = images[0]
                title = first.get("title", "今日名言")
                copyright_text = first.get("copyright", "")
    except Exception as exc:
        ctx.log(f"[bing_daily_quote] 获取必应接口失败: {exc}，使用默认祝福")
        title = "日拱一卒，功不唐捐"

    msg_lines = [f"{greeting} {title}"]
    if include_copyright and copyright_text:
        msg_lines.append(f"📌 {copyright_text}")

    final_text = "\n\n".join(msg_lines)
    try:
        await ctx.send_message(final_text)
        ctx.log(f"[bing_daily_quote] 成功推送每日名言: {title}")
        return True
    except Exception as exc:
        ctx.log(f"[bing_daily_quote] 发送消息异常: {exc}")
        return False

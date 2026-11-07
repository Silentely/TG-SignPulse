"""TG-SignPulse Community Plugin: Telegram Mini App Claim.

通过 RequestWebView 获取合法 Telegram Mini App 凭证并完成自动化签到。
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict

from tg_signer.core.plugins import (
    PluginContext,
    PluginFloodWaitError,
    PluginRegistry,
)

VERSION = "1.0.0"
AUTHOR = "TG-Community"


def _perform_http_post(
    url: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
    timeout: float = 15.0,
) -> Dict[str, Any]:
    """同步发送 HTTP POST 请求，返回 JSON 结构。"""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content = resp.read().decode("utf-8")
        try:
            return json.loads(content)
        except Exception:
            return {"raw": content, "status_code": resp.status}


@PluginRegistry.register(
    name="mini_app_claim",
    mode="active",
    description="通过 RequestWebView 获取合法 Telegram Mini App 凭证并完成自动化签到",
    version=VERSION,
    author=AUTHOR,
    context_version=2,
    plugin_api="2.0",
    min_app_version="1.8.0",
    permissions=["web_app", "storage", "network"],
    params_schema=[
        {
            "name": "bot_peer",
            "label": "Bot Peer",
            "type": "string",
            "default": "",
            "required": False,
            "description": "目标 Bot 用户名或 ID（留空默认当前 chat_id）",
        },
        {
            "name": "claim_url",
            "label": "签到 API 地址",
            "type": "string",
            "default": "https://api.example.com/v1/claim",
            "required": True,
            "description": "接收 initData 凭证的目标 HTTP 签到接口",
        },
        {
            "name": "from_bot_menu",
            "label": "From Bot Menu",
            "type": "boolean",
            "default": True,
            "required": False,
            "description": "是否以 Bot Menu 场景请求 WebApp",
        },
        {
            "name": "max_flood_wait",
            "label": "最大 FloodWait 容忍秒数",
            "type": "integer",
            "default": 300,
            "required": False,
            "description": "遇到 Telegram FloodWait 时最大允许等待秒数，超过则不重试",
        },
    ],
)
async def handle_mini_app_claim(ctx: PluginContext) -> bool:
    """执行 Telegram Mini App 自动化签到流程。"""
    bot_peer = ctx.params.get("bot_peer") or ctx.chat_id
    claim_url = str(
        ctx.params.get("claim_url", "https://api.example.com/v1/claim")
    ).strip()
    from_bot_menu = bool(ctx.params.get("from_bot_menu", True))
    max_flood_wait = int(ctx.params.get("max_flood_wait", 300))

    ctx.log(
        f"[mini_app_claim] 开始请求 WebApp 凭证: bot_peer={bot_peer}, from_bot_menu={from_bot_menu}"
    )

    # 1. 调用 request_web_view 换取 initData，若遇 FloodWait 按服务端返回秒数等待
    try:
        webview_res = await ctx.request_web_view(
            bot_peer=bot_peer,
            from_bot_menu=from_bot_menu,
            platform="android",
        )
    except PluginFloodWaitError as exc:
        wait_seconds = exc.seconds
        if wait_seconds > max_flood_wait:
            ctx.log(
                f"[mini_app_claim] 触发 Telegram FloodWait ({wait_seconds}s > {max_flood_wait}s)，超出容忍阈值，放弃重试",
                level="WARNING",
            )
            raise
        ctx.log(
            f"[mini_app_claim] 触发 Telegram FloodWait，严格按服务端秒数休眠 {wait_seconds} 秒后重试...",
            level="WARNING",
        )
        await asyncio.sleep(wait_seconds)
        webview_res = await ctx.request_web_view(
            bot_peer=bot_peer,
            from_bot_menu=from_bot_menu,
            platform="android",
        )
    except Exception as exc:
        exc_name = type(exc).__name__
        if "FloodWait" in exc_name:
            wait_seconds = getattr(exc, "value", getattr(exc, "seconds", None))
            if wait_seconds is not None and isinstance(wait_seconds, int):
                if wait_seconds > max_flood_wait:
                    ctx.log(
                        f"[mini_app_claim] 触发 FloodWait ({wait_seconds}s > {max_flood_wait}s)，超出容忍阈值，放弃重试",
                        level="WARNING",
                    )
                    raise
                ctx.log(
                    f"[mini_app_claim] 触发 FloodWait，严格按服务端秒数休眠 {wait_seconds} 秒后重试...",
                    level="WARNING",
                )
                await asyncio.sleep(wait_seconds)
                webview_res = await ctx.request_web_view(
                    bot_peer=bot_peer,
                    from_bot_menu=from_bot_menu,
                    platform="android",
                )
            else:
                raise
        else:
            raise

    init_data_raw = webview_res.get("init_data_raw")
    if not init_data_raw:
        raw_url = webview_res.get("url", "")
        if "#tgWebAppData=" in raw_url:
            fragment = raw_url.split("#", 1)[1]
            data_part = fragment.split("tgWebAppData=", 1)[1]
            if "&" in data_part:
                data_part = data_part.split("&", 1)[0]
            import urllib.parse

            init_data_raw = urllib.parse.unquote(data_part)

    if not init_data_raw:
        ctx.log("[mini_app_claim] 未能解析到有效的 init_data_raw 凭证", level="ERROR")
        return False

    ctx.log(
        f"[mini_app_claim] 凭证获取成功，长度 {len(init_data_raw)} 字节，执行零篡改透传"
    )

    # 2. 原样透传调用目标签到接口
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"tma {init_data_raw}",
        "X-Telegram-Init-Data": init_data_raw,
        "User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    }
    payload = {
        "init_data": init_data_raw,
    }

    try:
        resp_data = await asyncio.to_thread(
            _perform_http_post,
            claim_url,
            payload,
            headers,
        )
    except Exception as exc:
        ctx.log(f"[mini_app_claim] 签到接口请求失败: {exc}", level="ERROR")
        if ctx.storage is not None:
            await ctx.storage.set("last_claim_status", "failed")
            await ctx.storage.set("last_claim_error", str(exc))
            await ctx.storage.set("last_claim_timestamp", int(time.time()))
        return False

    # 3. 结果落库持久化
    ctx.log(f"[mini_app_claim] 签到接口响应成功: {resp_data}")
    if ctx.storage is not None:
        await ctx.storage.set("last_claim_status", "success")
        await ctx.storage.set("last_claim_result", resp_data)
        await ctx.storage.set("last_claim_timestamp", int(time.time()))

    return True

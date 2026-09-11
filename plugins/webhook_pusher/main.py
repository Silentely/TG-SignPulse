"""TG-SignPulse 官方标准范例插件：主动执行型 Webhook 通知推送 (webhook_pusher)。

模式：active（主动执行模式）
在签到动作推进到该插件时，主动将当前对话信息、自定义消息与执行时间戳通过 HTTP POST
发送给外部 Webhook（例如企业微信、飞书、钉钉、Bark 或自建监控 API）。
"""
from datetime import datetime, timezone
import json
from typing import Any, Dict, List
import httpx

from tg_signer.core.plugins import PluginContext, PluginRegistry

VERSION = "1.0.0"
UPDATED_AT = "2026-09-11"
AUTHOR = "TG-SignPulse Team"

PARAMS_SCHEMA: List[Dict[str, Any]] = [
    {
        "name": "webhook_url",
        "label": "Webhook URL",
        "type": "string",
        "default": "",
        "placeholder": "https://example.com/api/webhook",
        "description": "接收通知推送的完整 HTTP(S) 地址（必填）",
    },
    {
        "name": "secret_token",
        "label": "鉴权密钥 (Token)",
        "type": "string",
        "default": "",
        "placeholder": "可选，如 Bearer Token 或 Secret 字符串",
        "description": "若配置，将通过 HTTP Authorization 头附带 Bearer Token",
    },
    {
        "name": "custom_message",
        "label": "自定义说明文本",
        "type": "string",
        "default": "",
        "placeholder": "例如：日常打卡流水线触发",
        "description": "附加到推送负载中的说明文案",
    },
]


@PluginRegistry.register(
    name="webhook_pusher",
    mode="active",
    description="主动执行型 Webhook 推送插件：将当前执行上下文与状态通过 HTTP POST 发送至第三方系统",
    params_schema=PARAMS_SCHEMA,
    version=VERSION,
    updated_at=UPDATED_AT,
    author=AUTHOR,
)
async def webhook_pusher_handler(ctx: PluginContext) -> bool:
    """主动向配置的 Webhook URL 发送 POST 通知。"""
    params: Dict[str, Any] = ctx.params or {}
    url = str(params.get("webhook_url") or "").strip()
    if not url:
        ctx.log("Webhook 推送失败：未配置有效的 webhook_url", level="ERROR")
        return False

    if not (url.startswith("http://") or url.startswith("https://")):
        ctx.log(f"Webhook 推送失败：URL 格式无效，必须以 http:// 或 https:// 开头: {url}", level="ERROR")
        return False

    secret_token = str(params.get("secret_token") or "").strip()
    custom_msg = str(params.get("custom_message") or "").strip()

    payload = {
        "event": "plugin_active_trigger",
        "chat_id": ctx.chat_id,
        "custom_message": custom_msg,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "TG-SignPulse-Plugin/webhook_pusher",
    }
    if secret_token:
        headers["Authorization"] = f"Bearer {secret_token}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if 200 <= resp.status_code < 300:
                ctx.log(f"Webhook 推送成功: HTTP {resp.status_code}")
                return True
            else:
                ctx.log(f"Webhook 推送响应异常: HTTP {resp.status_code}, 内容: {resp.text[:200]}", level="WARNING")
                return False
    except Exception as exc:
        ctx.log(f"Webhook 推送发生网络异常: {exc}", level="ERROR")
        return False

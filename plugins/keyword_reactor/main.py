"""TG-SignPulse 官方标准插件：关键词表情表态与快捷回复 (keyword_reactor)。

当接收到的消息满足关键词匹配规则时，自动为消息添加表情表态（Reaction）或进行快捷回复。
支持包含匹配 (contains)、精确匹配 (exact) 及正则表达式 (regex)。
"""
from typing import Any, Dict, List
import re
from tg_signer.core.plugins import PluginContext, PluginRegistry

PARAMS_SCHEMA: List[Dict[str, Any]] = [
    {
        "name": "keyword",
        "label": "匹配关键词",
        "type": "string",
        "default": "",
        "placeholder": "例如：打卡成功 或 [Cc]ongrats",
        "description": "触发表态的关键词或正则表达式",
    },
    {
        "name": "emoji",
        "label": "表态 Emoji",
        "type": "string",
        "default": "👍",
        "placeholder": "例如：👍, 🎉, ❤️, 🔥",
        "description": "要添加的 Telegram 表情表态",
    },
    {
        "name": "match_mode",
        "label": "匹配模式",
        "type": "select",
        "options": [
            {"label": "包含关键词 (contains)", "value": "contains"},
            {"label": "精确匹配 (exact)", "value": "exact"},
            {"label": "正则表达式 (regex)", "value": "regex"},
        ],
        "default": "contains",
    },
    {
        "name": "reply_text",
        "label": "附加回复文本",
        "type": "string",
        "default": "",
        "placeholder": "可选。表态时一并发送该文本回复",
        "description": "若填写则在表态后同时自动回复本条内容",
    },
]


@PluginRegistry.register(
    name="keyword_reactor",
    mode="reactive",
    description="监听消息关键词，自动添加 Emoji 表情表态并支持快捷回复",
    params_schema=PARAMS_SCHEMA,
)
async def keyword_reactor_handler(ctx: PluginContext) -> bool:
    """监听接收到的消息，匹配关键词并自动执行表情表态。"""
    msg = ctx.message
    if not msg:
        return False

    text = str(getattr(msg, "text", None) or getattr(msg, "caption", None) or "").strip()
    if not text:
        return False

    params: Dict[str, Any] = ctx.params or {}
    keyword = str(params.get("keyword") or "").strip()
    if not keyword or len(keyword) > 512:
        return False

    text = text[:4096]

    emoji = str(params.get("emoji") or "👍").strip() or "👍"
    match_mode = str(params.get("match_mode") or "contains").lower()
    reply_text = str(params.get("reply_text") or "").strip()

    matched = False
    if match_mode == "exact":
        matched = (text.strip() == keyword)
    elif match_mode == "regex":
        try:
            matched = bool(re.search(keyword, text))
        except re.error as exc:
            ctx.log(f"[keyword_reactor] 无效正则表达式 '{keyword}': {exc}", level="WARNING")
            return False
    else:
        matched = (keyword in text)

    if not matched:
        return False

    ctx.log(f"[keyword_reactor] 命中关键词 '{keyword}'，正在添加表情表态 {emoji}")
    reacted = False
    try:
        await ctx.react(emoji)
        reacted = True
    except Exception as e:
        ctx.log(f"[keyword_reactor] 表情表态失败: {e}", level="WARNING")

    if reply_text:
        try:
            await ctx.reply(reply_text)
            ctx.log(f"[keyword_reactor] 已发送附加回复: {reply_text}")
            return True
        except Exception as e:
            ctx.log(f"[keyword_reactor] 发送附加回复失败: {e}", level="WARNING")

    return reacted

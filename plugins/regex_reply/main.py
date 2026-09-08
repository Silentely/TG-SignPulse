"""TG-SignPulse 官方标准插件：通用正则表达式匹配提取与回复 (regex_reply)。

支持用户自定义正则表达式从 Bot 消息中提取验证码、口令、答案等内容，
并按模板渲染后自动回复。
"""
import re
from typing import Any, Dict

from tg_signer.core.plugins import PluginContext, PluginRegistry


@PluginRegistry.register(
    name="regex_reply",
    mode="reactive",
    description="通用正则匹配提取与回复插件（支持自定义模式与捕获组模板）",
    params_schema=[
        {
            "name": "pattern",
            "label": "匹配正则表达式",
            "type": "string",
            "default": r"验证码[：:\s]+([a-zA-Z0-9]+)",
            "placeholder": r"例如：验证码[：:\s]+([a-zA-Z0-9]+) 或 \b\d{4,6}\b",
        },
        {
            "name": "template",
            "label": "回复文本模板",
            "type": "string",
            "default": "{1}",
            "placeholder": "例如：{1}（第一捕获组）或 答案：{1}",
        },
        {
            "name": "reply_to",
            "label": "引用原消息回复",
            "type": "bool",
            "default": True,
        },
    ],
)
async def regex_reply_handler(ctx: PluginContext) -> bool:
    """根据配置的正则表达式匹配到达的消息，并提取内容回复。"""
    msg = ctx.message
    if not msg or not getattr(msg, "text", None):
        return False

    params: Dict[str, Any] = ctx.params or {}
    pattern_str = str(params.get("pattern") or r"验证码[：:\s]+([a-zA-Z0-9]+)")
    template = str(params.get("template") or "{1}")
    reply_to = bool(params.get("reply_to", True))

    try:
        regex = re.compile(pattern_str)
    except re.error as exc:
        ctx.log(f"[regex_reply] 无效的正则表达式 {pattern_str!r}: {exc}")
        return False

    match = regex.search(msg.text)
    if not match:
        return False

    # 替换捕获组：{0} 为全文，{1} 为第 1 组，依此类推
    reply_content = template
    groups = match.groups()
    if groups:
        for idx, group_val in enumerate(groups, start=1):
            reply_content = reply_content.replace(f"{{{idx}}}", group_val or "")
        reply_content = reply_content.replace("{0}", match.group(0))
    else:
        # 正则无显式捕获组时，{0} 和 {1} 均回退为全文匹配
        reply_content = reply_content.replace("{0}", match.group(0))
        reply_content = reply_content.replace("{1}", match.group(0))

    ctx.log(
        f"[regex_reply] 成功匹配表达式 {pattern_str!r}，提取回复：{reply_content!r}"
    )

    if reply_to:
        await ctx.reply(reply_content)
    else:
        await ctx.send_message(reply_content)

    return True

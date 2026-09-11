"""TG-SignPulse 官方标准插件：通用正则表达式匹配提取与回复 (regex_reply)。

支持用户自定义正则表达式从 Bot 消息中提取验证码、口令、答案等内容，
并按模板渲染后自动回复。
"""
import asyncio
import json
import sys
from typing import Any, Dict

from tg_signer.core.plugins import PluginContext, PluginRegistry

VERSION = "1.0.0"
UPDATED_AT = "2026-09-11"
AUTHOR = "TG-SignPulse Team"

_REGEX_TIMEOUT_SECONDS = 0.2
_MAX_PATTERN_LENGTH = 512
_MAX_MESSAGE_LENGTH = 4096
_REGEX_WORKER = r'''
import json
import re
import sys

payload = json.loads(sys.stdin.read())
try:
    regex = re.compile(payload["pattern"])
    match = regex.search(payload["text"])
    result = {
        "ok": True,
        "match": match.group(0) if match else None,
        "groups": list(match.groups()) if match else [],
    }
except re.error as exc:
    result = {"ok": False, "error": str(exc)}
print(json.dumps(result, ensure_ascii=False))
'''

PARAMS_SCHEMA = [
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
]


@PluginRegistry.register(
    name="regex_reply",
    version=VERSION,
    updated_at=UPDATED_AT,
    author=AUTHOR,
    mode="reactive",
    description="通用正则匹配提取与回复插件（支持自定义模式与捕获组模板）",
    params_schema=PARAMS_SCHEMA,
)
async def regex_reply_handler(ctx: PluginContext) -> bool:
    """根据配置的正则表达式匹配到达的消息，并提取内容回复。"""
    msg = ctx.message
    if not msg:
        return False

    raw_text = getattr(msg, "text", None) or getattr(msg, "caption", None)
    if not raw_text:
        return False

    params: Dict[str, Any] = ctx.params or {}
    pattern_str = str(params.get("pattern") or r"验证码[：:\s]+([a-zA-Z0-9]+)")
    template = str(params.get("template") or "{1}")
    reply_to = bool(params.get("reply_to", True))

    if len(pattern_str) > _MAX_PATTERN_LENGTH:
        ctx.log(f"[regex_reply] 正则表达式过长，最多允许 {_MAX_PATTERN_LENGTH} 个字符")
        return False

    text = str(raw_text)
    if len(text) > _MAX_MESSAGE_LENGTH:
        text = text[:_MAX_MESSAGE_LENGTH]

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _REGEX_WORKER,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(
            process.communicate(
                json.dumps({"pattern": pattern_str, "text": text}).encode("utf-8")
            ),
            timeout=_REGEX_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        ctx.log(f"[regex_reply] 正则匹配超过 {_REGEX_TIMEOUT_SECONDS:g} 秒，已终止")
        return False
    if process.returncode != 0:
        ctx.log("[regex_reply] 正则匹配进程异常退出")
        return False

    try:
        result = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        ctx.log("[regex_reply] 正则匹配结果无法解析")
        return False
    if not result.get("ok"):
        ctx.log(f"[regex_reply] 无效的正则表达式 {pattern_str!r}: {result.get('error', '')}")
        return False
    match_text = result.get("match")
    if match_text is None:
        return False

    # 替换捕获组：{0} 为全文，{1} 为第 1 组，依此类推
    reply_content = template
    groups = result.get("groups") or []
    if groups:
        for idx, group_val in enumerate(groups, start=1):
            reply_content = reply_content.replace(f"{{{idx}}}", group_val or "")
        reply_content = reply_content.replace("{0}", match_text)
    else:
        # 正则无显式捕获组时，{0} 和 {1} 均回退为全文匹配
        reply_content = reply_content.replace("{0}", match_text)
        reply_content = reply_content.replace("{1}", match_text)

    ctx.log(
        f"[regex_reply] 成功匹配表达式 {pattern_str!r}，提取回复：{reply_content!r}"
    )

    if reply_to:
        await ctx.reply(reply_content)
    else:
        await ctx.send_message(reply_content)

    return True

"""TG-SignPulse 官方范例插件：纯文本计算题秒答 (math_solver)。

针对某些签到 Bot 会发送纯文本数学验证码，例如“请在 30 秒内输入 2*31 的答案”。
本插件在 Bot 触发回复后秒级识别算式并直接给出答案回复。
"""
import re
from typing import Optional

from tg_signer.core.plugins import PluginContext, PluginRegistry

VERSION = "1.0.0"
UPDATED_AT = "2026-09-11"
AUTHOR = "TG-SignPulse Team"

_MATH_PATTERN = re.compile(r"(?<![\d\-])(\d+)\s*([\+\-\*\/\×\÷])\s*(\d+)(?![\d\-])")


def _evaluate_expression(text: str) -> Optional[int]:
    match = _MATH_PATTERN.search(text)
    if not match:
        return None
    left = int(match.group(1))
    op = match.group(2)
    right = int(match.group(3))

    if op == "+":
        return left + right
    elif op == "-":
        return left - right
    elif op in ("*", "×"):
        return left * right
    elif op in ("/", "÷"):
        return left // right if right != 0 else None
    return None


PARAMS_SCHEMA = [
    {
        "name": "reply_prefix",
        "label": "回复前缀",
        "type": "string",
        "default": "",
        "placeholder": "例如：答案是：",
    },
]


@PluginRegistry.register(
    name="math_solver",
    version=VERSION,
    updated_at=UPDATED_AT,
    author=AUTHOR,
    mode="reactive",
    description="纯文本计算题秒答插件",
    params_schema=PARAMS_SCHEMA,
)
async def solve_math_challenge(ctx: PluginContext) -> bool:
    """监听新到达的消息，提取算式并自动回复答案。"""
    msg = ctx.message
    if not msg or not getattr(msg, "text", None):
        return False

    ans = _evaluate_expression(msg.text)
    if ans is None:
        return False

    ctx.log(f"[math_solver] 成功匹配计算题：{msg.text!r}，计算答案：{ans}")
    prefix = ""
    if ctx.params and isinstance(ctx.params, dict):
        prefix = str(ctx.params.get("reply_prefix") or "")
    await ctx.reply(f"{prefix}{ans}")
    return True

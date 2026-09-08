"""TG-SignPulse 官方范例插件：纯文本计算题秒答 (math_solver)。

对应 GitHub Issue #10 场景：“某些签到 Bot 会发送纯文本数学验证码，例如‘请在 30 秒内输入 2*31 的答案’”。
"""
import re
from typing import Optional

from tg_signer.core.plugins import PluginContext, PluginRegistry

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


@PluginRegistry.register(
    name="math_solver",
    mode="reactive",
    description="纯文本计算题秒答插件（对应 Issue #10 示例）",
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
    await ctx.reply(str(ans))
    return True

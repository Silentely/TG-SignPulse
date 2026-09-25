"""测试执行器在调度动作时对 ai_prompt 模板宏变量的渲染能力。"""
from __future__ import annotations

from tg_signer.config import ReplyByCalculationProblemAction
from tg_signer.core.signer_runner import _copy_action_with
from tg_signer.core.template import render_template


def test_ai_prompt_template_rendering():
    action = ReplyByCalculationProblemAction(ai_prompt="当前账号: {{ account.name }}，请解决题目")
    tmpl_ctx = {
        "account": {"name": "test_bot_1"},
        "chat": {"id": 12345, "name": "Test Group"},
    }
    rendered_prompt = render_template(action.ai_prompt, tmpl_ctx)
    assert rendered_prompt == "当前账号: test_bot_1，请解决题目"
    new_action = _copy_action_with(action, ai_prompt=rendered_prompt)
    assert new_action.ai_prompt == "当前账号: test_bot_1，请解决题目"

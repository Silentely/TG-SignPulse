# tests/test_flow_context.py
from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_models import NodeStatus, StepOutcome


def test_scoped_context_variable_resolution():
    ctx = ScopedFlowContext(
        system={"version": "4.0.0"},
        account={"username": "alice", "user_id": 9988},
    )
    ctx.set_var("captcha_code", "4521")
    ctx.record_step_outcome(
        StepOutcome(
            node_id="login_step",
            status=NodeStatus.SUCCESS,
            output_text="Token: XYZ-123",
            extracted_vars={"token": "XYZ-123"},
        )
    )

    rendered = ctx.render("欢迎 {{ account.username }}，验证码是 {{ vars.captcha_code }}，令牌是 {{ steps.login_step.token }}")
    assert rendered == "欢迎 alice，验证码是 4521，令牌是 XYZ-123"

def test_scoped_context_condition_evaluation():
    ctx = ScopedFlowContext()
    ctx.set_var("balance", "150")

    assert ctx.eval_condition("vars.balance > 100") is True
    assert ctx.eval_condition("vars.balance < 200") is True
    assert ctx.eval_condition("vars.balance < 50") is False
    ctx.set_var("non_numeric", "abc")
    assert ctx.eval_condition("vars.non_numeric < 50") is False
    assert ctx.eval_condition("vars.not_exist < 50") is False
    assert ctx.eval_condition("'XYZ' in prev.output", default_output="Token: XYZ-123") is True

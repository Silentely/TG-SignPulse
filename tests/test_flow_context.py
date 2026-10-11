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

    rendered = ctx.render(
        "欢迎 {{ account.username }}，验证码是 {{ vars.captcha_code }}，令牌是 {{ steps.login_step.token }}"
    )
    assert rendered == "欢迎 alice，验证码是 4521，令牌是 XYZ-123"

    # 验证 1-based 数字索引在 steps 与 step 别名中的一致性
    rendered_by_index = ctx.render(
        "第1步输出: {{ steps.1.output }}，step别名输出: {{ step.1.output }}"
    )
    assert (
        rendered_by_index == "第1步输出: Token: XYZ-123，step别名输出: Token: XYZ-123"
    )


def test_scoped_context_condition_evaluation():
    ctx = ScopedFlowContext()
    ctx.set_var("balance", "150")
    ctx.set_var("status", "success")

    assert ctx.eval_condition("vars.balance > 100") is True
    assert ctx.eval_condition("vars.balance < 200") is True
    assert ctx.eval_condition("vars.balance < 50") is False
    assert ctx.eval_condition("vars.status == 'success'") is True
    assert ctx.eval_condition("vars.status != 'failed'") is True
    assert ctx.eval_condition("vars.status != 'success'") is False

    ctx.set_var("non_numeric", "abc")
    assert ctx.eval_condition("vars.non_numeric < 50") is False
    assert ctx.eval_condition("vars.not_exist < 50") is False
    assert (
        ctx.eval_condition("'XYZ' in prev.output", default_output="Token: XYZ-123")
        is True
    )


def test_scoped_context_extended_operators():
    ctx = ScopedFlowContext()
    ctx.set_var("points", 100)
    ctx.set_var("is_vip", True)
    ctx.set_var("has_error", False)
    ctx.set_var("code", "AUTH-98765")
    ctx.set_var("tags", ["active", "premium"])
    ctx.last_output = "Welcome back, your verification code is 123456"

    # >= and <=
    assert ctx.eval_condition("vars.points >= 100") is True
    assert ctx.eval_condition("vars.points >= 101") is False
    assert ctx.eval_condition("vars.points <= 100") is True
    assert ctx.eval_condition("vars.points <= 99") is False

    # not in and in
    assert ctx.eval_condition("'error' not in prev.output") is True
    assert ctx.eval_condition("'Welcome' in prev.output") is True

    # contains and not contains
    assert ctx.eval_condition("prev.output contains 'verification'") is True
    assert ctx.eval_condition("prev.output not contains 'failure'") is True

    # matches (regex)
    assert ctx.eval_condition(r"prev.output matches \d{6}") is True
    assert ctx.eval_condition(r"vars.code matches ^AUTH-\d+$") is True
    assert ctx.eval_condition(r"vars.code matches ^FAIL") is False

    # boolean flag and negation
    assert ctx.eval_condition("vars.is_vip") is True
    assert ctx.eval_condition("!vars.has_error") is True
    assert ctx.eval_condition("not vars.has_error") is True
    assert ctx.eval_condition("vars.has_error") is False

    # boolean string comparison
    assert ctx.eval_condition("vars.is_vip == true") is True
    assert ctx.eval_condition("vars.is_vip == false") is False
    assert ctx.eval_condition("vars.has_error != true") is True

    # list indexing
    assert ctx.eval_condition("vars.tags.0 == 'active'") is True
    assert ctx.eval_condition("vars.tags.1 == 'premium'") is True


def test_scoped_context_compound_conditions_and_get():
    ctx = ScopedFlowContext(
        system={"env": "prod"},
        account={"name": "account_a"},
    )
    ctx.set_var("score", 85)
    ctx.set_var("role", "admin")
    ctx.last_output = "Task successfully completed"

    # 测试 ctx.get() 统一读取
    assert ctx.get("system.env") == "prod"
    assert ctx.get("account.name") == "account_a"
    assert ctx.get("vars.score") == 85
    assert ctx.get("vars.not_exist", "default_val") == "default_val"

    # 测试复合 and / or 条件
    assert ctx.eval_condition("vars.score >= 80 and vars.role == 'admin'") is True
    assert ctx.eval_condition("vars.score >= 90 and vars.role == 'admin'") is False
    assert ctx.eval_condition("vars.score >= 90 or vars.role == 'admin'") is True
    assert (
        ctx.eval_condition(
            "prev.output contains 'failed' or prev.output contains 'completed'"
        )
        is True
    )
    assert (
        ctx.eval_condition("prev.output contains 'failed' or vars.score < 50") is False
    )

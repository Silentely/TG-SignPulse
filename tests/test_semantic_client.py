from tg_signer.semantic.models import Decision, DecisionRequest
from tg_signer.semantic.policy import accept_decision


def test_decision_request_fields():
    req = DecisionRequest(
        kind="result",
        scope="test_scope",
        state={"message": "hello"},
        choices={"success": "成功", "failure": "失败"},
        instructions="判断是否成功",
        request_key="req_1",
        config_revision="rev_1",
    )
    assert req.kind == "result"
    assert req.choices["success"] == "成功"


def test_policy_accept_decision():
    d = Decision(
        status="ok",
        selected="success",
        probabilities={"success": 0.98, "failure": 0.02},
        confidence=0.98,
    )
    assert accept_decision(d, min_probability=0.97, min_margin=0.25)

    d_close = Decision(
        status="ok",
        selected="success",
        probabilities={"success": 0.55, "failure": 0.45},
        confidence=0.55,
    )
    assert not accept_decision(d_close, min_probability=0.50, min_margin=0.20)

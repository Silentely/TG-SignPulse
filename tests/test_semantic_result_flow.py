from __future__ import annotations

from tg_signer.semantic.models import Decision, ResultPolicy
from tg_signer.semantic.policy import result_disposition


def test_explicit_failure_wins_over_semantic_success():
    """显式失败规则优先于大模型判断，大模型返回 success 也绝对不能覆盖"""
    answer = Decision(
        status="ok",
        selected="success",
        probabilities={"success": 1.0, "failure": 0.0},
    )
    pol = ResultPolicy(mode="assist", goal="签到完成")
    assert (
        result_disposition(decision=answer, policy=pol, rule_result="failure")
        == "unchanged"
    )


def test_unmatched_reply_assist_triggers_success():
    """当规则未命中 (unmatched) 时，assist 模式下高置信度 success/already_done 转为 success"""
    pol = ResultPolicy(
        mode="assist", goal="签到成功", min_probability=0.95, min_margin=0.2
    )

    # 1. 成功回复
    ans_success = Decision(
        status="ok",
        selected="success",
        probabilities={"success": 0.98, "failure": 0.01},
    )
    assert (
        result_disposition(decision=ans_success, policy=pol, rule_result="unmatched")
        == "success"
    )

    # 2. 已签到回复同样视为成功
    ans_done = Decision(
        status="ok",
        selected="already_done",
        probabilities={"already_done": 0.96, "failure": 0.01},
    )
    assert (
        result_disposition(decision=ans_done, policy=pol, rule_result="unmatched")
        == "success"
    )


def test_unmatched_reply_assist_triggers_failure_and_wait():
    """规则未命中时，assist 判定为 failure 转为 failure，needs_action 转为 wait"""
    pol = ResultPolicy(
        mode="assist", goal="签到成功", min_probability=0.95, min_margin=0.2
    )

    # 明确失败
    ans_fail = Decision(
        status="ok",
        selected="failure",
        probabilities={"failure": 0.97, "success": 0.01},
    )
    assert (
        result_disposition(decision=ans_fail, policy=pol, rule_result="unmatched")
        == "failure"
    )

    # 需要进一步操作，继续原超时等待
    ans_action = Decision(
        status="ok",
        selected="needs_action",
        probabilities={"needs_action": 0.96, "success": 0.01},
    )
    assert (
        result_disposition(decision=ans_action, policy=pol, rule_result="unmatched")
        == "wait"
    )


def test_low_confidence_or_observe_mode_preserves_wait():
    """置信度不足或处于 observe 模式时不改变原始等待"""
    pol_assist = ResultPolicy(mode="assist", min_probability=0.95, min_margin=0.2)
    low_prob = Decision(
        status="ok",
        selected="success",
        probabilities={"success": 0.80, "failure": 0.15},
    )
    assert (
        result_disposition(
            decision=low_prob, policy=pol_assist, rule_result="unmatched"
        )
        == "wait"
    )

    pol_obs = ResultPolicy(mode="observe", min_probability=0.95, min_margin=0.2)
    high_prob = Decision(
        status="ok",
        selected="success",
        probabilities={"success": 0.99, "failure": 0.01},
    )
    assert (
        result_disposition(decision=high_prob, policy=pol_obs, rule_result="unmatched")
        == "unchanged"
    )

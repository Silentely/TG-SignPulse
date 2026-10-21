from __future__ import annotations

from typing import FrozenSet

from tg_signer.semantic.models import Decision, ResultPolicy, TriagePolicy


def accept_decision(
    decision: Decision,
    *,
    min_probability: float,
    min_margin: float,
    abstain: FrozenSet[str] = frozenset({"unknown", "none"}),
) -> bool:
    if decision.status != "ok":
        return False
    if decision.selected in abstain:
        return False

    probs = decision.probabilities
    if not probs or decision.selected not in probs:
        return False

    top_prob = probs[decision.selected]
    if top_prob < min_probability:
        return False

    sorted_probs = sorted(probs.values(), reverse=True)
    if len(sorted_probs) > 1:
        margin = sorted_probs[0] - sorted_probs[1]
        if margin < min_margin:
            return False

    return True


def triage_disposition(
    *,
    decision: Decision,
    policy: TriagePolicy,
    hard_failure: bool,
) -> str:
    """硬异常保护下的异常与分流处置判定。

    返回值:
        "unchanged" | "stop" | "review"
    """
    if hard_failure or getattr(policy, "mode", "off") != "assist":
        return "unchanged"
    if not accept_decision(
        decision,
        min_probability=policy.min_probability,
        min_margin=policy.min_margin,
        abstain=frozenset({"unknown", "none", "retryable"}),
    ):
        return "unchanged"
    return decision.selected if decision.selected in {"stop", "review"} else "unchanged"


def result_disposition(
    *,
    decision: Decision,
    policy: ResultPolicy,
    rule_result: str,
) -> str:
    """开放结果语义辅助判断处置判定。

    仅当显式规则未命中 (rule_result == "unmatched") 时生效。
    """
    if getattr(policy, "mode", "off") != "assist" or rule_result != "unmatched":
        return "unchanged"
    if not accept_decision(
        decision,
        min_probability=policy.min_probability,
        min_margin=policy.min_margin,
        abstain=frozenset({"unknown", "none"}),
    ):
        return "wait"
    return {
        "success": "success",
        "already_done": "success",
        "failure": "failure",
        "needs_action": "wait",
    }.get(decision.selected, "wait")

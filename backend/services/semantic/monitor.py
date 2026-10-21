from tg_signer.semantic.models import Decision, MonitorPolicy
from tg_signer.semantic.policy import accept_decision


def should_notify(
    *,
    policy: MonitorPolicy,
    keyword_matched: bool,
    decision: Decision,
) -> bool:
    if policy.mode == "off":
        return keyword_matched
    if policy.mode == "observe":
        return policy.source == "keyword_refine" and keyword_matched
    if policy.source == "keyword_refine" and not keyword_matched:
        return False
    return decision.selected == "match" and accept_decision(
        decision,
        min_probability=policy.min_probability,
        min_margin=policy.min_margin,
        abstain=frozenset({"unknown", "none"}),
    )

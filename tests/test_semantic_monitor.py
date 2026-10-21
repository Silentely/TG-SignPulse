from backend.services.semantic.monitor import should_notify
from tg_signer.semantic.models import Decision, MonitorPolicy


def test_semantic_only_can_match_without_keyword():
    policy = MonitorPolicy(mode="assist", source="semantic_only", intent="官方补货")
    answer = Decision(
        status="ok",
        selected="match",
        probabilities={"match": 0.98, "no_match": 0.01, "unknown": 0.01},
        confidence=0.98,
    )
    assert should_notify(policy=policy, keyword_matched=False, decision=answer)


def test_provider_failure_never_sends_semantic_notification():
    policy = MonitorPolicy(mode="assist", source="semantic_only", intent="官方补货")
    assert not should_notify(
        policy=policy,
        keyword_matched=False,
        decision=Decision(status="unavailable"),
    )


def test_observe_mode_keyword_refine_keeps_keyword_notification():
    policy = MonitorPolicy(mode="observe", source="keyword_refine", intent="官方补货")
    # observe 模式 keyword_refine 只要原关键词匹配即通知
    assert should_notify(
        policy=policy,
        keyword_matched=True,
        decision=Decision(status="ok", selected="no_match"),
    )
    assert not should_notify(
        policy=policy,
        keyword_matched=False,
        decision=Decision(status="ok", selected="match"),
    )


def test_observe_mode_semantic_only_never_sends_notification():
    policy = MonitorPolicy(mode="observe", source="semantic_only", intent="官方补货")
    # observe 下 semantic_only 不发业务通知，仅收集判断
    assert not should_notify(
        policy=policy,
        keyword_matched=False,
        decision=Decision(
            status="ok",
            selected="match",
            probabilities={"match": 0.99},
            confidence=0.99,
        ),
    )

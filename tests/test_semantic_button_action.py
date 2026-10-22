from tg_signer.semantic.buttons import extract_clickable_button_candidates
from tg_signer.semantic.models import Decision, SemanticButtonPolicy
from tg_signer.semantic.policy import accept_decision


class DummyBtn:
    def __init__(self, text: str, callback_data: str = "ok"):
        self.text = text
        self.callback_data = callback_data
        self.url = None
        self.web_app = None


def test_semantic_button_selection_logic():
    policy = SemanticButtonPolicy(mode="assist", goal="领取每日签到奖励")
    buttons = [
        [DummyBtn("排行榜"), DummyBtn("个人中心")],
        [DummyBtn("今日签到 (领取奖励)")],
    ]
    candidates = extract_clickable_button_candidates(buttons)
    assert len(candidates) == 3

    choices = {c["ref"]: c["text"] for c in candidates}
    choices["none"] = "没有符合的按钮"

    decision = Decision(
        status="ok",
        selected="btn_1_0",
        probabilities={"btn_1_0": 0.99, "none": 0.01},
        confidence=0.99,
    )

    assert accept_decision(
        decision, min_probability=policy.min_probability, min_margin=policy.min_margin
    )
    selected_ref = decision.selected
    selected_candidate = next((c for c in candidates if c["ref"] == selected_ref), None)
    assert selected_candidate is not None
    assert selected_candidate["text"] == "今日签到 (领取奖励)"


def test_semantic_button_rejection_logic():
    policy = SemanticButtonPolicy(mode="assist", goal="领取每日签到奖励", min_probability=0.98)
    decision = Decision(
        status="ok",
        selected="none",
        probabilities={"none": 0.80, "btn_1_0": 0.20},
        confidence=0.80,
    )
    # 决策未采纳（selected="none" 或置信度未达标）
    accepted = accept_decision(
        decision,
        min_probability=policy.min_probability,
        min_margin=policy.min_margin,
        abstain=frozenset({"none", "unknown"}),
    )
    assert accepted is False

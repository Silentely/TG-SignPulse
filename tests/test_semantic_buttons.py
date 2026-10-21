from tg_signer.semantic.buttons import (
    button_snapshot_revision,
    extract_clickable_button_candidates,
    is_dangerous_button,
)


class DummyBtn:
    def __init__(
        self, text: str, callback_data: str | None = None, url: str | None = None
    ):
        self.text = text
        self.callback_data = callback_data
        self.url = url


def test_extract_only_safe_callback_buttons():
    b_ok = DummyBtn("领取奖励", callback_data="claim_daily")
    b_url = DummyBtn("打开官网", url="https://example.com")
    b_danger = DummyBtn("删除账号并支付", callback_data="delete_account")

    candidates = extract_clickable_button_candidates([[b_ok, b_url, b_danger]])
    # 只有 b_ok 会被提取为候选
    assert len(candidates) == 1
    assert candidates[0]["text"] == "领取奖励"
    assert candidates[0]["ref"] == "btn_0_0"


def test_button_revision_changes_on_tampering():
    b1 = DummyBtn("领取奖励", callback_data="claim_1")
    rev1 = button_snapshot_revision("1001", [b1])

    b2 = DummyBtn("领取奖励", callback_data="claim_2")
    rev2 = button_snapshot_revision("1001", [b2])

    assert rev1 != rev2


def test_is_dangerous_button():
    assert is_dangerous_button("确认支付 $100")
    assert is_dangerous_button("授权登录并绑定")
    assert is_dangerous_button("删除所有数据")
    assert not is_dangerous_button("今日签到")
    assert not is_dangerous_button("领取")

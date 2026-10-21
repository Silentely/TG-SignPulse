from __future__ import annotations

import asyncio
import os
import sys

from tg_signer.semantic.buttons import build_button_snapshot, resolve_button
from tg_signer.semantic.client import JevClient
from tg_signer.semantic.decisions import button_request, result_request, triage_request
from tg_signer.semantic.models import ResultPolicy, TriagePolicy
from tg_signer.semantic.policy import result_disposition, triage_disposition

REAL_API_KEY = os.getenv("JEV_API_KEY", "").strip()
if not REAL_API_KEY and len(sys.argv) > 1:
    REAL_API_KEY = sys.argv[1].strip()


class DummyBtn:
    def __init__(
        self, text: str, callback_data: str | None = None, url: str | None = None
    ):
        self.text = text
        self.callback_data = callback_data
        self.url = url


class DummyChat:
    id = 10001


class DummyUser:
    id = 20002


class DummyMarkup:
    def __init__(self, inline_keyboard):
        self.inline_keyboard = inline_keyboard


class DummyMessage:
    def __init__(self, text, keyboard):
        self.id = 8848
        self.chat = DummyChat()
        self.from_user = DummyUser()
        self.message_thread_id = None
        self.text = text
        self.caption = ""
        self.reply_markup = DummyMarkup(keyboard)


async def run_real_jev_suite():
    if not REAL_API_KEY:
        print(
            "❌ 未提供 Jev API Key。请设置环境变量 JEV_API_KEY 或通过命令行参数传入："
        )
        print("   python scripts/test_real_jev.py <YOUR_API_KEY>")
        sys.exit(1)

    print("=" * 60)
    print("🚀 开始 Jev 官方 API 真实在线测试套件")
    print(f"API Key 前缀: {REAL_API_KEY[:10]}...{REAL_API_KEY[-8:]}")
    print("=" * 60)

    client = JevClient(api_key=REAL_API_KEY, timeout=10.0)

    # -------------------------------------------------------------
    # Test 1: 结果语义判定 (Result Decision: Success Case)
    # -------------------------------------------------------------
    print("\n[测试 1] 结果语义判定 - 成功到账场景")
    req_success = result_request(
        scope="acc1:checkin",
        state={
            "text": "🎉 签到成功！恭喜您获得今日奖励 100 积分，当前连续签到 7 天。",
            "goal": "确认今天的签到奖励已到账",
        },
        request_key="req_res_success",
        config_revision="rev_001",
    )
    dec_success = await client.query_choice(req_success)
    print(f"  -> status: {dec_success.status}")
    print(f"  -> selected: {dec_success.selected}")
    print(f"  -> confidence: {dec_success.confidence:.4f}")
    print(f"  -> probabilities: {dec_success.probabilities}")
    print(f"  -> elapsed_ms: {dec_success.elapsed_ms:.1f}ms")

    # 代码侧策略裁决
    res_policy = ResultPolicy(mode="assist", min_probability=0.9, min_margin=0.2)
    disp_success = result_disposition(
        decision=dec_success,
        policy=res_policy,
        rule_result="unmatched",
    )
    print(f"  -> 代码侧裁决 (result_disposition): {disp_success}")
    assert dec_success.status == "ok", f"Expected ok, got {dec_success.status}"
    assert dec_success.selected == "success", (
        f"Expected success, got {dec_success.selected}"
    )
    assert disp_success == "success"

    # -------------------------------------------------------------
    # Test 2: 结果语义判定 (Result Decision: Failure/Irrelevant Case)
    # -------------------------------------------------------------
    print("\n[测试 2] 结果语义判定 - 无关/系统通知场景")
    req_unmatched = result_request(
        scope="acc1:checkin",
        state={
            "text": "📢 服务器将于今晚 24:00 进行例行停服维护，请悉知。",
            "goal": "确认今天的签到奖励已到账",
        },
        request_key="req_res_unmatched",
        config_revision="rev_001",
    )
    dec_unmatched = await client.query_choice(req_unmatched)
    print(f"  -> status: {dec_unmatched.status}")
    print(f"  -> selected: {dec_unmatched.selected}")
    print(f"  -> confidence: {dec_unmatched.confidence:.4f}")
    print(f"  -> probabilities: {dec_unmatched.probabilities}")
    disp_unmatched = result_disposition(
        decision=dec_unmatched,
        policy=res_policy,
        rule_result="unmatched",
    )
    print(f"  -> 代码侧裁决 (result_disposition): {disp_unmatched}")
    assert dec_unmatched.status == "ok"
    assert dec_unmatched.selected in ("unmatched", "unknown", "failure", "needs_action")

    # -------------------------------------------------------------
    # Test 3: 候选按钮选择 (Button Selection)
    # -------------------------------------------------------------
    print("\n[测试 3] 候选按钮语义选择与版本校验")
    btn_0 = DummyBtn("个人信息", callback_data="user_info")
    btn_1 = DummyBtn("每日领奖", callback_data="daily_checkin")
    btn_2 = DummyBtn("充值余额", callback_data="recharge")  # 敏感操作，应被过滤
    btn_3 = DummyBtn("设置中心", callback_data="settings")
    msg = DummyMessage("请选择您要执行的操作：", [[btn_0, btn_1], [btn_2, btn_3]])

    snapshot = build_button_snapshot(msg)
    print(f"  -> 快照安全候选: {[c.text for c in snapshot.candidates]}")
    print(f"  -> 版本指纹 revision: {snapshot.revision[:16]}...")
    assert "充值余额" not in [c.text for c in snapshot.candidates], (
        "敏感按钮未被成功过滤！"
    )

    # 构造候选字典传递给 button_request
    candidates_dicts = [
        {"ref": c.ref, "text": c.text, "row": c.row, "col": c.column}
        for c in snapshot.candidates
    ]
    req_btn = button_request(
        scope="acc1:checkin",
        state={
            "message_text": msg.text,
            "candidates": candidates_dicts,
            "goal": "点击每日签到领奖按钮",
        },
        request_key="req_btn_sel",
        config_revision=snapshot.revision,
    )
    dec_btn = await client.query_choice(req_btn)
    print(f"  -> status: {dec_btn.status}")
    print(f"  -> selected: {dec_btn.selected}")
    print(f"  -> confidence: {dec_btn.confidence:.4f}")
    print(f"  -> probabilities: {dec_btn.probabilities}")

    # 代码侧按钮防篡改重核
    chosen_btn = resolve_button(
        snapshot=snapshot,
        current_message=msg,
        selected_ref=dec_btn.selected,
    )
    print(f"  -> 点击前重核选择 (resolve_button): {getattr(chosen_btn, 'text', None)}")
    assert chosen_btn is not None
    assert chosen_btn.text == "每日领奖"
    assert chosen_btn.callback_data == "daily_checkin"

    # -------------------------------------------------------------
    # Test 4: 异常分流 (Triage Decision)
    # -------------------------------------------------------------
    print("\n[测试 4] 未预期异常分流判定")
    req_triage = triage_request(
        scope="acc1:checkin",
        state={
            "error_type": "UnexpectedReply",
            "message_text": "由于触发系统风控，请联系人工客服提交手持身份证照片完成解封。",
            "task_goal": "每日常规签到",
        },
        request_key="req_triage_review",
        config_revision="rev_001",
    )
    dec_triage = await client.query_choice(req_triage)
    print(f"  -> status: {dec_triage.status}")
    print(f"  -> selected: {dec_triage.selected}")
    print(f"  -> confidence: {dec_triage.confidence:.4f}")
    print(f"  -> probabilities: {dec_triage.probabilities}")

    triage_pol = TriagePolicy(mode="assist", min_probability=0.8, min_margin=0.1)
    disp_triage = triage_disposition(
        decision=dec_triage,
        policy=triage_pol,
        hard_failure=False,
    )
    print(f"  -> 代码侧分流决策 (triage_disposition): {disp_triage}")
    assert dec_triage.status == "ok"
    assert dec_triage.selected in ("review", "stop")
    assert disp_triage in ("review", "stop")

    await client.close()
    print("\n" + "=" * 60)
    print("🎉 Jev 官方 API 全部真实在线测试 100% 通过！")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_real_jev_suite())

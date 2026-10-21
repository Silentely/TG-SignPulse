from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from backend.services.semantic.review import validate_label
from tg_signer.semantic.buttons import build_button_snapshot, resolve_button
from tg_signer.semantic.models import (
    Decision,
    ResultPolicy,
    TriagePolicy,
)
from tg_signer.semantic.policy import result_disposition, triage_disposition


@pytest.mark.asyncio
async def test_semantic_phase2_lifecycle(tmp_path: Path):
    # 1. 验证按钮快照指纹与版本防御
    msg1 = NS(
        id=101,
        chat=NS(id=12345),
        from_user=NS(id=999),
        message_thread_id=None,
        text="请点击下方按钮签到",
        caption=None,
        reply_markup=NS(
            inline_keyboard=[
                [
                    NS(
                        text="立即签到",
                        callback_data="cb_sign_v1",
                        url=None,
                        web_app=None,
                        login_url=None,
                        pay=False,
                    )
                ]
            ]
        ),
    )
    snap1 = build_button_snapshot(msg1)
    assert len(snap1.candidates) == 1
    btn_ref = snap1.candidates[0].ref

    # 按钮未发生变动时成功解析
    btn_resolved = resolve_button(snap1, msg1, btn_ref)
    assert btn_resolved is not None
    assert getattr(btn_resolved, "text", "") == "立即签到"

    # 若消息已被修改（callback 发生变化），指纹变更导致解析作废，避免过期点击
    msg1_tampered = NS(
        id=101,
        chat=NS(id=12345),
        from_user=NS(id=999),
        message_thread_id=None,
        text="请点击下方按钮签到",
        caption=None,
        reply_markup=NS(
            inline_keyboard=[
                [
                    NS(
                        text="立即签到",
                        callback_data="cb_sign_v2_new",
                        url=None,
                        web_app=None,
                        login_url=None,
                        pay=False,
                    )
                ]
            ]
        ),
    )
    assert resolve_button(snap1, msg1_tampered, btn_ref) is None

    # 2. 验证硬异常保护与分流策略
    triage_pol = TriagePolicy(mode="assist", min_probability=0.95, min_margin=0.2)
    dec_stop = Decision(
        status="ok",
        selected="stop",
        probabilities={"stop": 0.99, "review": 0.01},
    )
    # 硬异常下模型决策被严格阻断
    assert (
        triage_disposition(
            decision=dec_stop,
            policy=triage_pol,
            hard_failure=True,
        )
        == "unchanged"
    )
    # 非硬异常下正常输出受控停止
    assert (
        triage_disposition(
            decision=dec_stop,
            policy=triage_pol,
            hard_failure=False,
        )
        == "stop"
    )

    # 3. 验证结果 assist 与显式规则优先级
    res_pol = ResultPolicy(
        mode="assist", goal="签到成功", min_probability=0.95, min_margin=0.2
    )
    dec_success = Decision(
        status="ok",
        selected="success",
        probabilities={"success": 0.98, "failure": 0.01},
    )
    # 显式规则明确失败时，模型判 success 绝不覆盖
    assert (
        result_disposition(
            decision=dec_success,
            policy=res_pol,
            rule_result="failure",
        )
        == "unchanged"
    )
    # 规则未命中 (unmatched) 时，assist 高置信度判为成功
    assert (
        result_disposition(
            decision=dec_success,
            policy=res_pol,
            rule_result="unmatched",
        )
        == "success"
    )

    # 4. 验证人工标注合法性
    assert validate_label("triage", "review") is True
    assert validate_label("triage", "arbitrary_invalid") is False
    assert validate_label("result", "already_done") is True
    assert validate_label("button", "correct") is True

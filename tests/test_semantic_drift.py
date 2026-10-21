from __future__ import annotations

from datetime import datetime, timezone

from backend.services.semantic.drift import (
    build_baseline,
    collect_drift_candidates,
)
from tg_signer.semantic.decisions import drift_request


def test_without_confirmed_baseline_returns_no_candidate():
    """没有确认基线时，绝对不产生规则变化候选"""
    assert (
        collect_drift_candidates(
            baseline=None,
            observations=[],
            now=datetime(2026, 10, 20, tzinfo=timezone.utc),
        )
        == []
    )

    unconfirmed_baseline = {"scope": "s1", "config_revision": "r1", "confirmed": False}
    rows = [
        {
            "id": "1",
            "request_key": "req_1",
            "scope": "s1",
            "config_revision": "r1",
            "run_id": "run_1",
            "reason_code": "rule_unmatched",
            "observed_at": "2026-10-20T10:00:00Z",
        }
    ]
    assert (
        collect_drift_candidates(
            baseline=unconfirmed_baseline,
            observations=rows,
            now=datetime(2026, 10, 20, 11, tzinfo=timezone.utc),
        )
        == []
    )


def test_single_failure_is_not_drift():
    """单次未匹配不能当成规则变化"""
    baseline = {"scope": "s1", "config_revision": "r1", "confirmed": True}
    rows = [
        {
            "id": "1",
            "request_key": "req_1",
            "scope": "s1",
            "config_revision": "r1",
            "run_id": "run_1",
            "message_refs": ["m1"],
            "observed_at": "2026-10-20T10:00:00Z",
            "reason_code": "rule_unmatched",
        }
    ]
    assert (
        collect_drift_candidates(
            baseline=baseline,
            observations=rows,
            now=datetime(2026, 10, 20, 11, tzinfo=timezone.utc),
        )
        == []
    )


def test_multiple_unique_failures_across_runs_triggers_candidate():
    """当同一 scope+revision 下存在来自不同 run 的至少 3 条独立未匹配证据时，输出 drift 候选"""
    baseline = {
        "scope": "s1",
        "config_revision": "r1",
        "confirmed": True,
        "goal": "签到奖励",
        "expected": "success",
    }
    now = datetime(2026, 10, 20, 15, tzinfo=timezone.utc)
    rows = [
        {
            "id": "obs_1",
            "request_key": "req_1",
            "scope": "s1",
            "config_revision": "r1",
            "run_id": "run_1",
            "reason_code": "rule_unmatched",
            "observed_at": "2026-10-20T12:00:00Z",
            "text": "奖励 +10 今日已到账",
        },
        {
            "id": "obs_2",
            "request_key": "req_2",
            "scope": "s1",
            "config_revision": "r1",
            "run_id": "run_2",
            "reason_code": "rule_unmatched",
            "observed_at": "2026-10-20T13:00:00Z",
            "text": "奖励 +10 今日已到账",
        },
        {
            "id": "obs_3",
            "request_key": "req_3",
            "scope": "s1",
            "config_revision": "r1",
            "run_id": "run_3",
            "reason_code": "rule_unmatched",
            "observed_at": "2026-10-20T14:00:00Z",
            "text": "奖励 +10 今日已到账",
        },
    ]

    candidates = collect_drift_candidates(baseline=baseline, observations=rows, now=now)
    assert len(candidates) == 1
    cand = candidates[0]
    assert cand["scope"] == "s1"
    assert cand["config_revision"] == "r1"
    assert len(cand["evidence_ids"]) == 3
    assert set(cand["evidence_ids"]) == {"obs_1", "obs_2", "obs_3"}


def test_same_run_repetitions_do_not_satisfy_evidence_threshold():
    """来自同一个 run_id 的重复投递不计为跨轮证据"""
    baseline = {"scope": "s1", "config_revision": "r1", "confirmed": True}
    now = datetime(2026, 10, 20, 15, tzinfo=timezone.utc)
    rows = [
        {
            "id": f"obs_{i}",
            "request_key": f"req_{i}",
            "scope": "s1",
            "config_revision": "r1",
            "run_id": "run_same",
            "reason_code": "rule_unmatched",
            "observed_at": "2026-10-20T12:00:00Z",
        }
        for i in range(5)
    ]
    # 虽然有 5 条，但都在同一个 run_same 内，不能当成稳定 Bot 规则变化
    assert collect_drift_candidates(baseline=baseline, observations=rows, now=now) == []


def test_build_baseline_from_human_label():
    """验证从人工审核标签构建基线对象"""
    obs = {
        "id": "obs_10",
        "scope": "acc1:task1:chat1:step1",
        "config_revision": "rev_abc",
        "kind": "result",
        "state": {"goal": "签到金币", "text": "签到成功"},
    }
    baseline = build_baseline(observation=obs, label="success")
    assert baseline is not None
    assert baseline["scope"] == "acc1:task1:chat1:step1"
    assert baseline["config_revision"] == "rev_abc"
    assert baseline["confirmed"] is True
    assert baseline["expected"] == "success"

    # 人工标记为 unknown 或未知的标签不建基线
    assert build_baseline(observation=obs, label="unknown") is None


def test_drift_decision_request_format():
    """验证 drift_request 包含严格的封闭选项"""
    req = drift_request(
        scope="acc1:task1",
        state={"old_rule": "签到成功", "new_samples": ["奖励已到账"]},
        request_key="drift_req_1",
        config_revision="rev_1",
    )
    assert req.kind == "drift"
    assert set(req.choices.keys()) == {
        "equivalent_change",
        "business_changed",
        "no_change",
        "unknown",
    }

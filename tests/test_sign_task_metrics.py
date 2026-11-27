"""机器人回复数值结构化抽取测试。

覆盖:
- 内置通用规则抽取余额/积分（中英文）
- 任务级自定义规则覆盖内置规则，抽不到返回空
- 多来源冲突按 (rank, at) 取值：更权威且更新的胜出
- 非法正则/异常不影响结果
- 历史条目写入 metrics 且旧条目保持可读
- 执行器把任务配置的 metric_rules 传给抽取并写入历史
"""

from __future__ import annotations

import json

import pytest

from backend.services.sign_task_config_build import (
    build_sign_task_config,
    resolve_update_field_values,
)
from backend.services.sign_task_history_store import SignTaskHistoryStore
from backend.services.sign_task_metrics import (
    extract_metrics,
    extract_metrics_safe,
    merge_metric_sets,
    normalize_metric_rules,
    prefer,
)


def test_builtin_rules_extract_balance_and_points():
    metrics = extract_metrics("签到成功！余额：1200，获得积分: 35")
    assert metrics["balance"]["value"] == 1200
    assert metrics["points"]["value"] == 35

    en = extract_metrics("New balance: 1,234.5 credits / 88 points")
    assert en["balance"]["value"] == 1234.5
    assert en["points"]["value"] == 88

    assert extract_metrics("签到成功") == {}


def test_custom_rules_override_and_missing_returns_empty():
    rules = [
        {
            "key": "credits",
            "pattern": r"New Balance\s*[:：]\s*(\d+)\s*credits?",
            "unit": "credits",
            "source": "receipt",
            "rank": 2,
        }
    ]
    metrics = extract_metrics("New Balance: 500 credits", rules)
    assert metrics["credits"] == {
        "value": 500,
        "unit": "credits",
        "source": "receipt",
        "rank": 2,
        "at": metrics["credits"]["at"],
    }
    assert extract_metrics("nothing here", rules) == {}


def test_prefer_compares_rank_then_time():
    stale = {
        "key": "balance",
        "value": 100,
        "unit": "",
        "source": "welcome",
        "rank": 0,
        "at": "2026-01-01T00:00:00+08:00",
    }
    fresh = dict(stale, value=200, at="2026-01-02T00:00:00+08:00")
    authoritative = dict(
        stale,
        value=300,
        rank=2,
        at="2025-12-31T00:00:00+08:00",
    )

    from backend.services.sign_task_metrics import MetricCandidate

    def cand(d):
        return MetricCandidate(**d)

    assert prefer(cand(stale), cand(fresh)).value == 200
    # 更权威的胜出，即使时间更早
    assert prefer(cand(fresh), cand(authoritative)).value == 300
    # 同 rank 时取更新的
    older = dict(stale, rank=2, at="2025-12-31T00:00:00+08:00")
    newer = dict(stale, rank=2, at="2026-01-05T00:00:00+08:00")
    assert prefer(cand(older), cand(newer)).at == newer["at"]


def test_same_key_conflict_resolved_by_rank_and_time():
    rules = [
        {
            "key": "balance",
            "pattern": r"欢迎.*?余额[:：]?\s*(\d+)",
            "source": "welcome",
            "rank": 0,
        },
        {
            "key": "balance",
            "pattern": r"新余额[:：]?\s*(\d+)",
            "source": "service",
            "rank": 5,
        },
    ]
    text = "欢迎回来，当前余额：100\n签到成功，新余额：250"
    metrics = extract_metrics(text, rules, at="2026-02-01T00:00:00+08:00")
    assert metrics["balance"]["value"] == 250
    assert metrics["balance"]["source"] == "service"


def test_merge_metric_sets_uses_prefer():
    existing = {
        "balance": {"value": 1, "unit": "", "source": "a", "rank": 0, "at": "t1"}
    }
    new = {"balance": {"value": 2, "unit": "", "source": "b", "rank": 3, "at": "t0"}}
    merged = merge_metric_sets(existing, new)
    assert merged["balance"]["value"] == 2


def test_invalid_pattern_and_rules_are_safe():
    rules = [{"key": "balance", "pattern": "([0-9]+", "rank": 1}]
    assert extract_metrics("余额: 100", rules) == {}
    assert normalize_metric_rules(None)  # 回退内置规则
    assert extract_metrics_safe(None) == {}
    assert extract_metrics_safe("余额: 10", object()) != {}


def test_history_entry_persists_metrics(tmp_path):
    store = SignTaskHistoryStore(tmp_path)
    metrics = {
        "balance": {"value": 42, "unit": "", "source": "reply", "rank": 0, "at": "t"}
    }
    entry = store.record_run(
        account="acc",
        task="t",
        entry={
            "success": True,
            "message": "ok",
            "last_target_message": "余额: 42",
            "metrics": metrics,
        },
        publish_event=False,
    )
    assert entry["metrics"] == metrics

    # 旧格式条目(无 metrics)仍可正常读取,列表项补空字典
    history_file = store.get_history_file_path("acc", "t")
    raw = json.loads(history_file.read_text(encoding="utf-8"))
    raw.append(
        {
            "time": "2026-01-01T00:00:00+08:00",
            "success": True,
            "message": "legacy",
            "account_name": "acc",
        }
    )
    history_file.write_text(json.dumps(raw), encoding="utf-8")

    items = store.query_history(account="acc", task="t")
    by_message = {item["message"]: item for item in items}
    assert by_message["ok"]["metrics"] == metrics
    assert by_message["legacy"]["metrics"] == {}


def test_task_config_metric_rules_roundtrip():
    rules = [
        {
            "key": "balance",
            "pattern": r"余额[:：]?(\d+)",
            "unit": "",
            "source": "reply",
            "rank": 1,
        }
    ]
    cfg = build_sign_task_config(
        account_name="acc",
        account_names=["acc"],
        sign_at="09:00",
        chats=[],
        metric_rules=rules,
    )
    assert cfg["metric_rules"] == rules

    # 未显式更新沿用既有规则
    assert resolve_update_field_values({"metric_rules": rules})["metric_rules"] == rules
    # 显式空列表清空(回退内置规则)
    assert (
        resolve_update_field_values({"metric_rules": rules}, metric_rules=[])[
            "metric_rules"
        ]
        == []
    )


@pytest.mark.asyncio
async def test_runner_save_run_info_extracts_metrics_into_history():
    from backend.services.sign_task_runner import _runner_save_run_info

    captured = {}

    class _FakeSvc:
        def _save_run_info(self, *args, **kwargs):
            captured["args"] = args
            captured.update(kwargs)
            return {}

    state = {
        "svc": _FakeSvc(),
        "success": True,
        "error_msg": "",
        "last_reply": "签到成功，余额：88，积分: 5",
        "last_target_message": "签到成功，余额：88，积分: 5",
        "task_cfg": {"metric_rules": []},
        "final_logs": [],
        "account_name": "acc",
        "task_name": "t",
    }
    await _runner_save_run_info(state)

    assert captured["metrics"]["balance"]["value"] == 88
    assert captured["metrics"]["points"]["value"] == 5

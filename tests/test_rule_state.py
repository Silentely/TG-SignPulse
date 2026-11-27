"""关键词规则/触发器级持久状态测试。

覆盖:
- 状态跨进程持久化（新实例读同一文件）
- 文件损坏时安全降级为空状态
- 冷却期内拒绝触发，冷却结束后恢复
- 连续失败达到阈值后进入静默，静默到期自动恢复
- 重启补触发只在冷却已过时放行，且不绕过冷却
- 运行时的规则状态门控与补触发规划
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.services.keyword_monitor.rule_state import (
    RulePolicy,
    RuleStateStore,
    evaluate_trigger,
    make_rule_state_key,
)


def _store(tmp_path) -> RuleStateStore:
    return RuleStateStore(tmp_path / "keyword_monitor" / "rule_state.json")


def test_state_persists_across_instances(tmp_path):
    now = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    store = _store(tmp_path)
    store.record_trigger("rule-1", "keyword", now=now)
    store.record_success("rule-1", "keyword")

    # 新实例(模拟进程重启)读取同一份文件
    reloaded = _store(tmp_path).get("rule-1", "keyword")
    assert reloaded["last_trigger_at"] == "2026-03-01T12:00:00Z"
    assert reloaded["consecutive_failures"] == 0


def test_corrupt_state_file_degrades_safely(tmp_path, caplog):
    path = tmp_path / "keyword_monitor" / "rule_state.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not valid json", encoding="utf-8")

    with caplog.at_level("WARNING", logger="backend.keyword_monitor.rule_state"):
        store = RuleStateStore(path)
        assert store.load() == {}
        store.record_trigger("rule-1", "keyword")

    assert any("损坏" in rec.message for rec in caplog.records)
    assert store.get("rule-1", "keyword")["last_trigger_at"]


def test_cooldown_blocks_until_window_elapsed():
    policy = RulePolicy(cooldown_seconds=60)
    now = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    state = {"last_trigger_at": "2026-03-01T12:00:00Z"}

    allowed, reason = evaluate_trigger(state, policy, now=now + timedelta(seconds=30))
    assert (allowed, reason) == (False, "cooldown")

    allowed, reason = evaluate_trigger(state, policy, now=now + timedelta(seconds=61))
    assert (allowed, reason) == (True, "ok")


def test_failure_threshold_enters_and_exits_silence(tmp_path):
    policy = RulePolicy(failure_threshold=2, silence_seconds=300)
    now = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    store = _store(tmp_path)

    store.record_failure("rule-1", "keyword", policy, now=now)
    state = store.get("rule-1", "keyword")
    assert state["consecutive_failures"] == 1
    assert evaluate_trigger(state, policy, now=now)[0] is True

    store.record_failure("rule-1", "keyword", policy, now=now)
    state = store.get("rule-1", "keyword")
    assert state["silence_until"] == "2026-03-01T12:05:00Z"

    allowed, reason = evaluate_trigger(state, policy, now=now + timedelta(seconds=60))
    assert (allowed, reason) == (False, "silenced")

    # 静默到期自动恢复
    allowed, reason = evaluate_trigger(state, policy, now=now + timedelta(seconds=301))
    assert (allowed, reason) == (True, "ok")


def test_restart_catch_up_never_bypasses_cooldown(tmp_path):
    policy = RulePolicy(cooldown_seconds=60, catch_up_on_start=True)
    now = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    store = _store(tmp_path)

    # 无历史状态:冷却已过 → 放行补触发
    planned = store.plan_startup_catch_up([("rule-1", "keyword", policy)], now=now)
    assert planned == [{"rule_id": "rule-1", "trigger_id": "keyword"}]
    state = store.get("rule-1", "keyword")
    assert evaluate_trigger(state, policy, now=now) == (True, "catch_up")

    # 触发后清除补触发标记
    store.record_trigger("rule-1", "keyword", now=now)
    assert store.get("rule-1", "keyword")["catch_up_pending"] is False

    # 冷却期内重启:不得放行补触发
    store2 = _store(tmp_path)
    planned2 = store2.plan_startup_catch_up(
        [("rule-1", "keyword", policy)], now=now + timedelta(seconds=10)
    )
    assert planned2 == []


def test_policy_from_action():
    policy = RulePolicy.from_action(
        {
            "state_cooldown_minutes": 5,
            "state_failure_threshold": 3,
            "state_silence_minutes": 2,
            "state_catch_up_on_start": True,
        }
    )
    assert policy.cooldown_seconds == 300
    assert policy.failure_threshold == 3
    assert policy.silence_seconds == 120
    assert policy.catch_up_on_start is True

    # 显式秒数优先于分钟数
    policy2 = RulePolicy.from_action(
        {"state_cooldown_seconds": 30, "state_cooldown_minutes": 5}
    )
    assert policy2.cooldown_seconds == 30


def test_runtime_gate_and_catch_up_plan(tmp_path, monkeypatch, caplog):
    import backend.services.keyword_monitor.runtime as runtime_mod
    from backend.services.keyword_monitor.rules import KeywordMonitorRule

    monkeypatch.setattr(
        runtime_mod,
        "settings",
        type("S", (), {"resolve_workdir": staticmethod(lambda: tmp_path)})(),
    )
    service = runtime_mod.KeywordMonitorService()
    rule = KeywordMonitorRule(
        account_name="acc",
        task_name="task",
        chat_id=100,
        chat_name="chat",
        message_thread_id=None,
        sender_filter=None,
        action={
            "state_cooldown_seconds": 60,
            "state_catch_up_on_start": True,
        },
    )

    assert service._rule_state_gate(rule) == (True, "ok")
    service._rule_state_record(rule, "trigger")
    assert service._rule_state_gate(rule)[1] == "cooldown"

    # 重启补触发:同一进程内冷却未过,不应放行
    with caplog.at_level("INFO", logger="backend.keyword_monitor.rule_state"):
        service._plan_rule_state_catch_up([rule])
    assert not any("补触发已放行" in rec.message for rec in caplog.records)


def test_make_rule_state_key():
    assert make_rule_state_key("a", "b") == "a::b"


@pytest.mark.asyncio
async def test_on_message_gate_blocks_and_records_trigger(tmp_path, monkeypatch):
    """命中后先过状态门:冷却期内直接跳过,不重复派发。"""
    import backend.services.keyword_monitor.runtime as runtime_mod
    from backend.services.keyword_monitor.rules import KeywordMonitorRule

    monkeypatch.setattr(
        runtime_mod,
        "settings",
        type("S", (), {"resolve_workdir": staticmethod(lambda: tmp_path)})(),
    )
    monkeypatch.setattr(
        "backend.services.config.get_config_service",
        lambda: type("C", (), {"get_global_settings": lambda self: {}})(),
    )

    service = runtime_mod.KeywordMonitorService()
    rule = KeywordMonitorRule(
        account_name="acc",
        task_name="task",
        chat_id=100,
        chat_name="chat",
        message_thread_id=None,
        sender_filter=None,
        action={
            "action": 8,
            "keywords": ["签到"],
            "push_channel": "telegram",
            "state_cooldown_seconds": 3600,
        },
    )
    service._rules = [rule]
    dispatched = []

    async def fake_push(*args, **kwargs):
        dispatched.append(kwargs)
        return True

    service._handle_push = fake_push  # type: ignore[assignment]

    class _Chat:
        id = 100
        title = "chat"
        username = None

    class _Msg:
        id = 1
        text = "签到成功"
        chat = _Chat()
        from_user = None
        message_thread_id = None

    await service._on_message("acc", None, _Msg())
    assert len(dispatched) == 1

    # 同一规则冷却期内再次命中:被状态门拦下
    class _Msg2(_Msg):
        id = 2

    await service._on_message("acc", None, _Msg2())
    assert len(dispatched) == 1

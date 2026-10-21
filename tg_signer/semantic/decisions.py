from __future__ import annotations

from typing import Any

from tg_signer.semantic.models import DecisionRequest


def button_request(
    *,
    scope: str,
    state: dict[str, Any],
    request_key: str,
    config_revision: str,
) -> DecisionRequest:
    """构造候选项按钮选择决策请求"""
    candidates = state.get("candidates") or []
    choices = {c["ref"]: c["text"] for c in candidates if "ref" in c and "text" in c}
    choices["none"] = "无合适选项"
    return DecisionRequest(
        kind="button",
        scope=scope,
        state=state,
        choices=choices,
        instructions="根据操作目标选择最符合的按钮引用，如果没有合适按钮请选择 none。",
        request_key=request_key,
        config_revision=config_revision,
    )


def triage_request(
    *,
    scope: str,
    state: dict[str, Any],
    request_key: str,
    config_revision: str,
) -> DecisionRequest:
    """构造异常与未知回复分流决策请求"""
    choices = {
        "retryable": "临时异常或可重试错误",
        "stop": "已完成或无法继续，应终止执行",
        "review": "出现未预期状况，需要人工介入复核",
        "unknown": "无法判定",
    }
    return DecisionRequest(
        kind="triage",
        scope=scope,
        state=state,
        choices=choices,
        instructions="评估执行中的异常或未知回复，判断是临时性可重试、应终止任务还是需要人工介入复核。",
        request_key=request_key,
        config_revision=config_revision,
    )


def result_request(
    *,
    scope: str,
    state: dict[str, Any],
    request_key: str,
    config_revision: str,
) -> DecisionRequest:
    """构造执行结果开放辅助判断请求"""
    choices = {
        "success": "目标已成功达成",
        "already_done": "目标已在此前完成",
        "failure": "目标明确失败",
        "needs_action": "需要进一步操作",
        "unknown": "无法判定结果",
    }
    return DecisionRequest(
        kind="result",
        scope=scope,
        state=state,
        choices=choices,
        instructions="判断收到的机器人回复是否表明签到/操作已成功、已完成或明确失败。",
        request_key=request_key,
        config_revision=config_revision,
    )


def drift_request(
    *,
    scope: str,
    state: dict[str, Any],
    request_key: str,
    config_revision: str,
) -> DecisionRequest:
    """构造规则漂移与等价性变更判定请求"""
    choices = {
        "equivalent_change": "文本等价变更，业务语义未变",
        "business_changed": "业务流程或交互已改变",
        "no_change": "无变化或临时文案波动",
        "unknown": "无法判定",
    }
    return DecisionRequest(
        kind="drift",
        scope=scope,
        state=state,
        choices=choices,
        instructions="评估观察到的新机器人回复/按钮是否与基线属于业务等价变更，或是业务流程已发生根本变化。",
        request_key=request_key,
        config_revision=config_revision,
    )

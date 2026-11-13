"""Defaults and readable logs for action-level semantic assistance."""

from typing import Any

from tg_signer.log_utils import safe_text_preview

DEFAULT_RESULT_GOAL = "确认今天已完成签到或打卡，或今日奖励已经领取"


def resolve_action_semantic_policy(value: Any) -> dict[str, Any]:
    """Legacy missing policies inherit assist; explicit off/observe stays explicit."""
    policy = dict(value) if isinstance(value, dict) else {}
    policy.setdefault("mode", "assist")
    return policy


def semantic_runtime_unavailable_reason(runtime: Any) -> str:
    """Describe why JEV cannot run without exposing its key or other secrets."""
    if runtime is None:
        return "JEV runtime provider unavailable"
    try:
        config = runtime.config_store.load()
    except Exception as exc:
        return f"JEV config read failed ({type(exc).__name__})"
    if not config.enabled:
        return f"JEV disabled (config_dir={safe_text_preview(runtime.workdir, 120)})"
    if not config.api_key:
        return (
            "API key missing or could not be decrypted "
            f"(config_dir={safe_text_preview(runtime.workdir, 120)})"
        )
    return (
        "JEV service unavailable despite enabled config and available key "
        f"(config_dir={safe_text_preview(runtime.workdir, 120)})"
    )


def semantic_decision_summary(decision: Any) -> str:
    selected = decision.selected
    probabilities = decision.probabilities or {}
    ranked = sorted(probabilities.values(), reverse=True)
    margin = ranked[0] - ranked[1] if len(ranked) > 1 else 0.0
    return (
        f"状态={safe_text_preview(decision.status, 40)} "
        f"选择={safe_text_preview(selected, 80)} "
        f"候选概率={probabilities.get(selected, 0.0):.3f} 差距={margin:.3f} "
        f"缓存命中={decision.cache_hit} "
        f"原因={safe_text_preview(decision.reason_code or decision.error_message, 120) or '无'}"
    )

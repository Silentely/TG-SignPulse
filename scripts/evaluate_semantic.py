from __future__ import annotations

import math
from typing import Any


def wilson_lower(
    correct: int, total: int, *, z: float = 1.959963984540054
) -> float | None:
    if total <= 0:
        return None
    if correct < 0 or correct > total:
        raise ValueError("correct must be between 0 and total")

    p = correct / total
    z2 = z * z
    denom = 1 + z2 / total
    center = p + z2 / (2 * total)
    spread = z * math.sqrt((p * (1 - p) + z2 / (4 * total)) / total)
    lower = (center - spread) / denom
    return max(0.0, lower)


def evaluate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "total": 0,
            "accepted_count": 0,
            "coverage": 0.0,
            "dangerous_false_success": 0,
            "precision": None,
            "wilson_lower": None,
        }

    total = len(rows)
    accepted_rows = [r for r in rows if r.get("accepted")]
    accepted_count = len(accepted_rows)
    coverage = accepted_count / total

    # 危险假成功：原本不是成功，但被模型判定并接受为成功/已完成
    dangerous_false_success = 0
    correct_count = 0

    for r in accepted_rows:
        sel = r.get("selected")
        exp = r.get("expected")
        if sel in ("success", "already_done") and exp not in (
            "success",
            "already_done",
        ):
            dangerous_false_success += 1
        if sel == exp:
            correct_count += 1

    precision = (correct_count / accepted_count) if accepted_count > 0 else None
    w_lower = (
        wilson_lower(correct_count, accepted_count) if accepted_count > 0 else None
    )

    return {
        "total": total,
        "accepted_count": accepted_count,
        "coverage": coverage,
        "dangerous_false_success": dangerous_false_success,
        "precision": precision,
        "wilson_lower": w_lower,
    }


def evaluate_button_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """评估候选项按钮选择准确率与过期点击数"""
    if not rows:
        return {
            "total": 0,
            "accepted_count": 0,
            "coverage": 0.0,
            "stale_clicks": 0,
            "precision": None,
            "wilson_lower": None,
        }

    total = len(rows)
    accepted_rows = [r for r in rows if r.get("accepted")]
    accepted_count = len(accepted_rows)
    coverage = accepted_count / total

    correct_count = 0
    stale_clicks = 0

    for r in accepted_rows:
        sel = r.get("selected")
        exp = r.get("expected")
        is_stale = r.get("is_stale", False)
        if is_stale:
            if sel != "none":
                stale_clicks += 1
            elif exp == "none":
                correct_count += 1
        else:
            if sel == exp:
                correct_count += 1

    precision = (correct_count / accepted_count) if accepted_count > 0 else None
    w_lower = (
        wilson_lower(correct_count, accepted_count) if accepted_count > 0 else None
    )

    return {
        "total": total,
        "accepted_count": accepted_count,
        "coverage": coverage,
        "stale_clicks": stale_clicks,
        "precision": precision,
        "wilson_lower": w_lower,
    }


def evaluate_triage_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """评估异常分流：硬异常被覆盖数、新增重试次数与处置准确率"""
    if not rows:
        return {
            "total": 0,
            "accepted_count": 0,
            "coverage": 0.0,
            "hard_failure_override": 0,
            "extra_retries": 0,
            "precision": None,
            "wilson_lower": None,
        }

    total = len(rows)
    accepted_rows = [r for r in rows if r.get("accepted")]
    accepted_count = len(accepted_rows)
    coverage = accepted_count / total

    correct_count = 0
    hard_failure_override = 0
    extra_retries = 0

    for r in accepted_rows:
        sel = r.get("selected")
        exp = r.get("expected")
        hard_failure = r.get("hard_failure", False)

        # 硬异常绝对不能被改变
        if hard_failure and r.get("disposition") != "unchanged":
            hard_failure_override += 1

        # retryable 建议不能转换为实际额外重试
        if r.get("retried_due_to_semantic", False):
            extra_retries += 1

        if sel == exp:
            correct_count += 1

    precision = (correct_count / accepted_count) if accepted_count > 0 else None
    w_lower = (
        wilson_lower(correct_count, accepted_count) if accepted_count > 0 else None
    )

    return {
        "total": total,
        "accepted_count": accepted_count,
        "coverage": coverage,
        "hard_failure_override": hard_failure_override,
        "extra_retries": extra_retries,
        "precision": precision,
        "wilson_lower": w_lower,
    }

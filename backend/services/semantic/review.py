from __future__ import annotations

from typing import FrozenSet

# 合法的枚举型观察人工标注集合
TRIAGE_LABELS: FrozenSet[str] = frozenset({"retryable", "stop", "review", "unknown"})
RESULT_LABELS: FrozenSet[str] = frozenset(
    {"success", "already_done", "failure", "needs_action", "unknown"}
)
BUTTON_LABELS: FrozenSet[str] = frozenset({"correct", "incorrect", "none"})
MONITOR_LABELS: FrozenSet[str] = frozenset({"match", "no_match", "unknown"})

ALLOWED_LABELS_BY_KIND: dict[str, FrozenSet[str]] = {
    "triage": TRIAGE_LABELS,
    "result": RESULT_LABELS,
    "button": BUTTON_LABELS,
    "monitor": MONITOR_LABELS,
}

# 文本型业务意图标注类型（例如目标按钮文案、成功正则基准文案、监控目标意图等）
FREEFORM_TEXT_KINDS: FrozenSet[str] = frozenset(
    {"button_label", "success_text", "monitor_intent"}
)


def validate_label(kind: str, label: str) -> bool:
    """校验指定类型的标注值是否合法"""
    if (
        not label
        or not isinstance(label, str)
        or len(label.strip()) == 0
        or len(label) > 64
    ):
        return False
    if kind in ALLOWED_LABELS_BY_KIND:
        return label in ALLOWED_LABELS_BY_KIND[kind]
    if kind in FREEFORM_TEXT_KINDS:
        return True
    return False

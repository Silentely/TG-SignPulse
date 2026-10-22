from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DecisionRequest:
    kind: str
    scope: str
    state: dict[str, Any]
    choices: dict[str, str]
    instructions: str
    request_key: str
    config_revision: str


@dataclass(frozen=True)
class Decision:
    status: str
    selected: str = "unknown"
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    model: str = ""
    elapsed_ms: float = 0.0
    input_tokens: int = 0
    reason_code: str = ""
    http_status: int | None = None
    error_message: str = ""


@dataclass(frozen=True)
class SemanticResultPolicy:
    mode: str = "off"
    goal: str = ""
    min_probability: float = 0.97
    min_margin: float = 0.25


@dataclass(frozen=True)
class SemanticButtonPolicy:
    mode: str = "off"
    goal: str = ""
    min_probability: float = 0.98
    min_margin: float = 0.30


@dataclass(frozen=True)
class SemanticTriagePolicy:
    mode: str = "off"
    min_probability: float = 0.97
    min_margin: float = 0.25


@dataclass(frozen=True)
class MonitorPolicy:
    mode: str = "off"
    source: str = "keyword_refine"
    intent: str = ""
    min_probability: float = 0.90
    min_margin: float = 0.20


class SemanticReviewRequired(RuntimeError):
    """语义判定需人工复核，整流程受控停止"""

    non_retryable: bool = True
    failure_code: str = "semantic_review_required"
    semantic_disposition: str = "review"


class SemanticStopRequested(RuntimeError):
    """语义判定要求终止执行，整流程受控停止"""

    non_retryable: bool = True
    failure_code: str = "semantic_stop_requested"
    semantic_disposition: str = "stop"


TriagePolicy = SemanticTriagePolicy
ResultPolicy = SemanticResultPolicy
ButtonPolicy = SemanticButtonPolicy


def config_revision(config: dict[str, Any]) -> str:
    """计算任务配置的确定性业务哈希版本（排除顶层运行时 last_run 字段）"""
    business = {key: value for key, value in config.items() if key != "last_run"}
    raw = json.dumps(
        business,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

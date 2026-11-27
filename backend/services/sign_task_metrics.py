"""机器人回复的数值结构化抽取。

从回复原文中按可配置规则抽取「余额 / 积分」等数值，写入历史条目。

规则来源：任务配置 ``metric_rules``（列表），每项:

    {"key": "balance", "pattern": "余额[:：]?\\s*([\\d.,]+)",
     "unit": "credits", "source": "service", "rank": 2}

未配置时使用内置通用规则（覆盖余额/积分等常见中英文表述，不含任何
特定机器人的固定文案）。同一次回复里多个候选命中时，按
``(rank, at)`` 比较取值——来源更权威者胜出，同等来源取更新时间较晚者，
与上游 ``tg_rewards.prefer`` 的口径一致。

抽不到数值时字段留空；任何解析异常都只返回空结果，绝不影响任务执行与历史写入。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger("backend.sign_task_metrics")

# 抽取文本上限：避免超长回复让正则耗尽时间
MAX_METRIC_TEXT_CHARS = 8000

DEFAULT_METRIC_RULES: List[Dict[str, Any]] = [
    {
        "key": "balance",
        "pattern": r"余额[:：=]?\s*([\d][\d,]*(?:\.\d+)?)",
        "unit": "",
        "source": "reply",
        "rank": 0,
    },
    {
        "key": "balance",
        "pattern": r"(?i)\bbalance[:：=]?\s*([\d][\d,]*(?:\.\d+)?)",
        "unit": "",
        "source": "reply",
        "rank": 0,
    },
    {
        "key": "points",
        "pattern": r"积分[:：=]?\s*([\d][\d,]*(?:\.\d+)?)",
        "unit": "",
        "source": "reply",
        "rank": 0,
    },
    {
        "key": "points",
        "pattern": r"(?i)\bpoints?[:：=]?\s*([\d][\d,]*(?:\.\d+)?)",
        "unit": "",
        "source": "reply",
        "rank": 0,
    },
    # 「数值 + 单位」在后的常见表述(如 "1,234 credits" / "35 积分")
    {
        "key": "balance",
        "pattern": r"([\d][\d,]*(?:\.\d+)?)\s*(?i:credits?|balance)\b",
        "unit": "",
        "source": "reply",
        "rank": 0,
    },
    {
        "key": "points",
        "pattern": r"([\d][\d,]*(?:\.\d+)?)\s*(?i:points?|积分)",
        "unit": "",
        "source": "reply",
        "rank": 0,
    },
]

_NUMBER_RE = re.compile(r"^-?\d[\d,]*(?:\.\d+)?$")


@dataclass(frozen=True)
class MetricCandidate:
    key: str
    value: Any
    unit: str
    source: str
    rank: int
    at: str


def _parse_number(raw: str) -> Optional[Any]:
    text = str(raw or "").strip().replace(",", "")
    if not _NUMBER_RE.match(text):
        return None
    try:
        if "." in text:
            return float(text)
        return int(text)
    except (TypeError, ValueError):
        return None


def _coerce_rank(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def normalize_metric_rules(raw: Any) -> List[Dict[str, Any]]:
    """清洗任务级规则配置；非法项丢弃，非法正则保留但运行时跳过。"""
    if not isinstance(raw, list):
        return [dict(rule) for rule in DEFAULT_METRIC_RULES]
    cleaned: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        pattern = str(item.get("pattern") or "").strip()
        if not key or not pattern:
            continue
        cleaned.append(
            {
                "key": key,
                "pattern": pattern,
                "unit": str(item.get("unit") or "").strip(),
                "source": str(item.get("source") or "reply").strip() or "reply",
                "rank": _coerce_rank(item.get("rank")),
            }
        )
    return cleaned or [dict(rule) for rule in DEFAULT_METRIC_RULES]


def prefer(
    current: Optional[MetricCandidate], candidate: MetricCandidate
) -> MetricCandidate:
    """更权威且更新的候选胜出：先比 rank，再比时间（与上游 prefer 一致）。"""
    if current is None:
        return candidate
    return (
        candidate
        if (candidate.rank, candidate.at)
        > (
            current.rank,
            current.at,
        )
        else current
    )


def extract_metrics(
    text: Any,
    rules: Any = None,
    *,
    at: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """按规则抽取数值，返回 ``{key: {value, unit, source, rank, at}}``。

    同一 key 的多个命中按 ``(rank, at)`` 取最优；同一规则内多次命中取最后一次
    （数值回执通常出现在回复尾部）。抽不到返回空 dict。
    """
    if not text:
        return {}
    body = str(text)[:MAX_METRIC_TEXT_CHARS]
    timestamp = at or datetime.now().astimezone().isoformat()
    normalized_rules = normalize_metric_rules(rules)

    winners: Dict[str, MetricCandidate] = {}
    for rule in normalized_rules:
        try:
            compiled = re.compile(rule["pattern"])
        except re.error as exc:
            logger.warning("跳过非法数值抽取正则 %r: %s", rule.get("key"), exc)
            continue
        try:
            matches = list(compiled.finditer(body))
        except Exception as exc:
            logger.warning("数值抽取匹配失败 %r: %s", rule.get("key"), exc)
            continue
        if not matches:
            continue
        # 同一规则多次命中取最后一次（数值回执通常在回复尾部）
        match = matches[-1]
        group = match.group(1) if match.groups() else match.group(0)
        value = _parse_number(group)
        if value is None:
            continue
        candidate = MetricCandidate(
            key=rule["key"],
            value=value,
            unit=str(rule.get("unit") or ""),
            source=str(rule.get("source") or "reply"),
            rank=_coerce_rank(rule.get("rank")),
            at=timestamp,
        )
        winners[rule["key"]] = prefer(winners.get(rule["key"]), candidate)

    return {
        key: {
            "value": item.value,
            "unit": item.unit,
            "source": item.source,
            "rank": item.rank,
            "at": item.at,
        }
        for key, item in winners.items()
    }


def extract_metrics_safe(
    text: Any, rules: Any = None, *, at: Optional[str] = None
) -> Dict[str, Dict[str, Any]]:
    """抽取入口的安全包装：任何异常都返回空结果并记日志。"""
    try:
        return extract_metrics(text, rules, at=at)
    except Exception as exc:
        logger.warning("数值抽取异常，按无数据处理: %s", exc)
        return {}


def merge_metric_sets(existing: Any, new: Any) -> Dict[str, Dict[str, Any]]:
    """合并两组数值（如欢迎菜单与本次回执），按 (rank, at) 取更优。"""
    merged: Dict[str, Dict[str, Any]] = {}
    for source in (existing, new):
        if not isinstance(source, dict):
            continue
        for key, item in source.items():
            if not isinstance(item, dict):
                continue
            candidate = MetricCandidate(
                key=str(key),
                value=item.get("value"),
                unit=str(item.get("unit") or ""),
                source=str(item.get("source") or ""),
                rank=_coerce_rank(item.get("rank")),
                at=str(item.get("at") or ""),
            )
            current = merged.get(str(key))
            if current is None:
                merged[str(key)] = {
                    "value": candidate.value,
                    "unit": candidate.unit,
                    "source": candidate.source,
                    "rank": candidate.rank,
                    "at": candidate.at,
                }
                continue
            current_candidate = MetricCandidate(
                key=str(key),
                value=current.get("value"),
                unit=str(current.get("unit") or ""),
                source=str(current.get("source") or ""),
                rank=_coerce_rank(current.get("rank")),
                at=str(current.get("at") or ""),
            )
            best = prefer(current_candidate, candidate)
            merged[str(key)] = {
                "value": best.value,
                "unit": best.unit,
                "source": best.source,
                "rank": best.rank,
                "at": best.at,
            }
    return merged


def iter_metric_items(metrics: Any) -> Iterable[Tuple[str, Dict[str, Any]]]:
    """遍历合法数值项（供展示层复用）。"""
    if not isinstance(metrics, dict):
        return []
    return [(str(key), item) for key, item in metrics.items() if isinstance(item, dict)]

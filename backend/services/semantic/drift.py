from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def build_baseline(*, observation: dict[str, Any], label: str) -> dict[str, Any] | None:
    """从人工审核标签建立规则基线"""
    if not label or label in {"unknown", "none"}:
        return None

    state = observation.get("state") or {}
    return {
        "scope": observation.get("scope", ""),
        "config_revision": observation.get("config_revision", ""),
        "confirmed": True,
        "expected": label,
        "kind": observation.get("kind", ""),
        "goal": state.get("goal", ""),
        "baseline_text": state.get("text", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _parse_iso(ts_str: str) -> datetime | None:
    try:
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        return datetime.fromisoformat(ts_str)
    except Exception:
        return None


def collect_drift_candidates(
    *,
    baseline: dict[str, Any] | None,
    observations: list[dict[str, Any]],
    now: datetime,
) -> list[dict[str, Any]]:
    """确定性聚合并收集规则变化候选证据"""
    if baseline is None or not baseline.get("confirmed"):
        return []

    target_scope = baseline.get("scope")
    target_revision = baseline.get("config_revision")
    window_start = now - timedelta(hours=24)

    valid_rows = []
    for r in observations:
        if r.get("scope") != target_scope:
            continue
        if r.get("config_revision") != target_revision:
            continue
        if r.get("reason_code") not in {
            "rule_unmatched",
            "button_missing",
            "intent_mismatch",
        }:
            continue

        obs_at_str = r.get("observed_at")
        if obs_at_str:
            dt = _parse_iso(obs_at_str)
            if dt and dt < window_start:
                continue

        valid_rows.append(r)

    # 1. 按 request_key 去重（排除同一事件的重复推送）
    unique_by_req: dict[str, dict[str, Any]] = {}
    for r in valid_rows:
        req_k = r.get("request_key") or r.get("id")
        if req_k and req_k not in unique_by_req:
            unique_by_req[req_k] = r

    if len(unique_by_req) < 3:
        return []

    # 2. 验证证据必须来自至少两个不同的 run_id
    run_ids = {r.get("run_id") for r in unique_by_req.values() if r.get("run_id")}
    if len(run_ids) < 2:
        return []

    evidence_ids = [r["id"] for r in unique_by_req.values() if "id" in r]
    samples = [r.get("text") for r in unique_by_req.values() if r.get("text")]

    candidate = {
        "scope": target_scope,
        "config_revision": target_revision,
        "evidence_ids": evidence_ids,
        "evidence_count": len(evidence_ids),
        "samples": samples[:5],
        "baseline_expected": baseline.get("expected"),
        "kind": baseline.get("kind"),
    }
    return [candidate]

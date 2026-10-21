import json
from pathlib import Path

from scripts.evaluate_semantic import (
    evaluate_button_rows,
    evaluate_rows,
    evaluate_triage_rows,
    wilson_lower,
)


def test_wilson_lower_calculation():
    # 样本不足或空分母
    assert wilson_lower(0, 0) is None
    # 100 例全对下界不足 99%
    assert wilson_lower(100, 100) < 0.99
    # 381 例全对下界约为 99%
    assert wilson_lower(381, 381) >= 0.99


def test_evaluate_rows_metrics():
    rows = [
        {"expected": "success", "selected": "success", "accepted": True},
        {
            "expected": "needs_action",
            "selected": "success",
            "accepted": True,
        },  # 危险假阳性
        {"expected": "success", "selected": "unknown", "accepted": False},  # 弃权
    ]
    report = evaluate_rows(rows)
    assert report["total"] == 3
    assert report["dangerous_false_success"] == 1
    assert report["coverage"] == 2 / 3


def test_evaluate_button_rows_from_fixture():
    fixture_path = Path("tests/fixtures/semantic/button.jsonl")
    assert fixture_path.exists()
    rows = [
        json.loads(line)
        for line in fixture_path.read_text().splitlines()
        if line.strip()
    ]
    report = evaluate_button_rows(rows)
    assert report["total"] == 5
    assert report["accepted_count"] == 4
    assert report["stale_clicks"] == 0  # 即使是 stale，selected 为 none 不算错误点击
    assert report["precision"] == 1.0


def test_evaluate_triage_rows_from_fixture():
    fixture_path = Path("tests/fixtures/semantic/triage.jsonl")
    assert fixture_path.exists()
    rows = [
        json.loads(line)
        for line in fixture_path.read_text().splitlines()
        if line.strip()
    ]
    report = evaluate_triage_rows(rows)
    assert report["total"] == 5
    assert report["accepted_count"] == 4
    assert report["hard_failure_override"] == 0
    assert report["extra_retries"] == 0
    assert report["precision"] == 1.0

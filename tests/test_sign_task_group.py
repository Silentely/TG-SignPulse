"""sign_task_group 纯函数测试。"""
from __future__ import annotations

from typing import Any, List, Optional, Sequence

from backend.services.sign_task_group import (
    aggregate_tasks,
    filter_related_task_infos,
    first_real_account,
    select_latest_last_run,
    task_group_key,
)


def _norm(names: Optional[Sequence[Any]] = None, primary: Optional[str] = None) -> List[str]:
    out: List[str] = []
    for n in list(names or []):
        s = str(n or "").strip()
        if s and s not in out:
            out.append(s)
    if primary and primary not in out:
        out.append(primary)
    return out


def test_first_real_and_last_run():
    assert first_real_account(["*", "a"], "x") == "a"
    assert first_real_account(["*"], "x") == "x"
    assert select_latest_last_run(
        {"time": "2026-01-01"}, {"time": "2026-01-02"}
    )["time"] == "2026-01-02"


def test_task_group_key():
    assert task_group_key({"task_group_id": "g1", "name": "t"}) == "group:g1"
    assert task_group_key({"account_name": "a", "name": "t"}) == "single:a:t"


def test_aggregate_and_related():
    tasks = [
        {
            "name": "t1",
            "account_name": "a",
            "account_names": ["a", "b"],
            "task_group_id": "g1",
            "last_run": {"time": "1"},
        },
        {
            "name": "t1",
            "account_name": "b",
            "account_names": ["a", "b"],
            "task_group_id": "g1",
            "last_run": {"time": "2"},
        },
    ]
    agg = aggregate_tasks(tasks, normalize_account_names=_norm)
    assert len(agg) == 1
    assert set(agg[0]["account_names"]) == {"a", "b"}
    assert agg[0]["last_run"]["time"] == "2"

    related = filter_related_task_infos(
        tasks, "t1", "a", normalize_account_names=_norm
    )
    assert len(related) == 2
    related2 = filter_related_task_infos(
        tasks, "missing", None, normalize_account_names=_norm
    )
    assert related2 == []

from pathlib import Path

from backend.services.semantic.store import SemanticStore


def test_semantic_store_append_and_duplicate(tmp_path: Path):
    store = SemanticStore(tmp_path)
    obs = {
        "scope": "acc_1:task_1",
        "request_key": "k_1",
        "kind": "result",
        "observed_at": "2026-10-21T00:00:00Z",
        "selected": "success",
    }
    obs_id = store.append(obs)
    assert obs_id is not None

    # 重复 request_key 应该幂等返回相同 obs_id
    obs_id2 = store.append(obs)
    assert obs_id2 == obs_id

    records = store.list_observations(scope="acc_1:task_1")
    assert records["total"] == 1
    assert records["items"][0]["selected"] == "success"

    # 测试人工打标
    store.label(obs_id, scope="acc_1:task_1", label="already_done")
    records_after = store.list_observations(scope="acc_1:task_1")
    assert records_after["items"][0]["human_label"] == "already_done"

    # 测试容量统计
    stats = store.get_capacity_stats()
    assert stats["monitor_keys_capacity"] == 10000
    assert stats["is_full"] is False

import json

import pytest


def test_artifact_redacts_sensitive_fields_and_is_retained_for_all_terminal_states(
    tmp_path, monkeypatch
):
    from backend.services import run_artifacts as store

    monkeypatch.setattr(store, "artifact_root", lambda: tmp_path)
    for state in ("success", "failed", "timeout", "cancelled", "partial", "unknown"):
        store.record_run_artifact(
            run_id=state,
            config_revision="r1",
            graph_revision="g1",
            terminal_status=state,
            node_outcomes=[{"node_id": "a", "api_key": "secret-value"}],
            events=[],
            receipts=[],
        )
        row = store.load_run_artifact(state)
        assert row["terminal_status"] == state
        assert "secret-value" not in json.dumps(row)
    with pytest.raises(ValueError):
        store.load_run_artifact("../secrets")


def test_artifact_retention_removes_oldest_record(tmp_path, monkeypatch):
    from backend.services import run_artifacts as store

    monkeypatch.setattr(store, "artifact_root", lambda: tmp_path)
    monkeypatch.setattr(store, "MAX_ARTIFACTS", 2)
    for i in range(3):
        store.record_run_artifact(
            run_id=f"run{i}",
            config_revision="r",
            graph_revision="g",
            terminal_status="failed",
            node_outcomes=[],
            events=[],
            receipts=[],
        )
    assert len(list(tmp_path.glob("*.json"))) == 2
    assert store.load_run_artifact("run0") is None

import pytest


def test_runbook_actions_are_dry_run_by_default(monkeypatch):
    from backend.services.ops_runbooks import apply_runbook_action

    assert apply_runbook_action("refresh_task_cache")["applied"] is False
    with pytest.raises(ValueError, match="NOT_ALLOWED"):
        apply_runbook_action("delete_all_data")

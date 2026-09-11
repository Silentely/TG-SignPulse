from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.sign_tasks import SignTaskService
from backend.services.sign_task_history_index import append_index_entry, build_index_entry
from backend.core.auth import get_current_user
from backend.models.user import User


def test_get_history_trends(tmp_path: Path):
    service = SignTaskService()
    service.run_history_dir = tmp_path
    # 添加几条 index 条目
    append_index_entry(
        service.run_history_dir,
        build_index_entry(
            time="2026-09-11 10:00:00",
            account_name="test_acc",
            task_name="task_1",
            success=True,
            message="ok",
            failure_category="",
        ),
    )
    append_index_entry(
        service.run_history_dir,
        build_index_entry(
            time="2026-09-11 11:00:00",
            account_name="test_acc",
            task_name="task_2",
            success=False,
            message="failed",
            failure_category="timeout",
        ),
    )

    result = service.get_history_trends(days=7)
    assert result["days"] == 7
    assert result["total_runs"] == 2
    assert result["total_success"] == 1
    assert result["total_failed"] == 1
    assert result["overall_success_rate"] == 0.5
    assert len(result["trends"]) == 7
    assert result["categories"].get("timeout") == 1


def test_api_ops_trends():
    mock_user = User(username="admin")
    app.dependency_overrides[get_current_user] = lambda: mock_user
    client = TestClient(app)
    response = client.get("/api/ops/trends?days=7")
    assert response.status_code == 200
    data = response.json()
    assert "days" in data
    assert "total_runs" in data
    assert "overall_success_rate" in data
    assert "trends" in data
    assert len(data["trends"]) == 7
    app.dependency_overrides.clear()

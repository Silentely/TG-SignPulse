from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from backend.core.auth import get_current_user
from backend.main import app
from backend.models.user import User
from backend.services.sign_task_history_index import (
    append_index_entry,
    build_index_entry,
)
from backend.services.sign_tasks import SignTaskService


def test_get_history_trends(tmp_path: Path):
    service = SignTaskService()
    service.run_history_dir = tmp_path
    # 窗口起点为 now-(days-1)，日期必须动态生成，硬编码日期会随日历推进跌出 7 天窗口
    entry_day = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    # 添加几条 index 条目
    append_index_entry(
        service.run_history_dir,
        build_index_entry(
            time=f"{entry_day} 10:00:00",
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
            time=f"{entry_day} 11:00:00",
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

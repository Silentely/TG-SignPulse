from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.api.routes.semantic import get_semantic_store
from backend.core.auth import get_current_user
from backend.main import app
from backend.services.semantic.store import SemanticStore


def test_suggestions_list_and_dismiss_api(tmp_path: Path):
    store = SemanticStore(tmp_path)
    app.dependency_overrides[get_current_user] = lambda: {"username": "admin"}
    app.dependency_overrides[get_semantic_store] = lambda: store

    client = TestClient(app)

    # 初始为空
    resp = client.get("/api/semantic/suggestions?account_name=acc1&task_name=daily")
    assert resp.status_code == 200
    assert resp.json() == []

    # 写入一条建议
    s_id = store.save_suggestion(
        {
            "scope": "acc1:daily",
            "account_name": "acc1",
            "task_name": "daily",
            "kind": "button_label",
            "patch": {
                "op": "replace",
                "path": "/chats/0/actions/1/text",
                "old": "签到",
                "value": "领奖",
            },
        }
    )

    # 查询命中
    resp = client.get("/api/semantic/suggestions?account_name=acc1&task_name=daily")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["id"] == s_id
    assert items[0]["status"] == "pending"

    # 忽略建议
    resp_dis = client.post(
        f"/api/semantic/suggestions/{s_id}/dismiss",
        json={"account_name": "acc1", "task_name": "daily"},
    )
    assert resp_dis.status_code == 200
    assert resp_dis.json()["status"] == "dismissed"

    # 再次查询待处理建议，已被排除
    resp_pending = client.get(
        "/api/semantic/suggestions?account_name=acc1&task_name=daily&status=pending"
    )
    assert resp_pending.status_code == 200
    assert resp_pending.json() == []

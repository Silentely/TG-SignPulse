from fastapi.testclient import TestClient

from backend.api.routes.semantic import get_semantic_store
from backend.core.auth import get_current_user
from backend.main import app
from backend.services.semantic.store import SemanticStore


def test_semantic_review_api_flow(tmp_path):
    store = SemanticStore(tmp_path)
    obs_id = store.append(
        {
            "scope": "acc_1:task_1",
            "request_key": "k_1",
            "kind": "result",
            "selected": "success",
        }
    )

    app.dependency_overrides[get_current_user] = lambda: {"username": "admin"}
    app.dependency_overrides[get_semantic_store] = lambda: store
    client = TestClient(app)

    # 分页查询
    r = client.get("/api/semantic/observations?account_name=acc_1&task_name=task_1")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == obs_id

    # 打标
    r_label = client.put(
        f"/api/semantic/observations/{obs_id}/label",
        json={"account_name": "acc_1", "task_name": "task_1", "label": "already_done"},
    )
    assert r_label.status_code == 200
    assert r_label.json()["label"] == "already_done"

    # 再次查询验证 label 已关联
    r2 = client.get("/api/semantic/observations?account_name=acc_1&task_name=task_1")
    assert r2.json()["items"][0]["human_label"] == "already_done"

    # 跨 scope 打标拒绝
    r_err = client.put(
        f"/api/semantic/observations/{obs_id}/label",
        json={"account_name": "acc_2", "task_name": "task_1", "label": "already_done"},
    )
    assert r_err.status_code == 403

    app.dependency_overrides.clear()

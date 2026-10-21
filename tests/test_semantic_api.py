from fastapi.testclient import TestClient

from backend.api.routes.semantic import get_jev_store, get_semantic_store
from backend.core.auth import get_current_user
from backend.main import app
from backend.services.semantic.config import JevConfigStore
from backend.services.semantic.store import SemanticStore


def test_semantic_api_flow(tmp_path):
    store = JevConfigStore(tmp_path)
    sem_store = SemanticStore(tmp_path)
    app.dependency_overrides[get_current_user] = lambda: {"username": "admin"}
    app.dependency_overrides[get_jev_store] = lambda: store
    app.dependency_overrides[get_semantic_store] = lambda: sem_store

    client = TestClient(app)

    # 初始读取
    r = client.get("/api/semantic/config")
    assert r.status_code == 200
    assert r.json()["has_api_key"] is False
    assert r.json()["monitor_keys_usage"]["monitor_keys_capacity"] == 10000

    # 更新配置
    r = client.patch(
        "/api/semantic/config", json={"enabled": True, "api_key": "test_key_12345"}
    )
    assert r.status_code == 200
    assert r.json()["enabled"] is True
    assert r.json()["has_api_key"] is True

    # 再次读取验证
    r = client.get("/api/semantic/config")
    assert r.status_code == 200
    assert r.json()["enabled"] is True
    assert r.json()["has_api_key"] is True

    app.dependency_overrides.clear()

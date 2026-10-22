from fastapi.testclient import TestClient

from backend.api.routes.semantic import get_jev_store, get_semantic_store
from backend.core.auth import get_current_user
from backend.main import app
from backend.services.semantic.config import JevConfigStore
from backend.services.semantic.store import SemanticStore
from tg_signer.semantic.client import JevClient
from tg_signer.semantic.models import Decision


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


def test_semantic_test_uses_saved_base_url_and_model(tmp_path, monkeypatch):
    """② 验收测试：/semantic/test 确实使用已保存的 base_url/model 与 timeout_seconds"""
    store = JevConfigStore(tmp_path)
    sem_store = SemanticStore(tmp_path)

    # 保存自定义配置
    store.save_patch(
        {
            "mode": "custom",
            "base_url": "https://api.example.com/v1",
            "model": "jev-custom-001",
            "api_key": "ah-test-secret-key-123456",
            "timeout_seconds": 12.0,
            "enabled": True,
        }
    )

    app.dependency_overrides[get_current_user] = lambda: {"username": "admin"}
    app.dependency_overrides[get_jev_store] = lambda: store
    app.dependency_overrides[get_semantic_store] = lambda: sem_store

    captured_client_kwargs: dict = {}

    async def fake_query_choice(self, req):
        captured_client_kwargs["base_url"] = self.base_url
        captured_client_kwargs["model"] = self.model
        captured_client_kwargs["api_key"] = self.api_key
        captured_client_kwargs["timeout"] = self.timeout
        return Decision(
            status="ok",
            selected="pong",
            confidence=0.99,
            model=self.model,
            elapsed_ms=3950.0,
            http_status=200,
        )

    monkeypatch.setattr(JevClient, "query_choice", fake_query_choice)

    client = TestClient(app)
    # 不传 body，断言使用已保存的配置
    resp = client.post("/api/semantic/test", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["status"] == "ok"
    assert data["http_status"] == 200
    assert data["selected"] == "pong"
    assert data["elapsed_ms"] == 3950.0

    # 断言确实传递了已保存的 base_url, model, timeout
    assert captured_client_kwargs["base_url"] == "https://api.example.com/v1"
    assert captured_client_kwargs["model"] == "jev-custom-001"
    assert captured_client_kwargs["api_key"] == "ah-test-secret-key-123456"
    assert captured_client_kwargs["timeout"] == 12.0

    app.dependency_overrides.clear()


def test_semantic_test_failure_not_swallowed(tmp_path, monkeypatch):
    """验收测试：/semantic/test 不许把失败吞成成功，返回真实 HTTP 状态与错误摘要"""
    store = JevConfigStore(tmp_path)
    sem_store = SemanticStore(tmp_path)
    store.save_patch(
        {
            "mode": "custom",
            "base_url": "https://api.example.com/v1",
            "model": "jev",
            "api_key": "bad_key",
        }
    )

    app.dependency_overrides[get_current_user] = lambda: {"username": "admin"}
    app.dependency_overrides[get_jev_store] = lambda: store
    app.dependency_overrides[get_semantic_store] = lambda: sem_store

    async def fake_query_choice_401(self, req):
        return Decision(
            status="unavailable",
            reason_code="AUTH_FAILED",
            http_status=401,
            error_message="Invalid API key",
            elapsed_ms=210.0,
        )

    monkeypatch.setattr(JevClient, "query_choice", fake_query_choice_401)

    client = TestClient(app)
    resp = client.post("/api/semantic/test", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["status"] == "unavailable"
    assert data["http_status"] == 401
    assert data["reason_code"] == "AUTH_FAILED"
    assert "Invalid API key" in data["error_message"]

    app.dependency_overrides.clear()

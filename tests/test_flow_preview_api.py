import pytest
from fastapi.testclient import TestClient

from backend.core.auth import get_current_user
from backend.main import app


@pytest.fixture(autouse=True)
def override_auth_for_preview():
    app.dependency_overrides[get_current_user] = lambda: {
        "username": "admin",
        "role": "admin",
    }
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def client():
    return TestClient(app)


def test_preview_flow_success_valid_graph(client):
    payload = {
        "chat_id": 12345,
        "name": "Test Flow",
        "flow_graph": {
            "entry_node_id": "start",
            "nodes": {
                "start": {
                    "id": "start",
                    "type": "delay",
                    "delay_seconds": 2,
                    "next_node_id": "_TERMINAL_COMPLETE",
                }
            },
        },
    }
    response = client.post("/api/sign-tasks/preview-flow", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["node_count"] == 1
    assert data["entry_node_id"] == "start"
    assert "graph TD" in data["mermaid"]
    assert len(data["errors"]) == 0


def test_preview_flow_failure_dangling_edge(client):
    payload = {
        "chat_id": 12345,
        "name": "Invalid Flow",
        "steps": [
            {
                "step_id": "s1",
                "node_type": "delay",
                "delay_seconds": 2,
                "next_step_id": "non_exist_target",
            }
        ],
    }
    response = client.post("/api/sign-tasks/preview-flow", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["valid"] is False
    assert len(data["errors"]) > 0
    assert any("non_exist_target" in e["message"] for e in data["errors"])


def test_preview_flow_returns_unreachable_warnings(client):
    payload = {
        "chat_id": 12345,
        "name": "Flow with Orphan Steps",
        "flow_graph": {
            "entry_node_id": "start",
            "nodes": {
                "start": {
                    "id": "start",
                    "type": "delay",
                    "delay_seconds": 1,
                    "next_node_id": "_TERMINAL_COMPLETE",
                },
                "orphan": {
                    "id": "orphan",
                    "type": "delay",
                    "delay_seconds": 1,
                    "next_node_id": "_TERMINAL_COMPLETE",
                },
            },
        },
    }
    response = client.post("/api/sign-tasks/preview-flow", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["node_count"] == 2
    assert len(data["warnings"]) == 1
    assert data["warnings"][0]["level"] == "warning"
    assert "orphan" in data["warnings"][0]["message"]
    assert "orphan (不可达)" in data["mermaid"]

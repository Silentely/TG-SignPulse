import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.core.auth import get_current_user

# Mock auth dependency
app.dependency_overrides[get_current_user] = lambda: {"username": "admin", "role": "admin"}
client = TestClient(app)


def test_preview_flow_success_valid_graph():
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


def test_preview_flow_failure_dangling_edge():
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

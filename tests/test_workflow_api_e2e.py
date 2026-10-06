import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.core.auth import create_access_token
from backend.models.account import Account
from backend.models.user import User


def _get_auth_header(db_session, username: str = "admin") -> dict:
    user = db_session.query(User).filter_by(username=username).first()
    if not user:
        user = User(username=username, password_hash="dummy_hash", token_epoch=1)
        db_session.add(user)
        db_session.commit()
    token = create_access_token(data={"sub": username}, token_epoch=user.token_epoch)
    return {"Authorization": f"Bearer {token}"}


def _create_account(db, account_name: str = "test_account") -> Account:
    account = Account(
        account_name=account_name,
        api_id="12345",
        api_hash="test-api-hash",
        status="idle",
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def test_api_create_and_get_workflow_task(client: TestClient, db_session):
    headers = _get_auth_header(db_session)
    _create_account(db_session, account_name="acc_wf")

    valid_payload = {
        "name": "wf_e2e_task",
        "account_name": "acc_wf",
        "account_names": ["acc_wf"],
        "sign_at": "09:00",
        "chats": [
            {
                "chat_id": 777111,
                "name": "wf_chat",
                "initial_step_id": "step_start",
                "steps": [
                    {
                        "step_id": "step_start",
                        "action_type": 1,
                        "config": {"text": "hello"},
                        "next_step_id": "step_end",
                    },
                    {
                        "step_id": "step_end",
                        "action_type": 1,
                        "config": {"text": "done"},
                        "next_step_id": "COMPLETE",
                    },
                ],
            }
        ],
    }

    # 1. Create task
    with patch("backend.api.routes.sign_tasks_v2.asyncio.ensure_future"):
        create_resp = client.post(
            "/api/sign-tasks",
            json=valid_payload,
            headers=headers,
        )
    assert create_resp.status_code == 201, create_resp.text
    data = create_resp.json()
    assert data["name"] == "wf_e2e_task"

    # 2. Query task details
    get_resp = client.get(
        "/api/sign-tasks/wf_e2e_task?account_name=acc_wf",
        headers=headers,
    )
    assert get_resp.status_code == 200, get_resp.text
    task_out = get_resp.json()
    assert len(task_out["chats"]) == 1
    chat = task_out["chats"][0]
    assert chat["initial_step_id"] == "step_start"
    assert len(chat["steps"]) == 2
    assert chat["steps"][0]["step_id"] == "step_start"
    assert chat["steps"][1]["step_id"] == "step_end"


def test_api_create_workflow_task_rejects_cycle_topology(
    client: TestClient, db_session
):
    headers = _get_auth_header(db_session)
    _create_account(db_session, account_name="acc_wf_bad")

    cycle_payload = {
        "name": "wf_cycle_task",
        "account_name": "acc_wf_bad",
        "account_names": ["acc_wf_bad"],
        "sign_at": "09:00",
        "chats": [
            {
                "chat_id": 777222,
                "name": "wf_chat_cycle",
                "initial_step_id": "step1",
                "steps": [
                    {
                        "step_id": "step1",
                        "action_type": 1,
                        "config": {"text": "hello"},
                        "next_step_id": "step2",
                    },
                    {
                        "step_id": "step2",
                        "action_type": 1,
                        "config": {"text": "loopback"},
                        "next_step_id": "step1",
                        "allow_loop": False,
                    },
                ],
            }
        ],
    }

    create_resp = client.post(
        "/api/sign-tasks",
        json=cycle_payload,
        headers=headers,
    )
    assert create_resp.status_code == 400, create_resp.text
    assert (
        "环路" in create_resp.text
        or "loop" in create_resp.text.lower()
        or "topology" in create_resp.text.lower()
    )


def test_api_create_workflow_task_rejects_both_actions_and_steps(
    client: TestClient, db_session
):
    headers = _get_auth_header(db_session)
    _create_account(db_session, account_name="acc_wf_bad2")

    conflict_payload = {
        "name": "wf_conflict_task",
        "account_name": "acc_wf_bad2",
        "account_names": ["acc_wf_bad2"],
        "sign_at": "09:00",
        "chats": [
            {
                "chat_id": 777333,
                "name": "wf_chat_conflict",
                "actions": [{"action": 1, "text": "hi"}],
                "initial_step_id": "step1",
                "steps": [
                    {
                        "step_id": "step1",
                        "action_type": 1,
                        "config": {"text": "hello"},
                        "next_step_id": "COMPLETE",
                    }
                ],
            }
        ],
    }

    create_resp = client.post(
        "/api/sign-tasks",
        json=conflict_payload,
        headers=headers,
    )
    assert create_resp.status_code == 400, create_resp.text
    assert "互斥" in create_resp.text


def test_api_create_workflow_task_rejects_missing_initial_step(
    client: TestClient, db_session
):
    headers = _get_auth_header(db_session)
    _create_account(db_session, account_name="acc_wf_bad3")

    missing_init_payload = {
        "name": "wf_no_init_task",
        "account_name": "acc_wf_bad3",
        "account_names": ["acc_wf_bad3"],
        "sign_at": "09:00",
        "chats": [
            {
                "chat_id": 777444,
                "name": "wf_chat_no_init",
                "steps": [
                    {
                        "step_id": "step1",
                        "action_type": 1,
                        "config": {"text": "hello"},
                        "next_step_id": "COMPLETE",
                    }
                ],
            }
        ],
    }

    create_resp = client.post(
        "/api/sign-tasks",
        json=missing_init_payload,
        headers=headers,
    )
    assert create_resp.status_code == 400, create_resp.text
    assert "initial_step_id" in create_resp.text


def test_sse_endpoint_serializes_workflow_path():
    from backend.api.routes.events import _sign_log_sse_bytes

    record = {
        "time": "2026-10-06T12:00:00Z",
        "success": True,
        "status": "SUCCESS",
        "workflow_path": ["step1", "step2"],
    }
    raw_bytes = _sign_log_sse_bytes(record)
    text = raw_bytes.decode("utf-8")
    assert "data: " in text
    payload = None
    for line in text.strip().splitlines():
        if line.startswith("data: "):
            payload = json.loads(line[len("data: ") :])
            break
    assert payload is not None
    assert payload["workflow_path"] == ["step1", "step2"]


def test_api_get_task_history_includes_workflow_path(client: TestClient, db_session):
    headers = _get_auth_header(db_session)
    _create_account(db_session, account_name="acc_wf_hist")
    from backend.services.sign_tasks import get_sign_task_service

    svc = get_sign_task_service()
    svc.create_task(
        task_name="wf_hist_task",
        account_name="acc_wf_hist",
        account_names=["acc_wf_hist"],
        sign_at="08:00",
        chats=[
            {
                "chat_id": 123456,
                "name": "test_chat",
                "initial_step_id": "step_start",
                "steps": [
                    {
                        "step_id": "step_start",
                        "action_type": 1,
                        "config": {"text": "hello"},
                        "next_step_id": "COMPLETE",
                    }
                ],
            }
        ],
    )

    svc._save_run_info(
        "wf_hist_task",
        True,
        "success message",
        "acc_wf_hist",
        flow_logs=["flow 1"],
        workflow_path=["step_start", "step_end"],
    )

    resp = client.get(
        "/api/sign-tasks/wf_hist_task/history?account_name=acc_wf_hist",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) >= 1
    assert items[0]["workflow_path"] == ["step_start", "step_end"]

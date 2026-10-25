import json

import pytest
from fastapi import BackgroundTasks, HTTPException

from backend.api.routes import sign_tasks_v2
from backend.services.sign_tasks import SignTaskService
from backend.services.task_config_io import TaskConfigConflict
from tg_signer.semantic.models import config_revision


@pytest.fixture
def stored_task(tmp_path, monkeypatch):
    monkeypatch.setenv("TG_SIGNER_WORKDIR", str(tmp_path))
    monkeypatch.setattr(
        "backend.scheduler.add_or_update_sign_task_job", lambda *a, **kw: None
    )
    monkeypatch.setattr("backend.scheduler.remove_sign_task_job", lambda *a, **kw: None)
    service = SignTaskService()
    service.signs_dir = tmp_path / "signs"
    service.signs_dir.mkdir()
    service.create_task(
        task_name="daily", account_name="acc", sign_at="09:00", chats=[]
    )
    path = service.signs_dir / "acc" / "daily" / "config.json"
    config = json.loads(path.read_text())
    config.update(
        {
            "custom": {"keep": True},
            "chats": [
                {
                    "chat_id": 1,
                    "action_interval": 7,
                    "actions": [{"action": 1, "text": "one"}],
                    "unknown": 5,
                },
                {
                    "chat_id": 2,
                    "action_interval": 19,
                    "steps": [
                        {
                            "step_id": "start",
                            "action_type": 1,
                            "config": {"text": "two"},
                            "next_step_id": "COMPLETE",
                        }
                    ],
                    "initial_step_id": "start",
                    "unknown": {"x": 1},
                },
                {
                    "chat_id": 3,
                    "action_interval": 23,
                    "flow_graph": {
                        "entry_node_id": "wait",
                        "nodes": {
                            "wait": {
                                "node_type": "wait_event",
                                "event_type": "NEW_MESSAGE",
                                "filter_patterns": ["hello"],
                                "next_node_id": "_TERMINAL_COMPLETE",
                            }
                        },
                    },
                    "unknown": "graph extension",
                },
            ],
        }
    )
    path.write_text(json.dumps(config))
    service._refresh_tasks_cache_after_write()
    return service, path, config


def test_masked_metadata_roundtrip_preserves_every_unmasked_field(stored_task):
    service, path, before = stored_task
    service.update_task(
        task_name="daily",
        account_name="acc",
        tags=["new"],
        chats=[],
        field_mask=["tags"],
        revision=config_revision(before),
    )
    after = json.loads(path.read_text())
    assert after == {**before, "tags": ["new"]}
    assert service.get_task("daily", account_name="acc")["revision"] == config_revision(
        after
    )


def test_stale_revision_is_rejected_without_writing(stored_task):
    service, path, before = stored_task
    with pytest.raises(TaskConfigConflict):
        service.update_task(
            task_name="daily",
            account_name="acc",
            tags=["new"],
            field_mask=["tags"],
            revision="stale",
        )
    assert json.loads(path.read_text()) == before


def test_update_route_wires_mask_and_conflict_response(stored_task, monkeypatch):
    service, path, before = stored_task
    monkeypatch.setattr(sign_tasks_v2, "get_sign_task_service", lambda: service)
    payload = sign_tasks_v2.SignTaskUpdate(
        revision=config_revision(before),
        field_mask=["notify_on_success"],
        notify_on_success=False,
        chats=[],
    )
    updated = sign_tasks_v2.update_sign_task(
        "daily",
        payload,
        BackgroundTasks(),
        account_name="acc",
        current_user={},
    )
    assert updated["notify_on_success"] is False
    assert json.loads(path.read_text()) == {**before, "notify_on_success": False}
    with pytest.raises(HTTPException) as conflict:
        sign_tasks_v2.update_sign_task(
            "daily",
            payload,
            BackgroundTasks(),
            account_name="acc",
            current_user={},
        )
    assert conflict.value.status_code == 409
    assert conflict.value.detail == "TASK_CONFIG_CHANGED"


def test_legacy_update_without_mask_remains_supported(stored_task):
    service, path, before = stored_task
    service.update_task(task_name="daily", account_name="acc", tags=["legacy"])
    after = json.loads(path.read_text())
    assert after["tags"] == ["legacy"]
    assert after["chats"] == before["chats"]
    assert after["custom"] == before["custom"]


def test_route_flow_patch_preserves_unedited_target_exactly(stored_task, monkeypatch):
    service, path, before = stored_task
    monkeypatch.setattr(sign_tasks_v2, "get_sign_task_service", lambda: service)
    chats = json.loads(json.dumps(before["chats"]))
    chats[0]["actions"][0]["text"] = "changed"
    sign_tasks_v2.update_sign_task(
        "daily",
        sign_tasks_v2.SignTaskUpdate(
            revision=config_revision(before),
            field_mask=["chats"],
            chats=chats,
        ),
        BackgroundTasks(),
        account_name="acc",
        current_user={},
    )
    assert json.loads(path.read_text()) == {**before, "chats": chats}


def test_linking_an_account_copies_extension_fields_and_keeps_group_consistent(
    stored_task,
):
    service, path, before = stored_task
    service.update_task(
        task_name="daily",
        account_name="acc",
        account_names=["acc", "other"],
        revision=config_revision(before),
        field_mask=["account_names"],
    )
    original = json.loads(path.read_text())
    added = json.loads(
        (service.signs_dir / "other" / "daily" / "config.json").read_text()
    )
    assert added["custom"] == before["custom"]
    assert original["task_group_id"] == added["task_group_id"]
    assert original["task_group_id"]
    assert added["chats"] == before["chats"]

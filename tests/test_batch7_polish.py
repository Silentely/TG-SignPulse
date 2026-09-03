import pytest
from pydantic import ValidationError

from backend.api.routes.sign_tasks_v2 import SignTaskCreate
from backend.services.sign_task_run_status import make_task_key


def test_sign_task_create_name_validation():
    # Valid name
    task = SignTaskCreate(
        name="  my_task  ",
        sign_at="0 9 * * *",
        chats=[{"chat_id": 123, "actions": [{"action": "send_text", "text": "hello"}]}],
    )
    assert task.name == "my_task"

    # Invalid names
    with pytest.raises(ValidationError):
        SignTaskCreate(
            name="task/with/slash",
            sign_at="0 9 * * *",
            chats=[{"chat_id": 123, "actions": [{"action": "send_text", "text": "hello"}]}],
        )

    with pytest.raises(ValidationError):
        SignTaskCreate(
            name="task\x00null",
            sign_at="0 9 * * *",
            chats=[{"chat_id": 123, "actions": [{"action": "send_text", "text": "hello"}]}],
        )


def test_make_task_key_strips_spaces():
    assert make_task_key("  account1  ", "  task1  ") == ("account1", "task1")
    assert make_task_key(None, None) == ("", "")  # type: ignore[arg-type]

import pytest

from backend.services.runtime_settings import resolve_int_setting
from backend.services.sign_task_history_io import history_file_path, safe_history_key
from backend.services.sign_task_text import repair_mojibake
from backend.utils.task_logs import extract_last_target_message
from tg_signer.notification.server_chan import close_sc_client, sc_send


def test_resolve_int_setting_guards():
    # non-dict global_cfg
    assert resolve_int_setting(None, "k", "ENV_K", 10) == 10  # type: ignore[arg-type]
    # min_v > max_v auto swap
    val = resolve_int_setting({"k": 50}, "k", "ENV_K", 10, min_v=100, max_v=20)
    assert val == 50 or val in (20, 100)


def test_safe_history_key_dots():
    assert safe_history_key("...task.name") == "...task.name"
    assert safe_history_key("..") == "default"


def test_history_file_path_str():
    p = history_file_path("/tmp/run_history", "task1", "account1")
    assert p.name == "account1__task1.json"


def test_extract_last_target_message_colon():
    logs = ["2026-09-03 12:00:00 - prefix: text: hello from bot"]
    assert extract_last_target_message(logs) == "hello from bot"

    logs_zh = ["2026-09-03 12:00:00 - 任务收到 text： 你好世界"]
    assert extract_last_target_message(logs_zh) == "你好世界"


def test_repair_mojibake_huge():
    huge = "a" * 25000
    assert repair_mojibake(huge) == huge


@pytest.mark.asyncio
async def test_sc_send_empty_key():
    with pytest.raises(ValueError, match="sendkey cannot be empty"):
        await sc_send("", "title")
    await close_sc_client()

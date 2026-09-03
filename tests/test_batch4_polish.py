from pathlib import Path

from backend.services.backup_archive import create_backup_tarball, prune_backups
from backend.services.sign_task_backend import BackendUserSigner
from backend.services.sign_task_config_inspect import (
    task_has_keyword_monitor,
    task_requires_updates,
)
from backend.services.sign_task_group import select_latest_last_run
from backend.services.sign_task_notify import friendly_error_message
from backend.utils.version_info import _is_rate_limit_error


def test_is_rate_limit_error_custom_status():
    class CustomHttpError(Exception):
        def __init__(self, status):
            self.status = status

    assert _is_rate_limit_error(CustomHttpError(429)) is True
    assert _is_rate_limit_error(CustomHttpError(403)) is True
    assert _is_rate_limit_error(CustomHttpError(500)) is False
    assert _is_rate_limit_error(Exception("GitHub API rate limit exceeded")) is True


def test_prune_backups_invalid_keep(tmp_path: Path):
    # Non-existent dir
    assert prune_backups(tmp_path / "missing", None) == 0  # type: ignore[arg-type]
    # Existing empty dir with invalid keep string
    assert prune_backups(tmp_path, "invalid") == 0  # type: ignore[arg-type]


def test_create_backup_tarball_path_traversal_guards(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "valid.txt").write_text("hello")
    dest = tmp_path / "out.tar.gz"

    # Tarball creation should skip illegal paths like traversal, colon, or absolute
    create_backup_tarball(
        data_dir,
        dest,
        paths=["valid.txt", "../escape.txt", "/absolute/path", "C:\\windows"],
    )
    assert dest.exists()


def test_select_latest_last_run_type_safety():
    assert select_latest_last_run(None, None) is None
    assert select_latest_last_run("invalid", None) is None  # type: ignore[arg-type]
    assert select_latest_last_run(None, "invalid") is None  # type: ignore[arg-type]
    assert select_latest_last_run({"time": "2026-01-01"}, "invalid") == {"time": "2026-01-01"}  # type: ignore[arg-type]

    older = {"time": "2026-01-01T10:00:00Z"}
    newer = {"time": "2026-01-02T10:00:00Z"}
    assert select_latest_last_run(older, newer) == newer
    assert select_latest_last_run(newer, older) == newer


def test_friendly_error_message_extensions():
    assert friendly_error_message(None) == ""  # type: ignore[arg-type]
    assert friendly_error_message("nodename nor servname provided") == "DNS 域名解析失败"
    assert friendly_error_message("RemoteProtocolError: server disconnected") == "服务器端断开连接"
    assert friendly_error_message("random unmapped error") == "random unmapped error"


def test_task_config_inspect_objects_and_tuples():
    class MockAction:
        def __init__(self, action_id):
            self.action = action_id

    cfg = {
        "chats": (
            {
                "actions": (MockAction(8),),
            },
        )
    }
    assert task_has_keyword_monitor(cfg) is True
    assert task_requires_updates(cfg) is True


def test_backend_user_signer_task_dir(tmp_path: Path):
    signer = BackendUserSigner.__new__(BackendUserSigner)
    signer._workdir = str(tmp_path)
    signer._tasks_dir = "signs"
    signer.task_name = "test_task"
    signer._account = ""

    # When _account is empty, should point directly to tasks_dir / task_name
    assert signer.task_dir == tmp_path / "signs" / "test_task"

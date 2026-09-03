import pytest

from backend.services.avatar_cache import mark_no_avatar
from backend.services.sign_task_history_io import cleanup_old_history_files
from backend.utils.atomic_io import write_json_atomic
from backend.utils.names import validate_storage_name


def test_validate_storage_name_length_limit():
    assert validate_storage_name("a" * 128, field_name="account") == "a" * 128
    with pytest.raises(ValueError, match="length cannot exceed 128 bytes"):
        validate_storage_name("a" * 129, field_name="account")


def test_validate_storage_name_uses_utf8_byte_limit():
    assert validate_storage_name("中" * 42, field_name="task") == "中" * 42
    with pytest.raises(ValueError, match="length cannot exceed 128 bytes"):
        validate_storage_name("中" * 43, field_name="task")


def test_atomic_io_custom_prefix(tmp_path):
    target = tmp_path / "sub" / "data.json"
    write_json_atomic(target, {"hello": "world"})
    assert target.exists()


def test_mark_no_avatar_creates_parents(tmp_path):
    marker = tmp_path / "nested" / "dir" / ".no_avatar"
    mark_no_avatar(marker)
    assert marker.exists()


def test_cleanup_old_history_files_accepts_str(tmp_path):
    removed = cleanup_old_history_files(str(tmp_path), max_age_days=3)
    assert removed == 0

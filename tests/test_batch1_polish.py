from pathlib import Path

import pytest

from backend.services.backup_archive import _safe_mtime, prune_backups
from backend.services.sign_task_failure import FailureCategory, failure_category_label
from backend.utils.atomic_io import write_json_atomic
from backend.utils.cache import TTLCache
from backend.utils.names import validate_storage_name
from backend.utils.proxy import build_proxy_dict
from backend.utils.task_logs import extract_last_target_message
from tg_signer.core.client import get_proxy


def test_build_proxy_dict_invalid_ports_and_schemes():
    assert build_proxy_dict("socks5://127.0.0.1:70000") is None
    assert build_proxy_dict("socks5://127.0.0.1:0") is None
    assert build_proxy_dict("ftp://127.0.0.1:21") is None
    assert build_proxy_dict("socks5://127.0.0.1:not_a_port") is None


def test_core_get_proxy_normalization():
    # Schemeless string defaults to socks5
    res = get_proxy("127.0.0.1:1080")
    assert res is not None
    assert res["scheme"] == "socks5"
    assert res["hostname"] == "127.0.0.1"
    assert res["port"] == 1080

    # Invalid port returns None
    assert get_proxy("127.0.0.1:99999") is None
    assert get_proxy("not_valid_proxy") is None
    assert get_proxy("") is None


def test_validate_storage_name_null_byte():
    with pytest.raises(ValueError, match="path separators or null bytes"):
        validate_storage_name("my\x00account", field_name="account")


def test_extract_last_target_message_fullwidth_colon():
    logs = [
        "2026-03-29 10:00:00 - 图片：test_image.png",
    ]
    msg = extract_last_target_message(logs)
    assert msg == "[图片] test_image.png"


def test_ttl_cache_batch_and_prune():
    cache = TTLCache(maxsize=10, ttl=60.0)
    cache.set_many({"a": 1, "b": 2, "c": 3})
    assert cache.get_many(["a", "b", "nonexistent"]) == {"a": 1, "b": 2}

    deleted = cache.delete_many(["a", "c", "missing"])
    assert deleted == 2
    assert "a" not in cache
    assert "b" in cache

    # prune_expired alias
    assert cache.prune_expired() == 0


def test_write_json_atomic_cleans_tmp_on_dump_error(tmp_path: Path):
    target = tmp_path / "test.json"

    class BadObj:
        pass

    with pytest.raises(TypeError):
        write_json_atomic(target, BadObj())

    # Ensure no leftover .tmp files
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0


def test_safe_mtime_on_nonexistent_file(tmp_path: Path):
    non_existent = tmp_path / "ghost.tar.gz"
    assert _safe_mtime(non_existent) == 0.0

    f1 = tmp_path / "auto-20260101-000000.tar.gz"
    f1.write_text("test")
    assert _safe_mtime(f1) > 0.0

    # prune_backups with existing file
    removed = prune_backups(tmp_path, keep=0)
    assert removed == 1
    assert not f1.exists()


def test_failure_category_label_flexible():
    assert failure_category_label(FailureCategory.SESSION_INVALID) == "会话失效"
    assert failure_category_label("session_invalid") == "会话失效"
    assert failure_category_label("custom_failure") == "custom_failure"

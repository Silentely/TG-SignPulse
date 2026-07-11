"""names / task_logs / account_locks 边界测试"""

from __future__ import annotations

import pytest


class TestValidateStorageName:
    """validate_storage_name() 边界测试"""

    def test_valid_name(self):
        from backend.utils.names import validate_storage_name

        assert validate_storage_name("account_1", field_name="account") == "account_1"

    def test_strips_whitespace(self):
        from backend.utils.names import validate_storage_name

        assert validate_storage_name("  bot  ", field_name="name") == "bot"

    def test_empty_raises(self):
        from backend.utils.names import validate_storage_name

        with pytest.raises(ValueError, match="cannot be empty"):
            validate_storage_name("   ", field_name="name")

    def test_dot_raises(self):
        from backend.utils.names import validate_storage_name

        with pytest.raises(ValueError, match=r"cannot be '\.' or '\.\.'"):
            validate_storage_name(".", field_name="name")

    def test_path_separator_raises(self):
        from backend.utils.names import validate_storage_name

        with pytest.raises(ValueError, match="path separators"):
            validate_storage_name("a/b", field_name="name")

    def test_non_string_raises(self):
        from backend.utils.names import validate_storage_name

        with pytest.raises(ValueError, match="must be a string"):
            validate_storage_name(123, field_name="name")  # type: ignore[arg-type]


class TestNormalizeLogLine:
    """normalize_log_line() 测试"""

    def test_empty(self):
        from backend.utils.task_logs import normalize_log_line

        assert normalize_log_line("") == ""
        assert normalize_log_line(None) == ""

    def test_strips_timestamp_prefix(self):
        from backend.utils.task_logs import normalize_log_line

        raw = "2026-01-01 12:00:00,000 - 任务开始"
        assert normalize_log_line(raw) == "任务开始"


class TestExtractLastTargetMessage:
    """extract_last_target_message() 测试"""

    def test_empty_logs(self):
        from backend.utils.task_logs import extract_last_target_message

        assert extract_last_target_message(None) == ""
        assert extract_last_target_message([]) == ""

    def test_prefers_explicit_last_message(self):
        from backend.utils.task_logs import extract_last_target_message

        logs = [
            "收到回复: 旧消息",
            "任务对象最后一条消息: 最终结果",
        ]
        assert extract_last_target_message(logs) == "最终结果"

    def test_fallback_to_reply(self):
        from backend.utils.task_logs import extract_last_target_message

        logs = ["收到回复：签到成功"]
        assert extract_last_target_message(logs) == "签到成功"

    def test_fallback_to_text_marker(self):
        from backend.utils.task_logs import extract_last_target_message

        logs = ["step done text: hello world"]
        assert extract_last_target_message(logs) == "hello world"


class TestGetAccountLock:
    """get_account_lock() 测试"""

    def test_same_name_returns_same_lock(self):
        from backend.utils.account_locks import get_account_lock

        a = get_account_lock("acc-a")
        b = get_account_lock("acc-a")
        assert a is b

    def test_different_names_return_different_locks(self):
        from backend.utils.account_locks import get_account_lock

        a = get_account_lock("acc-x")
        b = get_account_lock("acc-y")
        assert a is not b

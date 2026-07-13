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


class TestSessionStringExport:
    """session_string 导出/校验（Issue #6：错误 base64 前缀导致签到失败）"""

    def _make_new_format_session_string(
        self,
        *,
        dc_id: int = 2,
        api_id: int = 12345,
        test_mode: bool = False,
        auth_key: bytes | None = None,
        user_id: int = 987654321,
        is_bot: bool = False,
    ) -> str:
        import base64
        import struct

        from backend.utils.tg_session import _SESSION_STRING_FORMAT

        key = auth_key if auth_key is not None else bytes(range(256))
        packed = struct.pack(
            _SESSION_STRING_FORMAT,
            dc_id,
            api_id,
            test_mode,
            key,
            user_id,
            is_bot,
        )
        return base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")

    def _make_legacy_broken_export(
        self,
        *,
        dc_id: int = 2,
        test_mode: bool = False,
        auth_key: bytes | None = None,
        user_id: int = 987654321,
        is_bot: bool = False,
    ) -> str:
        """复现 Issue #6 的错误导出：旧 struct + Telethon 风格 ``1`` 前缀 → 357 字符。"""
        import base64
        import struct

        key = auth_key if auth_key is not None else bytes(range(256))
        packed = struct.pack(
            ">B?256sQ?",
            dc_id,
            test_mode,
            key,
            user_id,
            is_bot,
        )
        return "1" + base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")

    def _write_fake_session_db(
        self,
        session_dir,
        account_name: str,
        *,
        dc_id: int = 2,
        api_id: int = 12345,
        user_id: int = 987654321,
        auth_key: bytes | None = None,
    ):
        import sqlite3

        key = auth_key if auth_key is not None else bytes(range(256))
        path = session_dir / f"{account_name}.session"
        conn = sqlite3.connect(str(path))
        conn.execute(
            """
            CREATE TABLE sessions (
                dc_id INTEGER,
                api_id INTEGER,
                test_mode INTEGER,
                auth_key BLOB,
                date INTEGER,
                user_id INTEGER,
                is_bot INTEGER
            )
            """
        )
        conn.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
            (dc_id, api_id, 0, key, 0, user_id, 0),
        )
        conn.commit()
        conn.close()
        return path

    def test_is_valid_accepts_new_format(self):
        from backend.utils.tg_session import is_valid_session_string

        s = self._make_new_format_session_string()
        assert is_valid_session_string(s)
        # 新格式典型长度 362
        assert len(s) == 362

    def test_is_valid_rejects_issue6_broken_string(self):
        from backend.utils.tg_session import is_valid_session_string

        broken = self._make_legacy_broken_export()
        assert len(broken) == 357
        assert not is_valid_session_string(broken)

    def test_is_valid_rejects_empty_and_garbage(self):
        from backend.utils.tg_session import is_valid_session_string

        assert not is_valid_session_string(None)
        assert not is_valid_session_string("")
        assert not is_valid_session_string("not-a-session")
        assert not is_valid_session_string("test-session-string-for-in-memory")

    def test_export_from_session_file_matches_pyrogram_format(self, tmp_path):
        import base64
        import struct

        from backend.utils.tg_session import (
            _SESSION_STRING_FORMAT,
            _export_session_string_from_file,
            is_valid_session_string,
            load_session_string_file,
        )

        account = "acc_export"
        auth_key = bytes((i * 3) % 256 for i in range(256))
        self._write_fake_session_db(
            tmp_path, account, api_id=99988, user_id=112233, auth_key=auth_key
        )

        exported = _export_session_string_from_file(tmp_path, account)
        assert exported is not None
        assert is_valid_session_string(exported)
        # 明确禁止 Issue #6：Telethon 前缀导致的 357 非法长度
        assert len(exported) != 357
        assert not (
            len(exported) == 357 and exported.startswith("1")
        )

        decoded = base64.urlsafe_b64decode(
            exported + "=" * (-len(exported) % 4)
        )
        dc_id, api_id, test_mode, key, user_id, is_bot = struct.unpack(
            _SESSION_STRING_FORMAT, decoded
        )
        assert dc_id == 2
        assert api_id == 99988
        assert key == auth_key
        assert user_id == 112233
        assert is_bot is False
        assert test_mode is False

        # 应写入缓存文件
        cached = load_session_string_file(tmp_path, account)
        assert cached == exported

    def test_load_heals_broken_cached_session_string(self, tmp_path):
        from backend.utils.tg_session import (
            is_valid_session_string,
            load_session_string_file,
            session_string_file_path,
        )

        account = "acc_heal"
        auth_key = bytes(range(256))
        self._write_fake_session_db(tmp_path, account, auth_key=auth_key)

        # 写入 Issue #6 坏缓存
        broken = self._make_legacy_broken_export(auth_key=auth_key)
        cache_path = session_string_file_path(tmp_path, account)
        cache_path.write_text(broken, encoding="utf-8")

        healed = load_session_string_file(tmp_path, account)
        assert healed is not None
        assert is_valid_session_string(healed)
        assert healed != broken
        assert cache_path.read_text(encoding="utf-8").strip() == healed

    def test_get_account_session_string_ignores_invalid(self, tmp_path, monkeypatch):
        from backend.utils import tg_session

        monkeypatch.setattr(
            tg_session, "_load_account_store", lambda: {
                "accounts": {
                    "bad_acc": {"session_string": self._make_legacy_broken_export()},
                    "good_acc": {
                        "session_string": self._make_new_format_session_string()
                    },
                }
            }
        )
        assert tg_session.get_account_session_string("bad_acc") is None
        good = tg_session.get_account_session_string("good_acc")
        assert good is not None
        assert tg_session.is_valid_session_string(good)

    def test_set_account_session_string_rejects_invalid(self, monkeypatch):
        from backend.utils import tg_session

        store = {"accounts": {}}
        monkeypatch.setattr(tg_session, "_load_account_store", lambda: store)
        monkeypatch.setattr(tg_session, "_save_account_store", lambda data: None)

        with pytest.raises(ValueError, match="invalid pyrogram session_string"):
            tg_session.set_account_session_string("x", "1" + "A" * 356)

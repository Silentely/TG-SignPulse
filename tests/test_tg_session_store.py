"""backend.utils.tg_session 账号存储 CRUD / 并发信号量 / 会话串导出兜底分支测试"""

from __future__ import annotations

import base64
import json
import struct

import pytest

from backend.utils import tg_session

# ─── 账号存储 CRUD ───


def _monkeypatch_store(tmp_path, monkeypatch):
    """将账号存储指向临时目录，并使用真实文件读写。"""
    store_path = tmp_path / "accounts.json"
    monkeypatch.setattr(tg_session, "_account_store_path", lambda: store_path)
    return store_path


class TestAccountStoreCRUD:
    def test_load_missing_file_returns_empty(self, tmp_path, monkeypatch):
        _monkeypatch_store(tmp_path, monkeypatch)
        assert tg_session._load_account_store() == {"accounts": {}}

    def test_load_corrupt_json_returns_empty(self, tmp_path, monkeypatch):
        path = _monkeypatch_store(tmp_path, monkeypatch)
        path.write_text("{not-json", encoding="utf-8")
        assert tg_session._load_account_store() == {"accounts": {}}

    def test_load_non_dict_json_returns_empty(self, tmp_path, monkeypatch):
        path = _monkeypatch_store(tmp_path, monkeypatch)
        path.write_text("[1, 2]", encoding="utf-8")
        assert tg_session._load_account_store() == {"accounts": {}}

    def test_load_dict_without_accounts_fills_empty(self, tmp_path, monkeypatch):
        path = _monkeypatch_store(tmp_path, monkeypatch)
        path.write_text(json.dumps({"foo": 1}), encoding="utf-8")
        data = tg_session._load_account_store()
        assert data["foo"] == 1
        assert data["accounts"] == {}

    def test_load_valid_roundtrip(self, tmp_path, monkeypatch):
        path = _monkeypatch_store(tmp_path, monkeypatch)
        path.write_text(json.dumps({"accounts": {"a": {"x": 1}}}), encoding="utf-8")
        assert tg_session._load_account_store() == {"accounts": {"a": {"x": 1}}}

    def test_list_account_names_sorted(self, tmp_path, monkeypatch):
        path = _monkeypatch_store(tmp_path, monkeypatch)
        path.write_text(
            json.dumps({"accounts": {"zeta": {}, "alpha": {}}}), encoding="utf-8"
        )
        assert tg_session.list_account_names() == ["alpha", "zeta"]

    def test_list_account_names_non_dict_accounts(self, tmp_path, monkeypatch):
        path = _monkeypatch_store(tmp_path, monkeypatch)
        path.write_text(json.dumps({"accounts": "oops"}), encoding="utf-8")
        assert tg_session.list_account_names() == []

    def test_set_and_get_session_string_roundtrip(self, tmp_path, monkeypatch):
        import base64
        import struct

        packed = struct.pack(
            tg_session._SESSION_STRING_FORMAT,
            2,
            12345,
            False,
            bytes(range(256)),
            987654321,
            False,
        )
        session_string = (
            base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")
        )
        _monkeypatch_store(tmp_path, monkeypatch)

        tg_session.set_account_session_string("acc1", f"  {session_string}  ")
        got = tg_session.get_account_session_string("acc1")
        assert got == session_string  # 首尾空白被裁剪

    def test_set_session_string_with_non_dict_entry(self, tmp_path, monkeypatch):
        import base64
        import struct

        packed = struct.pack(
            tg_session._SESSION_STRING_FORMAT,
            2,
            12345,
            False,
            bytes(range(256)),
            987654321,
            False,
        )
        session_string = (
            base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")
        )
        path = _monkeypatch_store(tmp_path, monkeypatch)
        path.write_text(json.dumps({"accounts": {"acc1": "not-a-dict"}}), encoding="utf-8")

        tg_session.set_account_session_string("acc1", session_string)
        assert tg_session.get_account_session_string("acc1") == session_string

    def test_set_session_string_with_non_dict_accounts(self, tmp_path, monkeypatch):
        import base64
        import struct

        packed = struct.pack(
            tg_session._SESSION_STRING_FORMAT,
            2,
            12345,
            False,
            bytes(range(256)),
            987654321,
            False,
        )
        session_string = (
            base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")
        )
        path = _monkeypatch_store(tmp_path, monkeypatch)
        path.write_text(json.dumps({"accounts": "oops"}), encoding="utf-8")

        tg_session.set_account_session_string("acc1", session_string)
        assert tg_session.get_account_session_string("acc1") == session_string

    def test_get_session_string_non_dict_entry_returns_none(self, tmp_path, monkeypatch):
        path = _monkeypatch_store(tmp_path, monkeypatch)
        path.write_text(json.dumps({"accounts": {"acc1": "not-a-dict"}}), encoding="utf-8")
        assert tg_session.get_account_session_string("acc1") is None

    def test_get_session_string_blank_entry_returns_none(self, tmp_path, monkeypatch):
        path = _monkeypatch_store(tmp_path, monkeypatch)
        path.write_text(
            json.dumps({"accounts": {"acc1": {"session_string": "   "}}}),
            encoding="utf-8",
        )
        assert tg_session.get_account_session_string("acc1") is None

    def test_delete_account_session_string(self, tmp_path, monkeypatch):
        path = _monkeypatch_store(tmp_path, monkeypatch)
        path.write_text(json.dumps({"accounts": {"a": {"x": 1}, "b": {"y": 2}}}), encoding="utf-8")
        tg_session.delete_account_session_string("a")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["accounts"] == {"b": {"y": 2}}

    def test_delete_missing_account_noop(self, tmp_path, monkeypatch):
        path = _monkeypatch_store(tmp_path, monkeypatch)
        path.write_text(json.dumps({"accounts": {"a": {}}}), encoding="utf-8")
        tg_session.delete_account_session_string("nope")
        assert json.loads(path.read_text(encoding="utf-8"))["accounts"] == {"a": {}}

    def test_rename_account_success(self, tmp_path, monkeypatch):
        path = _monkeypatch_store(tmp_path, monkeypatch)
        path.write_text(json.dumps({"accounts": {"old": {"x": 1}}}), encoding="utf-8")
        tg_session.rename_account_entry("old", "new")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "old" not in data["accounts"]
        assert data["accounts"]["new"]["x"] == 1
        assert "updated_at" in data["accounts"]["new"]

    def test_rename_same_name_is_noop(self, tmp_path, monkeypatch):
        path = _monkeypatch_store(tmp_path, monkeypatch)
        path.write_text(json.dumps({"accounts": {"a": {"x": 1}}}), encoding="utf-8")
        tg_session.rename_account_entry("a", "a")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["accounts"]["a"] == {"x": 1}

    def test_rename_missing_entry_is_noop(self, tmp_path, monkeypatch):
        path = _monkeypatch_store(tmp_path, monkeypatch)
        path.write_text(json.dumps({"accounts": {}}), encoding="utf-8")
        tg_session.rename_account_entry("missing", "new")
        assert json.loads(path.read_text(encoding="utf-8"))["accounts"] == {}

    def test_rename_collision_raises(self, tmp_path, monkeypatch):
        path = _monkeypatch_store(tmp_path, monkeypatch)
        path.write_text(
            json.dumps({"accounts": {"a": {"x": 1}, "b": {"y": 2}}}), encoding="utf-8"
        )
        with pytest.raises(ValueError, match="already exists"):
            tg_session.rename_account_entry("a", "b")

    def test_rename_non_dict_entry_is_normalized(self, tmp_path, monkeypatch):
        path = _monkeypatch_store(tmp_path, monkeypatch)
        path.write_text(json.dumps({"accounts": {"old": "not-a-dict"}}), encoding="utf-8")
        tg_session.rename_account_entry("old", "new")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "old" not in data["accounts"]
        assert "updated_at" in data["accounts"]["new"]

    def test_rename_non_dict_accounts_creates_empty(self, tmp_path, monkeypatch):
        path = _monkeypatch_store(tmp_path, monkeypatch)
        path.write_text(json.dumps({"accounts": "oops"}), encoding="utf-8")
        # 非 dict accounts 时原地重建空 dict，但旧条目不存在 → 早退不落盘
        tg_session.rename_account_entry("missing", "new")
        assert json.loads(path.read_text(encoding="utf-8"))["accounts"] == "oops"

    def test_get_account_profile_missing_returns_empty(self, tmp_path, monkeypatch):
        _monkeypatch_store(tmp_path, monkeypatch)
        assert tg_session.get_account_profile("nope") == {}

    def test_get_account_profile_fields(self, tmp_path, monkeypatch):
        path = _monkeypatch_store(tmp_path, monkeypatch)
        path.write_text(
            json.dumps(
                {
                    "accounts": {
                        "a": {
                            "remark": "备注",
                            "proxy": "socks5://1.2.3.4:1080",
                            "status": "connected",
                            "status_message": "ok",
                            "status_code": "0",
                            "status_checked_at": "2026-01-01T00:00:00Z",
                            "needs_relogin": 1,
                            "invalid_notified_at": "2026-01-02T00:00:00Z",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        profile = tg_session.get_account_profile("a")
        assert profile["remark"] == "备注"
        assert profile["needs_relogin"] is True
        assert profile["invalid_notified_at"] == "2026-01-02T00:00:00Z"

    def test_get_account_proxy_only_non_blank_str(self, tmp_path, monkeypatch):
        path = _monkeypatch_store(tmp_path, monkeypatch)
        path.write_text(
            json.dumps(
                {
                    "accounts": {
                        "a": {"proxy": "  socks5://h:1  "},
                        "b": {"proxy": 123},
                        "c": {"proxy": "   "},
                    }
                }
            ),
            encoding="utf-8",
        )
        assert tg_session.get_account_proxy("a") == "socks5://h:1"
        assert tg_session.get_account_proxy("b") is None
        assert tg_session.get_account_proxy("c") is None

    def test_set_account_profile(self, tmp_path, monkeypatch):
        _monkeypatch_store(tmp_path, monkeypatch)
        tg_session.set_account_profile("a", remark="  备注  ", proxy=" socks5://h:2 ")
        profile = tg_session.get_account_profile("a")
        assert profile["remark"] == "备注"
        assert profile["proxy"] == "socks5://h:2"

    def test_set_account_profile_partial_update(self, tmp_path, monkeypatch):
        _monkeypatch_store(tmp_path, monkeypatch)
        tg_session.set_account_profile("a", remark="备注")
        tg_session.set_account_profile("a", proxy="socks5://h:3")
        profile = tg_session.get_account_profile("a")
        assert profile["remark"] == "备注"
        assert profile["proxy"] == "socks5://h:3"

    def test_set_account_profile_non_dict_accounts(self, tmp_path, monkeypatch):
        path = _monkeypatch_store(tmp_path, monkeypatch)
        path.write_text(json.dumps({"accounts": "oops"}), encoding="utf-8")
        tg_session.set_account_profile("a", remark="备注")
        assert tg_session.get_account_profile("a")["remark"] == "备注"

    def test_get_account_status_default_connected(self, tmp_path, monkeypatch):
        _monkeypatch_store(tmp_path, monkeypatch)
        status = tg_session.get_account_status("missing")
        assert status["status"] == "connected"
        assert status["message"] == ""

    def test_get_account_status_blank_status_falls_back(self, tmp_path, monkeypatch):
        path = _monkeypatch_store(tmp_path, monkeypatch)
        path.write_text(json.dumps({"accounts": {"a": {"status": ""}}}), encoding="utf-8")
        assert tg_session.get_account_status("a")["status"] == "connected"

    def test_set_account_status_fields(self, tmp_path, monkeypatch):
        _monkeypatch_store(tmp_path, monkeypatch)
        tg_session.set_account_status(
            "a", status="invalid", message="会话失效", code="SESSION_REVOKED",
            needs_relogin=True, invalid_notified_at="2026-01-03T00:00:00Z",
        )
        status = tg_session.get_account_status("a")
        assert status["status"] == "invalid"
        assert status["message"] == "会话失效"
        assert status["code"] == "SESSION_REVOKED"
        assert status["needs_relogin"] is True
        assert status["invalid_notified_at"] == "2026-01-03T00:00:00Z"

    def test_set_account_status_non_invalid_clears_notified_at(self, tmp_path, monkeypatch):
        _monkeypatch_store(tmp_path, monkeypatch)
        tg_session.set_account_status(
            "a", status="invalid", invalid_notified_at="2026-01-03T00:00:00Z"
        )
        tg_session.set_account_status("a", status="connected")
        status = tg_session.get_account_status("a")
        assert status["status"] == "connected"
        assert status["invalid_notified_at"] is None

    def test_set_account_status_keeps_notified_at_when_invalid(self, tmp_path, monkeypatch):
        _monkeypatch_store(tmp_path, monkeypatch)
        tg_session.set_account_status(
            "a", status="invalid", invalid_notified_at="2026-01-03T00:00:00Z"
        )
        status = tg_session.get_account_status("a")
        assert status["invalid_notified_at"] == "2026-01-03T00:00:00Z"

    def test_set_account_status_non_dict_accounts(self, tmp_path, monkeypatch):
        path = _monkeypatch_store(tmp_path, monkeypatch)
        path.write_text(json.dumps({"accounts": "oops"}), encoding="utf-8")
        tg_session.set_account_status("a", status="error")
        assert tg_session.get_account_status("a")["status"] == "error"

    def test_set_account_status_non_dict_entry(self, tmp_path, monkeypatch):
        path = _monkeypatch_store(tmp_path, monkeypatch)
        path.write_text(json.dumps({"accounts": {"a": "not-a-dict"}}), encoding="utf-8")
        tg_session.set_account_status("a", status="error", message="x")
        assert tg_session.get_account_status("a")["status"] == "error"


# ─── 并发信号量 ───


class TestGlobalSemaphore:
    def test_resolve_limit_from_env(self, monkeypatch):
        monkeypatch.setenv("TG_GLOBAL_CONCURRENCY", "7")
        assert tg_session._resolve_concurrency_limit() == 7

    def test_resolve_limit_env_zero_clamped(self, monkeypatch):
        monkeypatch.setenv("TG_GLOBAL_CONCURRENCY", "0")
        assert tg_session._resolve_concurrency_limit() == 1

    def test_resolve_limit_env_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("TG_GLOBAL_CONCURRENCY", "abc")
        assert 1 <= tg_session._resolve_concurrency_limit() <= 5

    def test_resolve_limit_from_config_service(self, monkeypatch):
        monkeypatch.delenv("TG_GLOBAL_CONCURRENCY", raising=False)

        class FakeService:
            def get_global_settings(self):
                return {"tg_global_concurrency": 9}

        monkeypatch.setattr(
            "backend.services.config.get_config_service", lambda: FakeService()
        )
        assert tg_session._resolve_concurrency_limit() == 9

    def test_resolve_limit_config_service_error_falls_back(self, monkeypatch):
        monkeypatch.delenv("TG_GLOBAL_CONCURRENCY", raising=False)
        monkeypatch.setattr(
            "backend.services.config.get_config_service",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        assert 1 <= tg_session._resolve_concurrency_limit() <= 5

    def test_get_global_semaphore_uses_env_limit(self, monkeypatch):
        monkeypatch.setenv("TG_GLOBAL_CONCURRENCY", "3")
        monkeypatch.setattr(tg_session, "_GLOBAL_SEMAPHORE", None)
        sem = tg_session.get_global_semaphore()
        assert sem._value == 3

    def test_get_global_semaphore_cached(self, monkeypatch):
        monkeypatch.setattr(tg_session, "_GLOBAL_SEMAPHORE", None)
        first = tg_session.get_global_semaphore()
        second = tg_session.get_global_semaphore()
        assert first is second

    def test_update_global_semaphore_clamps_below_one(self):
        tg_session.update_global_semaphore(0)
        assert tg_session._GLOBAL_SEMAPHORE._value == 1

    def test_update_global_semaphore_normal(self):
        tg_session.update_global_semaphore(4)
        assert tg_session._GLOBAL_SEMAPHORE._value == 4


# ─── 会话模式与存储路径 ───


class TestSessionModeAndStorePath:
    def test_session_mode_default_file(self, monkeypatch):
        monkeypatch.delenv("TG_SESSION_MODE", raising=False)
        assert tg_session.get_session_mode() == "file"

    def test_session_mode_string_env(self, monkeypatch):
        monkeypatch.setenv("TG_SESSION_MODE", "  STRING  ")
        assert tg_session.get_session_mode() == "string"
        assert tg_session.is_string_session_mode() is True

    def test_session_mode_unknown_env_falls_back_file(self, monkeypatch):
        monkeypatch.setenv("TG_SESSION_MODE", "sqlite")
        assert tg_session.get_session_mode() == "file"
        assert tg_session.is_string_session_mode() is False

    def test_account_store_path_uses_settings_session_dir(self, monkeypatch, tmp_path):
        class FakeSettings:
            def resolve_session_dir(self):
                return tmp_path / "sessions"

        monkeypatch.setattr(tg_session, "get_settings", lambda: FakeSettings())
        path = tg_session._account_store_path()
        assert path == tmp_path / "sessions" / "accounts.json"
        assert path.parent.exists()  # 目录自动创建


# ─── 会话串校验旧格式分支 ───


class TestSessionStringOldFormats:
    def _make_old_format(self, fmt: str, *, user_id: int = 111, dc_id: int = 1) -> str:
        packed = struct.pack(
            fmt, dc_id, False, bytes(range(256)), user_id, False
        )
        return base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")

    def test_validates_351_old_format(self):
        s = self._make_old_format(">B?256sI?")
        assert len(s) == 351
        assert tg_session.is_valid_session_string(s)

    def test_validates_356_old_format_64(self):
        s = self._make_old_format(">B?256sQ?")
        assert len(s) == 356
        assert tg_session.is_valid_session_string(s)

    def test_rejects_corrupt_payload(self):
        # 长度合法但内容无法按 struct 解包（base64 可解码但字节数不足）
        assert not tg_session.is_valid_session_string("A" * 200)

    def test_rejects_undecodable(self):
        assert not tg_session.is_valid_session_string("!" * 10)


# ─── 会话串文件导出兜底 ───


class TestSessionStringFileFallback:
    def _write_fake_session_db(self, session_dir, account_name: str, **fields):
        """写入可被 _export_session_string_from_file 读取的 .session SQLite。"""
        import sqlite3

        defaults = {
            "dc_id": 2,
            "api_id": 12345,
            "test_mode": 0,
            "auth_key": bytes(range(256)),
            "user_id": 987654321,
            "is_bot": 0,
        }
        defaults.update(fields)
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
            "INSERT INTO sessions VALUES (?, ?, ?, ?, 0, ?, ?)",
            (
                defaults["dc_id"],
                defaults["api_id"],
                defaults["test_mode"],
                defaults["auth_key"],
                defaults["user_id"],
                defaults["is_bot"],
            ),
        )
        conn.commit()
        conn.close()
        return path

    def test_export_missing_session_file_returns_none(self, tmp_path):
        assert tg_session._export_session_string_from_file(tmp_path, "ghost") is None

    def test_load_no_cache_file_goes_straight_to_export(self, tmp_path):
        # 无 .session_string 缓存时直接走 .session 导出
        self._write_fake_session_db(tmp_path, "nocache", auth_key=bytes(range(256)))
        result = tg_session.load_session_string_file(tmp_path, "nocache")
        assert result is not None
        assert tg_session.is_valid_session_string(result)

    def test_export_corrupt_session_db_returns_none(self, tmp_path):
        (tmp_path / "bad.session").write_bytes(b"this is not a sqlite database")
        assert tg_session._export_session_string_from_file(tmp_path, "bad") is None

    def test_export_empty_row_returns_none(self, tmp_path):
        import sqlite3

        path = tmp_path / "empty.session"
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
        conn.commit()
        conn.close()
        assert tg_session._export_session_string_from_file(tmp_path, "empty") is None

    def test_export_missing_auth_key_returns_none(self, tmp_path):
        self._write_fake_session_db(tmp_path, "nokey", auth_key=None)
        assert tg_session._export_session_string_from_file(tmp_path, "nokey") is None

    def test_export_memoryview_auth_key(self, tmp_path, monkeypatch):
        # sqlite3 默认按 bytes 回读 BLOB，用假连接模拟 memoryview 分支
        (tmp_path / "memview.session").write_bytes(b"placeholder")
        row = (2, 12345, 0, memoryview(bytes(range(256))), 987654321, 0)

        class FakeCursor:
            def fetchone(self):
                return row

        class FakeConn:
            def execute(self, sql):
                return FakeCursor()

            def close(self):
                pass

        monkeypatch.setattr("sqlite3.connect", lambda *a, **k: FakeConn())
        exported = tg_session._export_session_string_from_file(tmp_path, "memview")
        assert tg_session.is_valid_session_string(exported)

    def test_export_short_auth_key_padded(self, tmp_path):
        self._write_fake_session_db(tmp_path, "short", auth_key=b"short-key")
        exported = tg_session._export_session_string_from_file(tmp_path, "short")
        assert exported is not None
        assert tg_session.is_valid_session_string(exported)

    def test_export_long_auth_key_truncated(self, tmp_path):
        self._write_fake_session_db(
            tmp_path, "long", auth_key=bytes(i % 256 for i in range(300))
        )
        exported = tg_session._export_session_string_from_file(tmp_path, "long")
        assert exported is not None
        assert tg_session.is_valid_session_string(exported)

    def test_export_invalid_result_returns_none(self, tmp_path, monkeypatch):
        self._write_fake_session_db(tmp_path, "invalid", auth_key=bytes(range(256)))
        monkeypatch.setattr(tg_session, "is_valid_session_string", lambda s: False)
        assert tg_session._export_session_string_from_file(tmp_path, "invalid") is None

    def test_export_generic_auth_key_converted(self, tmp_path, monkeypatch):
        # 非 bytes/bytearray/memoryview（如 int 列表）走 bytes() 兜底转换
        (tmp_path / "genkey.session").write_bytes(b"placeholder")
        row = (2, 12345, 0, [0x6B] * 256, 987654321, 0)

        class FakeCursor:
            def fetchone(self):
                return row

        class FakeConn:
            def execute(self, sql):
                return FakeCursor()

            def close(self):
                pass

        monkeypatch.setattr("sqlite3.connect", lambda *a, **k: FakeConn())
        exported = tg_session._export_session_string_from_file(tmp_path, "genkey")
        assert tg_session.is_valid_session_string(exported)

    def test_export_session_path_is_directory_returns_none(self, tmp_path):
        (tmp_path / "dir.session").mkdir()
        assert tg_session._export_session_string_from_file(tmp_path, "dir") is None

    def test_export_cache_write_error_still_returns_string(self, tmp_path, monkeypatch):
        import pathlib

        self._write_fake_session_db(tmp_path, "nowrite", auth_key=bytes(range(256)))

        def _boom_write(self, *args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(pathlib.Path, "write_text", _boom_write)
        exported = tg_session._export_session_string_from_file(tmp_path, "nowrite")
        assert exported is not None
        assert tg_session.is_valid_session_string(exported)

    def test_load_read_error_falls_back_to_export(self, tmp_path, monkeypatch):
        import pathlib

        self._write_fake_session_db(tmp_path, "readerr", auth_key=bytes(range(256)))
        cache_path = tg_session.session_string_file_path(tmp_path, "readerr")
        cache_path.write_text("stale", encoding="utf-8")

        def _boom_read_text(self, *args, **kwargs):
            raise OSError("io error")

        monkeypatch.setattr(pathlib.Path, "read_text", _boom_read_text)
        result = tg_session.load_session_string_file(tmp_path, "readerr")
        assert result is not None
        assert tg_session.is_valid_session_string(result)

    def test_load_unlink_error_heals(self, tmp_path, monkeypatch):
        import pathlib

        self._write_fake_session_db(tmp_path, "unlinkerr", auth_key=bytes(range(256)))
        cache_path = tg_session.session_string_file_path(tmp_path, "unlinkerr")
        cache_path.write_text("broken-cache", encoding="utf-8")

        def _boom_unlink(self, *args, **kwargs):
            raise OSError("permission denied")

        monkeypatch.setattr(pathlib.Path, "unlink", _boom_unlink)
        result = tg_session.load_session_string_file(tmp_path, "unlinkerr")
        assert result is not None
        assert tg_session.is_valid_session_string(result)

    def test_save_session_string_file(self, tmp_path):
        path = tg_session.session_string_file_path(tmp_path, "saved")
        tg_session.save_session_string_file(tmp_path, "saved", "  abc-def  ")
        assert path.read_text(encoding="utf-8") == "abc-def"

    def test_delete_session_string_file(self, tmp_path):
        path = tg_session.session_string_file_path(tmp_path, "del")
        path.write_text("x", encoding="utf-8")
        tg_session.delete_session_string_file(tmp_path, "del")
        assert not path.exists()

    def test_delete_session_string_file_missing_noop(self, tmp_path):
        tg_session.delete_session_string_file(tmp_path, "ghost")

    def test_delete_session_string_file_unlink_error_swallowed(self, tmp_path, monkeypatch):
        path = tg_session.session_string_file_path(tmp_path, "locked")
        path.write_text("x", encoding="utf-8")

        def _boom_unlink(self, *args, **kwargs):
            raise OSError("permission denied")

        monkeypatch.setattr(path.__class__, "unlink", _boom_unlink)
        tg_session.delete_session_string_file(tmp_path, "locked")  # 不抛异常

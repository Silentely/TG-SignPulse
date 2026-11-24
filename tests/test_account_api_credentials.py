"""Issue #17：账号级 Telegram API 凭据（解析 / 存储 / 事务 / 缓存）测试。

所有用例均使用临时 ``accounts.json`` 与 Mock/Fake Client，不访问真实 Telegram。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.services.telegram.credentials import (
    DEFAULT_API_HASH,
    DEFAULT_API_ID,
    ApiCredentialsInvalid,
    ApiCredentialsMismatch,
    ApiCredentialsPairRequired,
    ResolvedTelegramCredentials,
    apply_account_credential_update,
    credential_fingerprint,
    ensure_session_credentials_match,
    mask_api_hash,
    parse_credential_pair,
    resolve_account_credentials,
    resolve_global_credentials,
    resolve_telegram_credentials,
)
from backend.utils import tg_session


@pytest.fixture
def store(tmp_path, monkeypatch):
    """把 accounts.json 指向临时文件，并让凭据写入默认不标记重登录。"""
    path = tmp_path / "session" / "accounts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(tg_session, "_account_store_path", lambda: path)
    monkeypatch.setattr(
        tg_session, "account_has_session_artifact", lambda account_name: False
    )
    return path


def _no_env():
    return {"env_api_id": None, "env_api_hash": None}


# ---------------------------------------------------------------------------
# 统一凭据解析
# ---------------------------------------------------------------------------


class TestCredentialResolution:
    def test_account_pair_has_priority(self, store):
        tg_session.set_account_credentials(
            "acc", 111, "account-hash", mark_needs_relogin=False
        )
        resolved = resolve_telegram_credentials(
            {"api_id": "222", "api_hash": "panel-hash"},
            account_name="acc",
            **_no_env(),
        )
        assert resolved.as_tuple() == (111, "account-hash")
        assert resolved.source == "account"
        assert resolved.is_custom is True

    def test_blank_account_falls_back_to_global_env(self, store, monkeypatch):
        monkeypatch.setenv("TG_API_ID", "333")
        monkeypatch.setenv("TG_API_HASH", "env-hash")
        resolved = resolve_account_credentials("no-creds")
        assert resolved.as_tuple() == (333, "env-hash")
        assert resolved.source == "env"

    def test_one_sided_account_fails_closed(self, store):
        tg_session.set_account_profile("acc", remark="broken")
        data = json.loads(store.read_text(encoding="utf-8"))
        data["accounts"]["acc"]["api_id"] = 111
        store.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(ApiCredentialsPairRequired) as exc:
            resolve_telegram_credentials(account_name="acc", **_no_env())
        assert exc.value.code == "API_CREDENTIALS_PAIR_REQUIRED"

    def test_global_env_pair_priority(self):
        resolved = resolve_global_credentials(
            {"api_id": "222", "api_hash": "panel-hash"},
            env_api_id="111",
            env_api_hash="env-hash",
        )
        assert resolved.as_tuple() == (111, "env-hash")
        assert resolved.source == "env"

    def test_panel_pair_priority_over_default(self):
        resolved = resolve_global_credentials(
            {"api_id": "222", "api_hash": "panel-hash"}, **_no_env()
        )
        assert resolved.as_tuple() == (222, "panel-hash")
        assert resolved.source == "panel"

    def test_default_pair_when_everything_blank(self):
        resolved = resolve_global_credentials({}, **_no_env())
        assert resolved.as_tuple() == (int(DEFAULT_API_ID), DEFAULT_API_HASH)
        assert resolved.source == "default"

    def test_one_sided_env_is_not_mixed_with_panel(self):
        with pytest.raises(ApiCredentialsPairRequired):
            resolve_global_credentials(
                {"api_id": "222", "api_hash": "panel-hash"},
                env_api_id="111",
                env_api_hash=None,
            )
        with pytest.raises(ApiCredentialsPairRequired):
            resolve_global_credentials(
                {"api_id": "222", "api_hash": "panel-hash"},
                env_api_id=None,
                env_api_hash="env-hash",
            )

    def test_panel_configured_marker_fail_closed(self):
        # get_telegram_config() 对单边面板配置返回 configured=True + 原始单边值
        with pytest.raises(ApiCredentialsPairRequired):
            resolve_global_credentials(
                {
                    "api_id": DEFAULT_API_ID,
                    "api_hash": DEFAULT_API_HASH,
                    "is_custom": False,
                    "configured": True,
                    "configured_api_id": "222",
                    "configured_api_hash": None,
                },
                **_no_env(),
            )

    def test_parse_pair_validation(self):
        assert parse_credential_pair(None, "", source="account") is None
        with pytest.raises(ApiCredentialsPairRequired):
            parse_credential_pair("111", "", source="account")
        with pytest.raises(ApiCredentialsInvalid):
            parse_credential_pair("0", "hash", source="account")
        with pytest.raises(ApiCredentialsInvalid):
            parse_credential_pair("abc", "hash", source="account")

    def test_mask_and_fingerprint_never_leak_plaintext(self):
        api_hash = "d524b414d21f4d37f08684c1df41ac9c"
        masked = mask_api_hash(api_hash)
        assert masked == "d524****ac9c"
        assert api_hash not in masked

        fp1 = credential_fingerprint(111, api_hash)
        fp2 = credential_fingerprint(222, api_hash)
        assert fp1 != fp2
        assert api_hash not in fp1
        assert len(fp1) == 16

    def test_resolved_credentials_exposes_masked_hash(self):
        resolved = ResolvedTelegramCredentials(
            api_id=111,
            api_hash="d524b414d21f4d37f08684c1df41ac9c",
            source="account",
            account_name="acc",
        )
        assert resolved.masked_hash == "d524****ac9c"
        assert resolved.fingerprint == credential_fingerprint(
            111, "d524b414d21f4d37f08684c1df41ac9c"
        )


# ---------------------------------------------------------------------------
# 安全存储与生命周期
# ---------------------------------------------------------------------------


class TestCredentialStorage:
    def test_hash_is_encrypted_at_rest(self, store):
        tg_session.set_account_credentials(
            "acc", 12345, "super-secret-hash", mark_needs_relogin=False
        )
        raw = json.loads(store.read_text(encoding="utf-8"))["accounts"]["acc"]
        assert raw["api_hash"].startswith("fernet:")
        assert "super-secret-hash" not in raw["api_hash"]

        decrypted = tg_session.get_account_credentials("acc")
        assert decrypted["api_id"] == 12345
        assert decrypted["api_hash"] == "super-secret-hash"
        assert decrypted["has_api_hash"] is True
        assert decrypted["has_custom_api"] is True

    def test_api_view_masks_hash(self, store):
        tg_session.set_account_credentials(
            "acc", 12345, "d524b414d21f4d37f08684c1df41ac9c", mark_needs_relogin=False
        )
        view = tg_session.get_account_license_credentials_for_api("acc")
        assert view["use_custom_api"] is True
        assert view["api_credentials_source"] == "custom"
        assert view["api_hash_masked"] == "d524****ac9c"
        assert "api_hash" not in view
        assert "d524b414" not in json.dumps(view)

    def test_profile_contains_masked_only_fields(self, store):
        tg_session.set_account_credentials(
            "acc", 12345, "d524b414d21f4d37f08684c1df41ac9c", mark_needs_relogin=False
        )
        profile = tg_session.get_account_profile("acc")
        assert profile["api_id"] == 12345
        assert profile["has_api_hash"] is True
        assert "api_hash" not in profile
        assert "api_hash_masked" not in profile

    def test_clear_falls_back_to_global(self, store):
        tg_session.set_account_credentials(
            "acc", 12345, "hash", mark_needs_relogin=False
        )
        tg_session.clear_account_credentials("acc")
        creds = tg_session.get_account_credentials("acc")
        assert creds["api_id"] is None
        assert creds["api_hash"] is None
        assert creds["has_custom_api"] is False
        assert (
            tg_session.get_account_license_credentials_for_api("acc")[
                "api_credentials_source"
            ]
            == "global"
        )

    def test_rename_preserves_credentials(self, store):
        tg_session.set_account_credentials(
            "old", 12345, "hash", mark_needs_relogin=False
        )
        tg_session.rename_account_entry("old", "new")
        assert tg_session.get_account_credentials("new")["api_id"] == 12345
        assert tg_session.get_account_credentials("new")["api_hash"] == "hash"
        assert tg_session.get_account_credentials("old")["api_id"] is None

    def test_delete_then_recreate_does_not_inherit(self, store):
        tg_session.set_account_credentials(
            "acc", 12345, "hash", mark_needs_relogin=False
        )
        tg_session.delete_account_session_string("acc")
        assert tg_session.get_account_credentials("acc")["api_id"] is None

        tg_session.set_account_profile("acc", remark="recreated")
        recreated = tg_session.get_account_credentials("acc")
        assert recreated["api_id"] is None
        assert recreated["has_custom_api"] is False

    def test_set_credentials_marks_relogin_when_session_exists(
        self, store, monkeypatch
    ):
        monkeypatch.setattr(
            tg_session, "account_has_session_artifact", lambda name: True
        )
        tg_session.set_account_credentials("acc", 12345, "hash")
        assert tg_session.get_account_credentials("acc")["needs_relogin"] is True

    def test_clear_relogin_flag_after_successful_login(self, store, monkeypatch):
        monkeypatch.setattr(
            tg_session, "account_has_session_artifact", lambda name: True
        )
        tg_session.set_account_credentials("acc", 12345, "hash")
        tg_session.clear_account_credentials_relogin("acc")
        assert tg_session.get_account_credentials("acc")["needs_relogin"] is False


# ---------------------------------------------------------------------------
# PATCH 更新语义
# ---------------------------------------------------------------------------


class TestCredentialUpdateSemantics:
    def test_both_fields_absent_is_unchanged(self, store):
        assert (
            apply_account_credential_update(
                "acc", api_id=None, api_hash=None, fields_set=set()
            )
            == "unchanged"
        )

    def test_both_blank_clears(self, store):
        tg_session.set_account_credentials("acc", 111, "hash", mark_needs_relogin=False)
        assert (
            apply_account_credential_update(
                "acc",
                api_id=None,
                api_hash=None,
                fields_set={"api_id", "api_hash"},
            )
            == "cleared"
        )
        assert tg_session.get_account_credentials("acc")["api_id"] is None

    def test_new_id_with_keep_marker_keeps_hash(self, store):
        tg_session.set_account_credentials(
            "acc", 111, "kept-hash", mark_needs_relogin=False
        )
        assert (
            apply_account_credential_update(
                "acc", api_id="222", api_hash="KEEP", fields_set={"api_id", "api_hash"}
            )
            == "saved"
        )
        creds = tg_session.get_account_credentials("acc")
        assert creds["api_id"] == 222
        assert creds["api_hash"] == "kept-hash"

    def test_id_only_keeps_existing_hash(self, store):
        tg_session.set_account_credentials(
            "acc", 111, "kept-hash", mark_needs_relogin=False
        )
        apply_account_credential_update(
            "acc", api_id="222", api_hash=None, fields_set={"api_id"}
        )
        creds = tg_session.get_account_credentials("acc")
        assert (creds["api_id"], creds["api_hash"]) == (222, "kept-hash")

    def test_hash_only_keeps_existing_id(self, store):
        tg_session.set_account_credentials(
            "acc", 111, "old-hash", mark_needs_relogin=False
        )
        apply_account_credential_update(
            "acc", api_id=None, api_hash="new-hash", fields_set={"api_hash"}
        )
        creds = tg_session.get_account_credentials("acc")
        assert (creds["api_id"], creds["api_hash"]) == (111, "new-hash")

    def test_id_only_without_existing_hash_fails_closed(self, store):
        with pytest.raises(ApiCredentialsPairRequired):
            apply_account_credential_update(
                "acc", api_id="222", api_hash=None, fields_set={"api_id"}
            )

    def test_hash_only_without_existing_id_fails_closed(self, store):
        with pytest.raises(ApiCredentialsPairRequired):
            apply_account_credential_update(
                "acc", api_id=None, api_hash="hash", fields_set={"api_hash"}
            )

    def test_new_pair_is_encrypted(self, store):
        apply_account_credential_update(
            "acc", api_id="222", api_hash="new-hash", fields_set={"api_id", "api_hash"}
        )
        raw = json.loads(store.read_text(encoding="utf-8"))["accounts"]["acc"]
        assert raw["api_hash"].startswith("fernet:")
        assert tg_session.get_account_credentials("acc")["api_hash"] == "new-hash"

    def test_invalid_id_raises_invalid(self, store):
        with pytest.raises(ApiCredentialsInvalid):
            apply_account_credential_update(
                "acc", api_id="abc", api_hash="hash", fields_set={"api_id", "api_hash"}
            )


# ---------------------------------------------------------------------------
# Session 兼容：api_id 探测与不匹配
# ---------------------------------------------------------------------------


class TestSessionCredentialCompatibility:
    def test_sqlite_session_api_id_is_read_without_mutation(self, tmp_path):
        session_file = tmp_path / "acc.session"
        conn = sqlite3.connect(session_file)
        try:
            conn.execute(
                "CREATE TABLE sessions (dc_id INTEGER, api_id INTEGER, "
                "test_mode INTEGER, auth_key BLOB, user_id INTEGER, is_bot INTEGER)"
            )
            conn.execute(
                "INSERT INTO sessions VALUES (2, 987654, 0, ?, 1, 0)",
                (bytes(256),),
            )
            conn.commit()
        finally:
            conn.close()
        before = session_file.read_bytes()

        assert tg_session._read_sqlite_session_api_id(session_file) == 987654
        assert (
            tg_session.get_account_session_api_id("acc", session_dir=tmp_path) == 987654
        )
        assert session_file.read_bytes() == before

    def test_session_string_api_id(self):
        packed = struct.pack(
            tg_session._SESSION_STRING_FORMAT,
            2,
            123456,
            False,
            bytes(range(256)),
            777000,
            False,
        )
        import base64

        session_string = base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")
        assert tg_session.session_string_api_id(session_string) == 123456
        assert tg_session.session_string_api_id("not-a-session") is None

    def test_mismatch_raises_specific_error(self, store, monkeypatch):
        monkeypatch.setattr(
            tg_session, "get_account_session_api_id", lambda name, session_dir=None: 111
        )
        resolved = ResolvedTelegramCredentials(
            api_id=222, api_hash="hash", source="account", account_name="acc"
        )
        with pytest.raises(ApiCredentialsMismatch) as exc:
            ensure_session_credentials_match("acc", resolved)
        assert exc.value.code == "API_CREDENTIALS_MISMATCH"
        assert "重新登录" in str(exc.value)

    def test_match_returns_session_api_id(self, store, monkeypatch):
        monkeypatch.setattr(
            tg_session, "get_account_session_api_id", lambda name, session_dir=None: 222
        )
        resolved = ResolvedTelegramCredentials(
            api_id=222, api_hash="hash", source="account", account_name="acc"
        )
        assert ensure_session_credentials_match("acc", resolved) == 222

    def test_replace_session_file_swaps_atomically(self, tmp_path):
        target_dir = tmp_path / "session"
        target_dir.mkdir()
        target = target_dir / "acc.session"
        target.write_bytes(b"old")
        (target_dir / "acc.session-wal").write_bytes(b"stale")

        staging = tmp_path / ".login_acc_1"
        staged = staging.with_suffix(".session")
        staged.write_bytes(b"new")

        tg_session.replace_session_file(staging, "acc", target_dir)
        assert target.read_bytes() == b"new"
        assert not staged.exists()
        # 旧主库遗留的 WAL 必须删除，避免 SQLite 误判
        assert not (target_dir / "acc.session-wal").exists()

    def test_cleanup_staging_session(self, tmp_path):
        staged = (tmp_path / ".qr_acc_1").with_suffix(".session")
        staged.write_bytes(b"x")
        wal = Path(str(staged) + "-wal")
        wal.write_bytes(b"x")
        tg_session.cleanup_staging_session(staged)
        assert not staged.exists()
        assert not wal.exists()


# ---------------------------------------------------------------------------
# 登录事务一致性
# ---------------------------------------------------------------------------


class TestLoginTransactionConsistency:
    def test_qr_credentials_are_reused_from_transaction(self):
        from backend.services.telegram.login_qr import TelegramQrLoginMixin

        class Dummy(TelegramQrLoginMixin):
            pass

        data = {"api_id": 111, "api_hash": "tx-hash"}
        assert Dummy()._resolve_api_credentials(data) == (111, "tx-hash")
        # 已写入事务上下文后，后续轮询不会重新解析覆盖
        assert data["api_id"] == 111
        assert data["api_hash"] == "tx-hash"

    def test_qr_credentials_resolved_once_and_stored(self, store, monkeypatch):
        from backend.services.telegram import login_qr

        class Dummy(login_qr.TelegramQrLoginMixin):
            pass

        class FakeConfigService:
            def get_telegram_config(self):
                return {"api_id": "222", "api_hash": "panel-hash"}

        monkeypatch.setattr(
            "backend.services.config.get_config_service",
            lambda: FakeConfigService(),
        )
        data = {"account_name": None}
        assert Dummy()._resolve_api_credentials(data) == (222, "panel-hash")
        assert data["api_id"] == 222
        assert data["api_hash"] == "panel-hash"
        assert data["api_credentials_source"] == "panel"

    @pytest.mark.asyncio
    async def test_phone_verify_rejects_changed_credentials(self, monkeypatch):
        from backend.services.telegram import login_phone

        class Dummy(login_phone.TelegramPhoneLoginMixin):
            def _normalize_account_name(self, name):
                return str(name).strip()

        login_phone._login_sessions.clear()
        login_phone._login_sessions["acc_+100"] = {
            "client": object(),
            "api_id": 111,
            "api_hash": "tx-hash",
            "phone_code_hash": "code-hash",
            "account_name": "acc",
            "phone_number": "+100",
        }
        try:
            with pytest.raises(ValueError, match="API_CREDENTIALS_CHANGED"):
                await Dummy().verify_login(
                    account_name="acc",
                    phone_number="+100",
                    phone_code="12345",
                    phone_code_hash="code-hash",
                    api_id=222,
                    api_hash="other-hash",
                )
        finally:
            login_phone._login_sessions.clear()

    @pytest.mark.asyncio
    async def test_phone_verify_accepts_same_credentials(self, monkeypatch):
        from backend.services.telegram import login_phone

        class Dummy(login_phone.TelegramPhoneLoginMixin):
            def _normalize_account_name(self, name):
                return str(name).strip()

        login_phone._login_sessions.clear()
        login_phone._login_sessions["acc_+100"] = {
            "client": object(),
            "api_id": 111,
            "api_hash": "tx-hash",
            "phone_code_hash": "code-hash",
            "account_name": "acc",
            "phone_number": "+100",
        }
        # 相同凭据不应触发 API_CREDENTIALS_CHANGED；后续失败来自 fake client，
        # 不是凭据事务一致性错误。
        try:
            with pytest.raises(Exception) as exc:
                await Dummy().verify_login(
                    account_name="acc",
                    phone_number="+100",
                    phone_code="12345",
                    phone_code_hash="code-hash",
                    api_id=111,
                    api_hash="tx-hash",
                )
            assert "API_CREDENTIALS_CHANGED" not in str(exc.value)
        finally:
            login_phone._login_sessions.clear()


# ---------------------------------------------------------------------------
# 后台执行链路
# ---------------------------------------------------------------------------


class TestBackgroundCredentialUsage:
    @pytest.mark.asyncio
    async def test_runner_resolves_target_account_credentials(
        self, store, monkeypatch, tmp_path
    ):
        from backend.services import sign_task_runner

        captured: list[str] = []

        def fake_resolve(tg_config, *, account_name=None, **kwargs):
            captured.append(account_name)
            return ResolvedTelegramCredentials(
                api_id=777,
                api_hash="acc-hash",
                source="account",
                account_name=account_name,
            )

        monkeypatch.setattr(
            "backend.services.telegram.credentials.resolve_telegram_credentials",
            fake_resolve,
        )
        monkeypatch.setattr(
            "backend.services.telegram.credentials.ensure_session_credentials_match",
            lambda *args, **kwargs: None,
        )

        class FakeConfigService:
            def get_telegram_config(self):
                return {}

            def require_proxy_for_telegram(self):
                return False

        monkeypatch.setattr(
            "backend.services.config.get_config_service",
            lambda: FakeConfigService(),
        )
        monkeypatch.setattr(
            "backend.utils.tg_session.load_account_session_string",
            lambda *args, **kwargs: None,
        )
        monkeypatch.setattr("backend.utils.tg_session.get_session_mode", lambda: "file")

        state = {
            "svc": SimpleNamespace(_get_effective_proxy=lambda name: None),
            "account_name": "target-acc",
            "settings": SimpleNamespace(resolve_session_dir=lambda: tmp_path),
        }
        await sign_task_runner._runner_resolve_credentials(state)

        assert captured == ["target-acc"]
        assert state["api_id"] == 777
        assert state["api_hash"] == "acc-hash"

    @pytest.mark.asyncio
    async def test_keyword_monitor_resolves_each_account_independently(
        self, store, monkeypatch, tmp_path
    ):
        from backend.services.keyword_monitor import runtime
        from backend.services.keyword_monitor.rules import KeywordMonitorRule

        rules = [
            KeywordMonitorRule(
                account_name="acc1",
                task_name="t1",
                chat_id=1,
                chat_name="chat1",
                message_thread_id=None,
                sender_filter=None,
                action={"keywords": ["k"]},
            ),
            KeywordMonitorRule(
                account_name="acc2",
                task_name="t2",
                chat_id=2,
                chat_name="chat2",
                message_thread_id=None,
                sender_filter=None,
                action={"keywords": ["k"]},
            ),
        ]

        calls: list[str] = []

        def fake_resolve(tg_config, *, account_name=None, **kwargs):
            calls.append(account_name)
            if account_name == "acc2":
                raise ApiCredentialsPairRequired("单边配置")
            return ResolvedTelegramCredentials(
                api_id=100 if account_name == "acc1" else 200,
                api_hash="hash",
                source="account",
                account_name=account_name,
            )

        monkeypatch.setattr(
            "backend.services.telegram.credentials.resolve_telegram_credentials",
            fake_resolve,
        )
        monkeypatch.setattr(
            "backend.services.telegram.credentials.ensure_session_credentials_match",
            lambda *args, **kwargs: None,
        )

        class FakeConfigService:
            def get_global_settings(self):
                return {}

            def get_telegram_config(self):
                return {}

        monkeypatch.setattr(
            "backend.services.config.get_config_service",
            lambda: FakeConfigService(),
        )
        monkeypatch.setattr(
            runtime,
            "settings",
            SimpleNamespace(
                resolve_session_dir=lambda: tmp_path,
                resolve_workdir=lambda: tmp_path,
            ),
        )
        monkeypatch.setattr(runtime, "get_session_mode", lambda: "file")
        monkeypatch.setattr(
            runtime, "load_account_session_string", lambda *args, **kwargs: None
        )
        monkeypatch.setattr(
            runtime, "resolve_effective_proxy", lambda *args, **kwargs: None
        )

        client_calls: list[tuple[str, int]] = []

        class FakeClient:
            def __init__(self, name, api_id, api_hash):
                self.name = name

            def add_handler(self, *args, **kwargs):
                return ("handler", self.name)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            def remove_handler(self, *args, **kwargs):
                return None

        def fake_get_client(name, **kwargs):
            client_calls.append((name, kwargs.get("api_id")))
            return FakeClient(name, kwargs.get("api_id"), kwargs.get("api_hash"))

        monkeypatch.setattr("tg_signer.core.get_client", fake_get_client)
        monkeypatch.setattr("tg_signer.core.close_client_by_name", _async_noop)
        monkeypatch.setattr("tg_signer.core._CLIENT_INSTANCES", {}, raising=False)

        service = runtime.KeywordMonitorService()
        monkeypatch.setattr(service, "_load_rules", lambda: rules)
        await service.restart_from_tasks()

        assert calls == ["acc1", "acc2"]
        assert client_calls == [("acc1", 100)]
        logs = service.get_task_logs("t2", account_name="acc2")
        assert any("API 凭据无效" in line for line in logs)
        service._handler_refs = []


async def _async_noop(*args, **kwargs):
    return None


# ---------------------------------------------------------------------------
# 客户端缓存隔离
# ---------------------------------------------------------------------------


class TestClientCacheIsolation:
    def test_credential_fingerprint_separates_instances(self, tmp_path):
        from tg_signer.core import _CLIENT_INSTANCES, close_client_by_name, get_client

        keys_before = set(_CLIENT_INSTANCES)
        try:
            client_a = get_client(
                "acc", workdir=tmp_path, api_id=111, api_hash="hash-a"
            )
            client_b = get_client(
                "acc", workdir=tmp_path, api_id=222, api_hash="hash-b"
            )
            client_mem = get_client(
                "acc",
                workdir=tmp_path,
                api_id=111,
                api_hash="hash-a",
                in_memory=True,
            )
            assert client_a is not client_b
            assert client_a is not client_mem
            assert "::cred=" in client_a.key
            assert client_mem.key.endswith("::memory")

            asyncio.run(close_client_by_name("acc", workdir=tmp_path))
            base = str((tmp_path / "acc").resolve())
            assert not any(
                key == base or key.startswith(f"{base}::") for key in _CLIENT_INSTANCES
            )
        finally:
            for key in list(_CLIENT_INSTANCES):
                if key not in keys_before:
                    _CLIENT_INSTANCES.pop(key, None)

    def test_same_credentials_reuse_instance(self, tmp_path):
        from tg_signer.core import _CLIENT_INSTANCES, get_client

        keys_before = set(_CLIENT_INSTANCES)
        try:
            client_a = get_client(
                "acc", workdir=tmp_path, api_id=111, api_hash="hash-a"
            )
            client_b = get_client(
                "acc", workdir=tmp_path, api_id=111, api_hash="hash-a"
            )
            assert client_a is client_b
        finally:
            for key in list(_CLIENT_INSTANCES):
                if key not in keys_before:
                    _CLIENT_INSTANCES.pop(key, None)

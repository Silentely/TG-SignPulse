from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import pyotp


class _FakeKeywordMonitorService:
    async def restart_from_tasks(self):
        return None

    def get_task_history_entry(self, *args, **kwargs):
        return None

    def get_task_logs(self, *args, **kwargs):
        return []

    async def stop(self):
        return None


class _FakeTelegramService:
    def __init__(self):
        self.profiles: dict[str, dict[str, str | None]] = {
            "acc-login": {"remark": "alpha", "proxy": None},
            "acc-qr": {"remark": None, "proxy": "socks5://127.0.0.1:1080"},
        }

    async def start_login(self, account_name: str, phone_number: str, proxy=None):
        return {
            "phone_code_hash": "hash-123",
            "phone_number": phone_number,
            "account_name": account_name,
            "message": "sent",
        }

    async def verify_login(
        self,
        account_name: str,
        phone_number: str,
        phone_code: str,
        phone_code_hash: str,
        password=None,
        proxy=None,
    ):
        return {
            "user_id": 101,
            "first_name": "Tester",
            "username": account_name,
        }

    async def start_qr_login(self, account_name: str, proxy=None):
        return {
            "login_id": "qr-1",
            "qr_uri": "tg://login?token=abc",
            "expires_at": "2026-05-08T10:00:00Z",
        }

    async def get_qr_login_status(self, login_id: str):
        return {
            "status": "success",
            "expires_at": "2026-05-08T10:00:00Z",
            "message": "ok",
            "account": {
                "name": "acc-qr",
                "session_file": "acc-qr.session",
                "exists": True,
                "size": 12,
                "remark": self.profiles["acc-qr"]["remark"],
                "proxy": self.profiles["acc-qr"]["proxy"],
                "status": "connected",
                "needs_relogin": False,
            },
            "user_id": 202,
            "first_name": "QR",
            "username": "acc-qr",
        }

    async def submit_qr_password(self, login_id: str, password: str):
        return {
            "message": "ok",
            "account": {
                "name": "acc-qr",
                "session_file": "acc-qr.session",
                "exists": True,
                "size": 12,
                "remark": self.profiles["acc-qr"]["remark"],
                "proxy": self.profiles["acc-qr"]["proxy"],
                "status": "connected",
                "needs_relogin": False,
            },
            "user_id": 202,
            "first_name": "QR",
            "username": "acc-qr",
        }

    async def cancel_qr_login(self, login_id: str):
        return True

    def list_accounts(self, force_refresh: bool = False):
        return [
            {
                "name": name,
                "session_file": f"{name}.session",
                "exists": True,
                "size": 12,
                "remark": profile["remark"],
                "proxy": profile["proxy"],
                "status": "connected",
                "status_message": "",
                "status_code": "OK",
                "status_checked_at": "2026-05-08T10:00:00Z",
                "needs_relogin": False,
            }
            for name, profile in sorted(self.profiles.items())
        ]

    async def check_account_status(
        self,
        account_name: str,
        timeout_seconds: float = 8.0,
        no_updates: bool = True,
    ):
        return {
            "account_name": account_name,
            "ok": True,
            "status": "connected",
            "message": "",
            "code": "OK",
            "checked_at": "2026-05-08T10:00:00Z",
            "needs_relogin": False,
            "user_id": 1001,
        }

    async def delete_account(self, account_name: str):
        return self.profiles.pop(account_name, None) is not None

    def account_exists(self, account_name: str):
        return account_name in self.profiles


@pytest.fixture
def app_ctx(monkeypatch, tmp_path):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(
        "APP_DATA_DIR_OVERRIDE_FILE",
        str(tmp_path / ".tg_signpulse_data_dir"),
    )
    monkeypatch.setenv("ADMIN_PASSWORD", "AdminPass123!")
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key")

    import backend.api as api_module
    import backend.api.routes as routes_module
    import backend.api.routes.accounts as accounts_route
    import backend.api.routes.auth as auth_route
    import backend.api.routes.config as config_route
    import backend.api.routes.events as events_route
    import backend.api.routes.sign_tasks_v2 as sign_tasks_route
    import backend.api.routes.tasks as tasks_route
    import backend.api.routes.user as user_route
    import backend.core.auth as auth_module
    import backend.core.config as core_config
    import backend.core.database as db_module
    import backend.core.rate_limit as rate_limit_module
    import backend.models.account as account_model_module
    import backend.models.task as task_model_module
    import backend.models.task_log as task_log_model_module
    import backend.models.user as user_model_module
    import backend.scheduler as scheduler_module
    import backend.services.config as config_service_module
    import backend.services.keyword_monitor as keyword_monitor_module
    import backend.services.sign_tasks as sign_tasks_module
    import backend.services.telegram as telegram_service_module
    import backend.services.users as users_module

    core_config.get_settings.cache_clear()

    for module in [
        core_config,
        db_module,
            auth_module,
            user_model_module,
            account_model_module,
            task_model_module,
            task_log_model_module,
            users_module,
        config_service_module,
        sign_tasks_module,
        telegram_service_module,
        keyword_monitor_module,
        auth_route,
        user_route,
        accounts_route,
        tasks_route,
        sign_tasks_route,
        config_route,
        events_route,
        routes_module,
        api_module,
    ]:
        importlib.reload(module)

    async def _noop_async(*args, **kwargs):
        return None

    monkeypatch.setattr(scheduler_module, "sync_jobs", _noop_async)
    monkeypatch.setattr(tasks_route, "sync_jobs", _noop_async)
    monkeypatch.setattr(scheduler_module, "add_or_update_sign_task_job", lambda *args, **kwargs: None)
    monkeypatch.setattr(scheduler_module, "remove_sign_task_job", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        keyword_monitor_module,
        "get_keyword_monitor_service",
        lambda: _FakeKeywordMonitorService(),
    )

    db_module._engine = None
    db_module._SessionLocal = None
    config_service_module._config_service = None
    sign_tasks_module._sign_task_service = None
    telegram_service_module._telegram_service = None
    user_route._pending_totp_secrets.clear()
    rate_limit_module.get_rate_limiter().reset_all()
    auth_route.rate_limiter.reset_all()
    accounts_route.rate_limiter.reset_all()

    db_module.init_engine()
    db_module.Base.metadata.create_all(bind=db_module.get_engine())
    with db_module.get_session_local()() as db:
        users_module.ensure_admin(db)

    app = FastAPI()
    app.include_router(api_module.router, prefix="/api")
    client = TestClient(app)

    try:
        yield {
            "client": client,
            "tmp_path": tmp_path,
            "db_module": db_module,
            "accounts_route": accounts_route,
            "config_service_module": config_service_module,
            "sign_tasks_module": sign_tasks_module,
            "tasks_route": tasks_route,
            "events_route": events_route,
        }
    finally:
        client.close()
        asyncio.set_event_loop(None)
        loop.close()


def _login(client: TestClient, username: str, password: str, totp_code: str | None = None):
    payload = {"username": username, "password": password}
    if totp_code is not None:
        payload["totp_code"] = totp_code
    response = client.post("/api/auth/login", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_full_user_settings_and_config_flow(app_ctx, monkeypatch):
    client: TestClient = app_ctx["client"]
    tmp_path: Path = app_ctx["tmp_path"]
    config_service_module = app_ctx["config_service_module"]

    token = _login(client, "admin", "AdminPass123!")
    headers = _headers(token)

    me_response = client.get("/api/auth/me", headers=headers)
    assert me_response.status_code == 200
    assert me_response.json()["username"] == "admin"

    change_username_response = client.put(
        "/api/user/username",
        headers=headers,
        json={"new_username": "owner", "password": "AdminPass123!"},
    )
    assert change_username_response.status_code == 200, change_username_response.text
    token = change_username_response.json()["access_token"]
    headers = _headers(token)

    change_password_response = client.put(
        "/api/user/password",
        headers=headers,
        json={"old_password": "AdminPass123!", "new_password": "NewPass123!"},
    )
    assert change_password_response.status_code == 200, change_password_response.text

    setup_totp_response = client.post("/api/user/totp/setup", headers=headers)
    assert setup_totp_response.status_code == 200, setup_totp_response.text
    secret = setup_totp_response.json()["secret"]
    totp_code = pyotp.TOTP(secret).now()

    qr_response = client.get("/api/user/totp/qrcode", headers=headers)
    assert qr_response.status_code == 200, qr_response.text
    assert qr_response.headers["content-type"].startswith("image/png")

    enable_totp_response = client.post(
        "/api/user/totp/enable",
        headers=headers,
        json={"totp_code": totp_code},
    )
    assert enable_totp_response.status_code == 200, enable_totp_response.text

    missing_totp_login = client.post(
        "/api/auth/login",
        json={"username": "owner", "password": "NewPass123!"},
    )
    assert missing_totp_login.status_code == 401
    assert missing_totp_login.json()["detail"] == "TOTP_REQUIRED_OR_INVALID"

    totp_login = client.post(
        "/api/auth/login",
        json={
            "username": "owner",
            "password": "NewPass123!",
            "totp_code": pyotp.TOTP(secret).now(),
        },
    )
    assert totp_login.status_code == 200, totp_login.text

    reset_totp_response = client.post(
        "/api/auth/reset-totp",
        json={"username": "owner", "password": "NewPass123!"},
    )
    assert reset_totp_response.status_code == 200, reset_totp_response.text

    token = _login(client, "owner", "NewPass123!")
    headers = _headers(token)

    settings_response = client.get("/api/config/settings", headers=headers)
    assert settings_response.status_code == 200, settings_response.text
    assert settings_response.json()["log_retention_days"] == 7

    custom_data_dir = tmp_path / "custom-data"
    save_settings_response = client.post(
        "/api/config/settings",
        headers=headers,
        json={
            "sign_interval": 9,
            "log_retention_days": 14,
            "data_dir": str(custom_data_dir),
            "global_proxy": "socks5://127.0.0.1:1080",
            "telegram_bot_notify_enabled": True,
            "telegram_bot_login_notify_enabled": True,
            "telegram_bot_task_failure_enabled": True,
            "telegram_bot_token": "bot-token",
            "telegram_bot_chat_id": "10001",
            "telegram_bot_message_thread_id": 7,
        },
    )
    assert save_settings_response.status_code == 200, save_settings_response.text

    updated_settings = client.get("/api/config/settings", headers=headers)
    assert updated_settings.status_code == 200, updated_settings.text
    updated_settings_data = updated_settings.json()
    assert updated_settings_data["sign_interval"] == 9
    assert updated_settings_data["log_retention_days"] == 14
    assert updated_settings_data["global_proxy"] == "socks5://127.0.0.1:1080"
    assert updated_settings_data["data_dir"] == str(custom_data_dir)
    assert (tmp_path / ".tg_signpulse_data_dir").read_text(encoding="utf-8").strip() == str(
        custom_data_dir
    )

    async def _fake_ai_test(self):
        return {"success": True, "message": "ok", "model_used": "gpt-4o-mini"}

    monkeypatch.setattr(config_service_module.ConfigService, "test_ai_connection", _fake_ai_test)

    save_ai_response = client.post(
        "/api/config/ai",
        headers=headers,
        json={
            "api_key": "sk-testkey12345678",
            "base_url": "https://api.example.com/v1",
            "model": "gpt-4o-mini",
        },
    )
    assert save_ai_response.status_code == 200, save_ai_response.text

    ai_response = client.get("/api/config/ai", headers=headers)
    assert ai_response.status_code == 200, ai_response.text
    ai_data = ai_response.json()
    assert ai_data["has_config"] is True
    assert ai_data["base_url"] == "https://api.example.com/v1"
    assert ai_data["model"] == "gpt-4o-mini"
    assert ai_data["api_key_masked"] != "sk-testkey12345678"

    ai_test_response = client.post("/api/config/ai/test", headers=headers)
    assert ai_test_response.status_code == 200, ai_test_response.text
    assert ai_test_response.json()["success"] is True

    save_telegram_response = client.post(
        "/api/config/telegram",
        headers=headers,
        json={"api_id": "123456", "api_hash": "custom-hash"},
    )
    assert save_telegram_response.status_code == 200, save_telegram_response.text

    telegram_response = client.get("/api/config/telegram", headers=headers)
    assert telegram_response.status_code == 200, telegram_response.text
    telegram_data = telegram_response.json()
    assert telegram_data["api_id"] == "123456"
    assert telegram_data["api_hash"] == "custom-hash"
    assert telegram_data["is_custom"] is True

    task_payload = {
        "name": "config-demo",
        "account_name": "cfgacc",
        "sign_at": "08:00",
        "chats": [
            {
                "chat_id": -100123,
                "name": "Demo",
                "actions": [{"action": 1, "text": "/checkin"}],
                "action_interval": 1,
            }
        ],
        "random_seconds": 0,
        "sign_interval": 1,
        "execution_mode": "fixed",
        "notify_on_failure": True,
    }
    create_sign_task_response = client.post(
        "/api/sign-tasks",
        headers=headers,
        json=task_payload,
    )
    assert create_sign_task_response.status_code == 201, create_sign_task_response.text

    config_tasks_response = client.get("/api/config/tasks", headers=headers)
    assert config_tasks_response.status_code == 200, config_tasks_response.text
    assert "config-demo" in config_tasks_response.json()["sign_tasks"]

    export_sign_response = client.get(
        "/api/config/export/sign/config-demo?account_name=cfgacc",
        headers=headers,
    )
    assert export_sign_response.status_code == 200, export_sign_response.text
    exported_sign_payload = export_sign_response.text
    assert json.loads(exported_sign_payload)["task_name"] == "config-demo"

    delete_sign_response = client.delete(
        "/api/config/sign/config-demo?account_name=cfgacc",
        headers=headers,
    )
    assert delete_sign_response.status_code == 200, delete_sign_response.text

    import_sign_response = client.post(
        "/api/config/import/sign",
        headers=headers,
        json={
            "config_json": exported_sign_payload,
            "task_name": "config-demo",
            "account_name": "cfgacc",
        },
    )
    assert import_sign_response.status_code == 200, import_sign_response.text

    export_all_response = client.get("/api/config/export/all", headers=headers)
    assert export_all_response.status_code == 200, export_all_response.text
    exported_all_payload = export_all_response.text

    delete_ai_response = client.delete("/api/config/ai", headers=headers)
    assert delete_ai_response.status_code == 200, delete_ai_response.text

    reset_telegram_response = client.delete("/api/config/telegram", headers=headers)
    assert reset_telegram_response.status_code == 200, reset_telegram_response.text

    delete_sign_again = client.delete(
        "/api/config/sign/config-demo?account_name=cfgacc",
        headers=headers,
    )
    assert delete_sign_again.status_code == 200, delete_sign_again.text

    import_all_response = client.post(
        "/api/config/import/all",
        headers=headers,
        json={"config_json": exported_all_payload, "overwrite": True},
    )
    assert import_all_response.status_code == 200, import_all_response.text
    assert import_all_response.json()["signs_imported"] >= 1

    restored_ai = client.get("/api/config/ai", headers=headers)
    assert restored_ai.status_code == 200, restored_ai.text
    assert restored_ai.json()["has_config"] is True

    restored_telegram = client.get("/api/config/telegram", headers=headers)
    assert restored_telegram.status_code == 200, restored_telegram.text
    assert restored_telegram.json()["is_custom"] is True

    restored_settings = client.get("/api/config/settings", headers=headers)
    assert restored_settings.status_code == 200, restored_settings.text
    assert restored_settings.json()["sign_interval"] == 9

    restored_task = client.get(
        "/api/sign-tasks/config-demo?account_name=cfgacc",
        headers=headers,
    )
    assert restored_task.status_code == 200, restored_task.text
    assert restored_task.json()["name"] == "config-demo"


def test_full_tasks_sign_tasks_accounts_and_events_flow(app_ctx, monkeypatch):
    client: TestClient = app_ctx["client"]
    db_module = app_ctx["db_module"]
    accounts_route = app_ctx["accounts_route"]
    events_route = app_ctx["events_route"]
    sign_tasks_module = app_ctx["sign_tasks_module"]

    token = _login(client, "admin", "AdminPass123!")
    headers = _headers(token)

    fake_telegram = _FakeTelegramService()
    monkeypatch.setattr(accounts_route, "get_telegram_service", lambda: fake_telegram)

    import backend.utils.tg_session as tg_session_module

    def _fake_set_account_profile(account_name: str, remark=None, proxy=None):
        if account_name not in fake_telegram.profiles:
            fake_telegram.profiles[account_name] = {"remark": None, "proxy": None}
        fake_telegram.profiles[account_name]["remark"] = remark
        fake_telegram.profiles[account_name]["proxy"] = proxy

    monkeypatch.setattr(tg_session_module, "set_account_profile", _fake_set_account_profile)

    account_login_start = client.post(
        "/api/accounts/login/start",
        headers=headers,
        json={
            "account_name": "acc-login",
            "phone_number": "+8613800000000",
            "proxy": None,
        },
    )
    assert account_login_start.status_code == 200, account_login_start.text

    account_login_verify = client.post(
        "/api/accounts/login/verify",
        headers=headers,
        json={
            "account_name": "acc-login",
            "phone_number": "+8613800000000",
            "phone_code": "12345",
            "phone_code_hash": "hash-123",
            "password": None,
            "proxy": None,
        },
    )
    assert account_login_verify.status_code == 200, account_login_verify.text
    assert account_login_verify.json()["success"] is True

    qr_start = client.post(
        "/api/accounts/qr/start",
        headers=headers,
        json={"account_name": "acc-qr", "proxy": None},
    )
    assert qr_start.status_code == 200, qr_start.text
    assert qr_start.json()["login_id"] == "qr-1"

    qr_status = client.get("/api/accounts/qr/status?login_id=qr-1", headers=headers)
    assert qr_status.status_code == 200, qr_status.text
    assert qr_status.json()["status"] == "success"

    qr_password = client.post(
        "/api/accounts/qr/password",
        headers=headers,
        json={"login_id": "qr-1", "password": "secret"},
    )
    assert qr_password.status_code == 200, qr_password.text
    assert qr_password.json()["success"] is True

    qr_cancel = client.post(
        "/api/accounts/qr/cancel",
        headers=headers,
        json={"login_id": "qr-1"},
    )
    assert qr_cancel.status_code == 200, qr_cancel.text
    assert qr_cancel.json()["success"] is True

    accounts_response = client.get("/api/accounts", headers=headers)
    assert accounts_response.status_code == 200, accounts_response.text
    assert accounts_response.json()["total"] == 2

    status_check_response = client.post(
        "/api/accounts/status/check",
        headers=headers,
        json={"account_names": ["acc-login", "acc-qr"], "timeout_seconds": 3},
    )
    assert status_check_response.status_code == 200, status_check_response.text
    assert len(status_check_response.json()["results"]) == 2

    exists_response = client.get("/api/accounts/acc-login/exists", headers=headers)
    assert exists_response.status_code == 200, exists_response.text
    assert exists_response.json()["exists"] is True

    update_account_response = client.patch(
        "/api/accounts/acc-login",
        headers=headers,
        json={"remark": "updated", "proxy": "http://127.0.0.1:9000"},
    )
    assert update_account_response.status_code == 200, update_account_response.text
    assert update_account_response.json()["account"]["remark"] == "updated"
    assert update_account_response.json()["account"]["proxy"] == "http://127.0.0.1:9000"

    delete_account_response = client.delete("/api/accounts/acc-qr", headers=headers)
    assert delete_account_response.status_code == 200, delete_account_response.text
    assert delete_account_response.json()["success"] is True

    with db_module.get_session_local()() as db:
        import backend.models.account as account_model

        account = account_model.Account(
            account_name="legacy-account",
            api_id="123",
            api_hash="hash",
            proxy=None,
            status="idle",
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        account_id = account.id

    import backend.services.tasks as tasks_service_module

    async def _fake_async_run_task_cli(account_name: str, task_name: str, callback):
        callback("first line")
        callback("second line")
        return 0, "task stdout", ""

    monkeypatch.setattr(tasks_service_module, "async_run_task_cli", _fake_async_run_task_cli)

    create_task_response = client.post(
        "/api/tasks",
        headers=headers,
        json={
            "name": "legacy-demo",
            "cron": "0 6 * * *",
            "account_id": account_id,
            "enabled": True,
        },
    )
    assert create_task_response.status_code == 201, create_task_response.text
    legacy_task_id = create_task_response.json()["id"]

    list_tasks_response = client.get("/api/tasks", headers=headers)
    assert list_tasks_response.status_code == 200, list_tasks_response.text
    assert any(item["id"] == legacy_task_id for item in list_tasks_response.json())

    update_task_response = client.put(
        f"/api/tasks/{legacy_task_id}",
        headers=headers,
        json={"name": "legacy-demo-updated", "cron": "0 7 * * *", "enabled": False},
    )
    assert update_task_response.status_code == 200, update_task_response.text
    assert update_task_response.json()["name"] == "legacy-demo-updated"

    run_task_response = client.post(f"/api/tasks/{legacy_task_id}/run", headers=headers)
    assert run_task_response.status_code == 200, run_task_response.text
    assert run_task_response.json()["status"] == "success"
    log_id = run_task_response.json()["id"]

    task_logs_response = client.get(f"/api/tasks/{legacy_task_id}/logs", headers=headers)
    assert task_logs_response.status_code == 200, task_logs_response.text
    assert len(task_logs_response.json()) >= 1

    log_output_response = client.get(f"/api/tasks/logs/{log_id}/output", headers=headers)
    assert log_output_response.status_code == 200, log_output_response.text
    assert "task stdout" in log_output_response.json()["output"]

    with db_module.get_session_local()() as db:
        event_stream = events_route._logs_event_stream(db, object())
        first_chunk = asyncio.run(event_stream.__anext__()).decode("utf-8")
        asyncio.run(event_stream.aclose())
    assert '"task_id"' in first_chunk

    delete_task_response = client.delete(f"/api/tasks/{legacy_task_id}", headers=headers)
    assert delete_task_response.status_code == 200, delete_task_response.text

    sign_task_payload = {
        "name": "shared-demo",
        "account_name": "acc-login",
        "account_names": ["acc-login", "acc-extra"],
        "sign_at": "08:00",
        "chats": [
            {
                "chat_id": -10001,
                "name": "Shared Chat",
                "actions": [{"action": 1, "text": "/checkin"}],
                "action_interval": 1,
            }
        ],
        "random_seconds": 0,
        "sign_interval": 1,
        "execution_mode": "listen",
        "notify_on_failure": True,
    }

    create_sign_task_response = client.post(
        "/api/sign-tasks",
        headers=headers,
        json=sign_task_payload,
    )
    assert create_sign_task_response.status_code == 201, create_sign_task_response.text
    assert create_sign_task_response.json()["account_names"] == ["acc-login", "acc-extra"]

    list_sign_tasks_response = client.get("/api/sign-tasks?aggregate=true", headers=headers)
    assert list_sign_tasks_response.status_code == 200, list_sign_tasks_response.text
    assert len(list_sign_tasks_response.json()) == 1

    update_sign_task_response = client.put(
        "/api/sign-tasks/shared-demo?account_name=acc-login",
        headers=headers,
        json={
            "execution_mode": "fixed",
            "sign_at": "09:30",
            "account_names": ["acc-login", "acc-extra"],
        },
    )
    assert update_sign_task_response.status_code == 200, update_sign_task_response.text
    assert update_sign_task_response.json()["sign_at"] == "09:30"

    sign_task_service = sign_tasks_module.get_sign_task_service()
    sign_task_service._save_run_info(
        "shared-demo",
        True,
        "ok",
        "acc-login",
        flow_logs=[
            "2026-05-08 10:00:00 - text: first message",
            "2026-05-08 10:00:01 - text: last target message",
        ],
    )

    async def _fake_run_task_with_logs(account_name: str, task_name: str):
        sign_task_service._active_logs[(account_name, task_name)] = ["run line 1", "run line 2"]
        return {"success": True, "output": "run line 1\nrun line 2", "error": ""}

    monkeypatch.setattr(sign_task_service, "run_task_with_logs", _fake_run_task_with_logs)

    run_sign_task_response = client.post(
        "/api/sign-tasks/shared-demo/run?account_name=acc-login",
        headers=headers,
    )
    assert run_sign_task_response.status_code == 200, run_sign_task_response.text
    assert run_sign_task_response.json()["success"] is True

    sign_task_logs_response = client.get(
        "/api/sign-tasks/shared-demo/logs?account_name=acc-login",
        headers=headers,
    )
    assert sign_task_logs_response.status_code == 200, sign_task_logs_response.text
    assert sign_task_logs_response.json() == ["run line 1", "run line 2"]

    sign_task_history_response = client.get(
        "/api/sign-tasks/shared-demo/history?account_name=acc-login&limit=10",
        headers=headers,
    )
    assert sign_task_history_response.status_code == 200, sign_task_history_response.text
    history_data = sign_task_history_response.json()
    assert history_data[0]["last_target_message"] == "last target message"

    account_logs_response = client.get("/api/accounts/acc-login/logs?limit=10", headers=headers)
    assert account_logs_response.status_code == 200, account_logs_response.text
    assert account_logs_response.json()[0]["bot_message"] == "last target message"

    recent_logs_response = client.get("/api/accounts/logs/recent?limit=10", headers=headers)
    assert recent_logs_response.status_code == 200, recent_logs_response.text
    assert recent_logs_response.json()[0]["bot_message"] == "last target message"

    export_logs_response = client.get("/api/accounts/acc-login/logs/export", headers=headers)
    assert export_logs_response.status_code == 200, export_logs_response.text
    assert "Account Logs for: acc-login" in export_logs_response.text

    clear_logs_response = client.post("/api/accounts/acc-login/logs/clear", headers=headers)
    assert clear_logs_response.status_code == 200, clear_logs_response.text
    assert clear_logs_response.json()["success"] is True

    delete_sign_task_response = client.delete(
        "/api/sign-tasks/shared-demo?account_name=acc-login",
        headers=headers,
    )
    assert delete_sign_task_response.status_code == 200, delete_sign_task_response.text


def test_pending_totp_setup_expires_and_reset_clears_pending(app_ctx, monkeypatch):
    client: TestClient = app_ctx["client"]

    import backend.api.routes.user as user_route

    now = 1000.0
    monkeypatch.setattr(user_route.time, "monotonic", lambda: now)

    token = _login(client, "admin", "AdminPass123!")
    headers = _headers(token)

    setup_response = client.post("/api/user/totp/setup", headers=headers)
    assert setup_response.status_code == 200, setup_response.text
    secret = setup_response.json()["secret"]
    assert secret

    monkeypatch.setattr(
        user_route.time,
        "monotonic",
        lambda: now + user_route._PENDING_TOTP_TTL_SECONDS + 1,
    )

    expired_qr = client.get("/api/user/totp/qrcode", headers=headers)
    assert expired_qr.status_code == 400
    assert "setup" in expired_qr.json()["detail"].lower()

    expired_enable = client.post(
        "/api/user/totp/enable",
        headers=headers,
        json={"totp_code": pyotp.TOTP(secret).now()},
    )
    assert expired_enable.status_code == 400
    assert "setup" in expired_enable.json()["detail"].lower()

    fresh_setup = client.post("/api/user/totp/setup", headers=headers)
    assert fresh_setup.status_code == 200, fresh_setup.text
    fresh_secret = fresh_setup.json()["secret"]
    assert fresh_secret != secret

    reset_response = client.post(
        "/api/auth/reset-totp",
        json={"username": "admin", "password": "AdminPass123!"},
    )
    assert reset_response.status_code == 200, reset_response.text
    assert user_route.get_pending_totp_secret(1) is None

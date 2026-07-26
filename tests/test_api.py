"""
API 端点集成测试

覆盖三大 API 模块：
- 认证 API（登录、token 验证、未认证访问）
- 账号 API（列表、存在检查、删除、更新）
- 任务 API（CRUD、切换启用状态）

使用 FastAPI TestClient + 内存 SQLite 数据库（StaticPool），
Mock 外部依赖（Telegram 服务、调度器同步）。
"""

from __future__ import annotations

import asyncio
import importlib
from typing import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.core import config as config_module
from backend.core import database as database_module
from backend.models.account import Account
from backend.models.task import Task

# ============================================================================
# 测试专用 Fixtures
# ============================================================================


@pytest.fixture
def api_client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    """
    API 集成测试客户端

    使用 StaticPool 确保所有连接共享同一个内存数据库。
    独立于 conftest 的 client fixture，避免 :memory: 多连接隔离问题。
    """
    # 隔离环境变量
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "data" / "test.sqlite"))
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key-for-jwt")
    monkeypatch.setenv("TG_API_ID", "12345")
    monkeypatch.setenv("TG_API_HASH", "test-api-hash")
    monkeypatch.setenv("SIGN_TASK_FORCE_IN_MEMORY", "1")
    monkeypatch.setenv("SIGN_TASK_EXECUTION_TIMEOUT", "5")
    monkeypatch.setenv("AI_REQUEST_TIMEOUT", "5")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin123")

    # 重置数据库模块状态
    config_module.get_settings.cache_clear()
    database_module._engine = None
    database_module._SessionLocal = None

    # 创建 StaticPool 引擎，保证所有连接共享同一内存数据库
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    database_module.Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    database_module._engine = engine
    database_module._SessionLocal = testing_session

    # 导入应用（触发模块注册，但不执行 lifespan）
    main = importlib.import_module("backend.main")

    # 注入数据库依赖覆盖
    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[database_module.get_db] = override_get_db

    try:
        # raise_server_exceptions=False 避免 lifespan 异常中断
        with TestClient(main.app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        main.app.dependency_overrides.clear()
        database_module.Base.metadata.drop_all(bind=engine)
        engine.dispose()
        database_module._engine = None
        database_module._SessionLocal = None
        config_module.get_settings.cache_clear()
        # TestClient 关闭后会销毁事件循环，需恢复以避免影响其他测试模块
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())


@pytest.fixture
def db(api_client: TestClient):
    """从同一引擎获取数据库会话，用于创建账号/任务等种子数据"""
    session = database_module._SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ============================================================================
# 辅助函数
# ============================================================================

# ensure_admin 在 lifespan 启动时已创建 admin 用户，密码来自 ADMIN_PASSWORD 环境变量
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"


def _create_account(db, account_name: str = "test_account", **kwargs) -> Account:
    """在数据库中创建账号记录并返回"""
    account = Account(
        account_name=account_name,
        api_id=kwargs.get("api_id", "12345"),
        api_hash=kwargs.get("api_hash", "test-api-hash"),
        proxy=kwargs.get("proxy"),
        status=kwargs.get("status", "idle"),
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def _login(client: TestClient, username: str = ADMIN_USERNAME, password: str = ADMIN_PASSWORD) -> str:
    """登录并返回 Bearer token"""
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, f"登录失败: {resp.status_code} {resp.text}"
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    """生成 Authorization 请求头"""
    return {"Authorization": f"Bearer {token}"}


def _mock_tg_service():
    """创建 TelegramService Mock"""
    svc = MagicMock()
    svc.list_accounts.return_value = []
    svc.account_exists.return_value = False
    svc.delete_account = AsyncMock(return_value=True)
    svc.rename_account = AsyncMock(side_effect=lambda old, new: new)
    svc.check_account_status = AsyncMock(
        return_value={
            "account_name": "test",
            "ok": True,
            "status": "connected",
            "message": "OK",
            "code": None,
            "checked_at": None,
            "needs_relogin": False,
        }
    )
    svc.download_account_avatar = AsyncMock(return_value=None)
    return svc


# ============================================================================
# 认证 API 测试
# ============================================================================


class TestAuthAPI:
    """认证 API 端点测试"""

    def test_login_success(self, api_client, db):
        """登录成功：提供正确用户名和密码，返回 access_token"""
        resp = api_client.post(
            "/api/auth/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert len(data["access_token"]) > 0

    def test_login_wrong_password(self, api_client, db):
        """登录失败：密码错误返回 401"""
        resp = api_client.post(
            "/api/auth/login",
            json={"username": ADMIN_USERNAME, "password": "wrongpassword"},
        )

        assert resp.status_code == 401
        assert "Invalid username or password" in resp.json()["detail"]

    def test_login_wrong_username(self, api_client, db):
        """登录失败：用户名不存在返回 401"""


        resp = api_client.post(
            "/api/auth/login",
            json={"username": "nonexistent", "password": ADMIN_PASSWORD},
        )

        assert resp.status_code == 401

    def test_login_empty_credentials(self, api_client, db):
        """登录失败：空用户名返回 401"""


        resp = api_client.post(
            "/api/auth/login",
            json={"username": "", "password": ADMIN_PASSWORD},
        )

        assert resp.status_code == 401

    def test_me_authenticated(self, api_client, db):
        """获取当前用户信息：认证后返回用户详情"""
        token = _login(api_client)

        resp = api_client.get("/api/auth/me", headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == ADMIN_USERNAME
        assert "id" in data

    def test_me_unauthenticated(self, api_client, db):
        """未认证访问受保护端点：返回 401"""
        resp = api_client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_me_invalid_token(self, api_client, db):
        """无效 token 访问受保护端点：返回 401"""
        resp = api_client.get(
            "/api/auth/me",
            headers=_auth("invalid.token.value"),
        )
        assert resp.status_code == 401

    def test_login_returns_usable_token(self, api_client, db):
        """登录返回的 token 可用于访问受保护端点"""

        token = _login(api_client)

        resp = api_client.get("/api/auth/me", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["username"] == ADMIN_USERNAME


# ============================================================================
# 账号 API 测试
# ============================================================================


class TestAccountAPI:
    """账号 API 端点测试"""

    def test_list_accounts_empty(self, api_client, db):
        """账号列表：无账号时返回空列表"""

        token = _login(api_client)

        mock_svc = _mock_tg_service()
        mock_svc.list_accounts.return_value = []

        with patch("backend.api.routes.accounts.get_telegram_service", return_value=mock_svc):
            resp = api_client.get("/api/accounts", headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["accounts"] == []

    def test_list_accounts_with_data(self, api_client, db):
        """账号列表：有账号时返回账号信息"""

        token = _login(api_client)

        mock_svc = _mock_tg_service()
        mock_svc.list_accounts.return_value = [
            {
                "name": "account_1",
                "session_file": "account_1.session",
                "exists": True,
                "size": 1024,
                "remark": None,
                "proxy": None,
                "status": "connected",
                "status_message": None,
                "status_code": None,
                "status_checked_at": None,
                "needs_relogin": False,
            },
            {
                "name": "account_2",
                "session_file": "account_2.session",
                "exists": True,
                "size": 2048,
                "remark": "备注",
                "proxy": None,
                "status": "idle",
                "status_message": None,
                "status_code": None,
                "status_checked_at": None,
                "needs_relogin": False,
            },
        ]

        with patch("backend.api.routes.accounts.get_telegram_service", return_value=mock_svc):
            resp = api_client.get("/api/accounts", headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["accounts"]) == 2
        assert data["accounts"][0]["name"] == "account_1"
        assert data["accounts"][1]["name"] == "account_2"
        assert data["accounts"][1]["remark"] == "备注"

    def test_list_accounts_unauthenticated(self, api_client, db):
        """未认证访问账号列表：返回 401"""
        resp = api_client.get("/api/accounts")
        assert resp.status_code == 401

    def test_check_account_exists_true(self, api_client, db):
        """检查账号存在：返回 exists=true"""

        token = _login(api_client)

        mock_svc = _mock_tg_service()
        mock_svc.account_exists.return_value = True

        with patch("backend.api.routes.accounts.get_telegram_service", return_value=mock_svc):
            resp = api_client.get("/api/accounts/existing_acc/exists", headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        assert data["exists"] is True
        assert data["account_name"] == "existing_acc"

    def test_check_account_exists_false(self, api_client, db):
        """检查账号不存在：返回 exists=false"""

        token = _login(api_client)

        mock_svc = _mock_tg_service()
        mock_svc.account_exists.return_value = False

        with patch("backend.api.routes.accounts.get_telegram_service", return_value=mock_svc):
            resp = api_client.get("/api/accounts/ghost_acc/exists", headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        assert data["exists"] is False

    def test_delete_account_success(self, api_client, db):
        """删除账号成功：返回 success=true"""

        token = _login(api_client)

        mock_svc = _mock_tg_service()
        mock_svc.delete_account = AsyncMock(return_value=True)

        with patch("backend.api.routes.accounts.get_telegram_service", return_value=mock_svc):
            resp = api_client.delete("/api/accounts/old_account", headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "old_account" in data["message"]
        mock_svc.delete_account.assert_called_once_with("old_account")

    def test_delete_account_not_found(self, api_client, db):
        """删除不存在的账号：返回 404"""

        token = _login(api_client)

        mock_svc = _mock_tg_service()
        mock_svc.delete_account = AsyncMock(return_value=False)

        with patch("backend.api.routes.accounts.get_telegram_service", return_value=mock_svc):
            resp = api_client.delete("/api/accounts/ghost", headers=_auth(token))

        assert resp.status_code == 404

    def test_delete_account_unauthenticated(self, api_client, db):
        """未认证删除账号：返回 401"""
        resp = api_client.delete("/api/accounts/some_account")
        assert resp.status_code == 401

    def test_update_account_remark(self, api_client, db):
        """更新账号备注"""

        token = _login(api_client)

        mock_svc = _mock_tg_service()
        original_account = {
            "name": "my_account",
            "session_file": "my_account.session",
            "exists": True,
            "size": 1024,
            "remark": None,
            "proxy": None,
            "status": "connected",
            "status_message": None,
            "status_code": None,
            "status_checked_at": None,
            "needs_relogin": False,
        }
        # 首次查找用原始数据，更新后刷新用新数据
        mock_svc.list_accounts.side_effect = [
            [original_account],
            [{**original_account, "remark": "新备注"}],
        ]

        with patch("backend.api.routes.accounts.get_telegram_service", return_value=mock_svc), \
             patch("backend.utils.tg_session.set_account_profile"):
            resp = api_client.patch(
                "/api/accounts/my_account",
                json={"remark": "新备注"},
                headers=_auth(token),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["account"]["remark"] == "新备注"

    def test_update_account_not_found(self, api_client, db):
        """更新不存在的账号：返回 404"""

        token = _login(api_client)

        mock_svc = _mock_tg_service()
        mock_svc.list_accounts.return_value = []

        with patch("backend.api.routes.accounts.get_telegram_service", return_value=mock_svc):
            resp = api_client.patch(
                "/api/accounts/ghost",
                json={"remark": "test"},
                headers=_auth(token),
            )

        assert resp.status_code == 404

    def test_update_account_unauthenticated(self, api_client, db):
        """未认证更新账号：返回 401"""
        resp = api_client.patch("/api/accounts/some_account", json={"remark": "test"})
        assert resp.status_code == 401

    def test_check_accounts_status(self, api_client, db):
        """批量检测账号状态"""

        token = _login(api_client)

        mock_svc = _mock_tg_service()
        mock_svc.list_accounts.return_value = [
            {"name": "acc_1", "session_file": "acc_1.session", "exists": True, "size": 1024},
            {"name": "acc_2", "session_file": "acc_2.session", "exists": True, "size": 2048},
        ]
        mock_svc.check_account_status = AsyncMock(
            return_value={
                "account_name": "test",
                "ok": True,
                "status": "connected",
                "message": "OK",
                "code": None,
                "checked_at": None,
                "needs_relogin": False,
            }
        )

        with patch("backend.api.routes.accounts.get_telegram_service", return_value=mock_svc):
            resp = api_client.post(
                "/api/accounts/status/check",
                json={"account_names": ["acc_1", "acc_2"], "timeout_seconds": 5.0},
                headers=_auth(token),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 2




def _seed_legacy_task(db, account, name="seed_task", cron="0 6 * * *", enabled=True):
    """直接写 ORM，供只读 GET 用例准备数据（写 API 已永久 410）。"""
    task = Task(name=name, cron=cron, enabled=enabled, account_id=account.id)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


# ============================================================================
# 任务 API 测试
# ============================================================================


class TestTaskAPI:
    """旧版 /api/tasks：写路径永久 410；只读 GET 仍可用。"""

    def test_list_tasks_empty(self, api_client, db):
        token = _login(api_client)
        resp = api_client.get("/api/tasks", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_tasks_unauthenticated(self, api_client, db):
        resp = api_client.get("/api/tasks")
        assert resp.status_code == 401

    def test_create_task_gone(self, api_client, db):
        token = _login(api_client)
        account = _create_account(db)
        resp = api_client.post(
            "/api/tasks",
            json={
                "name": "daily_sign",
                "cron": "0 6 * * *",
                "enabled": True,
                "account_id": account.id,
            },
            headers=_auth(token),
        )
        assert resp.status_code == 410
        assert resp.json().get("detail") == "LEGACY_TASKS_READONLY"

    def test_create_task_unauthenticated(self, api_client, db):
        resp = api_client.post(
            "/api/tasks",
            json={"name": "task", "cron": "0 6 * * *", "enabled": True, "account_id": 1},
        )
        assert resp.status_code == 401

    def test_get_task(self, api_client, db):
        token = _login(api_client)
        account = _create_account(db)
        task = _seed_legacy_task(db, account, name="fetch_task", cron="30 8 * * *")
        resp = api_client.get(f"/api/tasks/{task.id}", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == task.id
        assert data["name"] == "fetch_task"
        assert data["cron"] == "30 8 * * *"

    def test_get_task_not_found(self, api_client, db):
        token = _login(api_client)
        resp = api_client.get("/api/tasks/9999", headers=_auth(token))
        assert resp.status_code == 404
        assert "Task not found" in resp.json()["detail"]

    def test_update_task_gone(self, api_client, db):
        token = _login(api_client)
        account = _create_account(db)
        task = _seed_legacy_task(db, account, name="old_name")
        resp = api_client.put(
            f"/api/tasks/{task.id}",
            json={"name": "new_name", "cron": "30 9 * * 1-5"},
            headers=_auth(token),
        )
        assert resp.status_code == 410
        assert resp.json().get("detail") == "LEGACY_TASKS_READONLY"

    def test_delete_task_gone(self, api_client, db):
        token = _login(api_client)
        account = _create_account(db)
        task = _seed_legacy_task(db, account, name="doomed_task")
        resp = api_client.delete(f"/api/tasks/{task.id}", headers=_auth(token))
        assert resp.status_code == 410
        assert resp.json().get("detail") == "LEGACY_TASKS_READONLY"
        # 只读 GET 仍可见
        get_resp = api_client.get(f"/api/tasks/{task.id}", headers=_auth(token))
        assert get_resp.status_code == 200

    def test_delete_task_unauthenticated(self, api_client, db):
        resp = api_client.delete("/api/tasks/1")
        assert resp.status_code == 401

    def test_run_task_gone(self, api_client, db):
        token = _login(api_client)
        account = _create_account(db)
        task = _seed_legacy_task(db, account, name="run_me")
        resp = api_client.post(f"/api/tasks/{task.id}/run", headers=_auth(token))
        assert resp.status_code == 410
        assert resp.json().get("detail") == "LEGACY_TASKS_READONLY"

    def test_list_tasks_with_data(self, api_client, db):
        token = _login(api_client)
        account = _create_account(db)
        _seed_legacy_task(db, account, name="task_a", cron="0 6 * * *", enabled=True)
        _seed_legacy_task(db, account, name="task_b", cron="0 7 * * *", enabled=False)
        resp = api_client.get("/api/tasks", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert {t["name"] for t in data} == {"task_a", "task_b"}

    def test_get_task_logs_empty(self, api_client, db):
        token = _login(api_client)
        account = _create_account(db)
        task = _seed_legacy_task(db, account, name="logged_task")
        resp = api_client.get(f"/api/tasks/{task.id}/logs", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_task_logs_not_found(self, api_client, db):
        token = _login(api_client)
        resp = api_client.get("/api/tasks/9999/logs", headers=_auth(token))
        assert resp.status_code == 404

    def test_legacy_readonly_status_writes_removed(self, api_client, db):
        token = _login(api_client)
        resp = api_client.get("/api/tasks/legacy-status", headers=_auth(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["legacy_writes_allowed"] is False
        assert body.get("legacy_writes_removed") is True
        assert body["ready_for_route_removal"] is True



# ============================================================================
# 新增功能测试：timezone、retry_count
# ============================================================================


class TestTimezoneSettings:
    """时区配置 API 测试"""

    def test_get_settings_returns_timezone(self, api_client, db):
        """GET /api/config/settings 应返回 timezone 字段"""
        token = _login(api_client)
        resp = api_client.get("/api/config/settings", headers=_auth(token))
        assert resp.status_code == 200
        assert "timezone" in resp.json()
        assert resp.json()["timezone"]  # 非空

    def test_save_timezone(self, api_client, db):
        """POST /api/config/settings 可保存时区"""
        token = _login(api_client)
        resp = api_client.post(
            "/api/config/settings",
            json={"timezone": "Asia/Tokyo"},
            headers=_auth(token),
        )
        assert resp.status_code == 200
        # 验证保存成功
        get_resp = api_client.get("/api/config/settings", headers=_auth(token))
        assert get_resp.json()["timezone"] == "Asia/Tokyo"

    def test_save_invalid_timezone_rejected(self, api_client, db):
        """无效时区应返回 400"""
        token = _login(api_client)
        resp = api_client.post(
            "/api/config/settings",
            json={"timezone": "Invalid/Zone"},
            headers=_auth(token),
        )
        assert resp.status_code == 400

    def test_partial_save_preserves_timezone(self, api_client, db):
        """保存其他字段时不应覆盖已有时区"""
        token = _login(api_client)
        # 先设置时区
        api_client.post(
            "/api/config/settings",
            json={"timezone": "Europe/Berlin"},
            headers=_auth(token),
        )
        # 再保存其他字段（不传 timezone）
        api_client.post(
            "/api/config/settings",
            json={"tg_global_concurrency": 3},
            headers=_auth(token),
        )
        # 时区应保持不变
        get_resp = api_client.get("/api/config/settings", headers=_auth(token))
        assert get_resp.json()["timezone"] == "Europe/Berlin"


class TestRetryCountValidation:
    """retry_count 后端校验测试"""

    def test_retry_count_negative_rejected(self, api_client, db):
        """retry_count < 0 应被拒绝"""
        token = _login(api_client)
        _create_account(db, account_name="acc1")
        db.commit()
        resp = api_client.post(
            "/api/sign-tasks",
            json={
                "name": "test_task",
                "account_name": "acc1",
                "account_names": ["acc1"],
                "sign_at": "08:00",
                "chats": [{"chat_id": 123, "name": "test", "actions": [{"action": 1, "text": "hi"}]}],
                "retry_count": -1,
            },
            headers=_auth(token),
        )
        assert resp.status_code == 422

    def test_retry_count_over_99_rejected(self, api_client, db):
        """retry_count > 99 应被拒绝"""
        token = _login(api_client)
        _create_account(db, account_name="acc1")
        db.commit()
        resp = api_client.post(
            "/api/sign-tasks",
            json={
                "name": "test_task",
                "account_name": "acc1",
                "account_names": ["acc1"],
                "sign_at": "08:00",
                "chats": [{"chat_id": 123, "name": "test", "actions": [{"action": 1, "text": "hi"}]}],
                "retry_count": 100,
            },
            headers=_auth(token),
        )
        assert resp.status_code == 422

    def test_retry_count_valid_accepted(self, api_client, db):
        """有效 retry_count 应被接受"""
        token = _login(api_client)
        _create_account(db, account_name="acc1")
        db.commit()
        with patch("backend.api.routes.sign_tasks_v2.asyncio.ensure_future"):
            resp = api_client.post(
                "/api/sign-tasks",
                json={
                    "name": "test_retry",
                    "account_name": "acc1",
                    "account_names": ["acc1"],
                    "sign_at": "08:00",
                    "chats": [{"chat_id": 123, "name": "test", "actions": [{"action": 1, "text": "hi"}]}],
                    "retry_count": 5,
                },
                headers=_auth(token),
            )
        assert resp.status_code == 201
        assert resp.json()["retry_count"] == 5

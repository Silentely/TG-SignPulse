"""API 错误码化回归测试。

确保任务/账号核心路径的 500/404 返回稳定错误码（CODE 形态），
不再把内部异常细节（str(e)）暴露给前端；前端据此映射 i18n 文案。
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from backend.core.auth import create_access_token


def _auth_headers() -> dict:
    token = create_access_token(
        {"sub": "admin"},
        expires_delta=timedelta(hours=1),
    )
    return {"Authorization": f"Bearer {token}"}


_MINIMAL_TASK_BODY = {
    "name": "t1",
    "account_name": "acc1",
    "sign_at": "09:00",
    "chats": [
        {"chat_id": 1, "name": "c", "actions": [{"action": 1, "text": "x"}]}
    ],
}


class TestSignTaskErrorCodes:
    def test_get_missing_task_returns_stable_code(self, client, db_session):
        resp = client.get("/api/sign-tasks/nope", headers=_auth_headers())
        assert resp.status_code == 404
        assert resp.json()["detail"] == "TASK_NOT_FOUND"

    def test_delete_missing_task_returns_stable_code(self, client, db_session):
        svc = MagicMock()
        svc.delete_task.return_value = False
        with patch(
            "backend.api.routes.sign_tasks_v2.get_sign_task_service",
            return_value=svc,
        ):
            resp = client.delete("/api/sign-tasks/nope", headers=_auth_headers())
        assert resp.status_code == 404
        assert resp.json()["detail"] == "TASK_NOT_FOUND"

    def test_create_task_internal_error_hides_detail(self, client, db_session):
        """500 时返回稳定错误码，内部异常（含路径等细节）不泄漏。"""
        svc = MagicMock()
        svc.create_task.side_effect = RuntimeError("boom: /secret/path/session.json")
        with patch(
            "backend.api.routes.sign_tasks_v2.get_sign_task_service",
            return_value=svc,
        ):
            resp = client.post(
                "/api/sign-tasks",
                json=_MINIMAL_TASK_BODY,
                headers=_auth_headers(),
            )
        assert resp.status_code == 500
        body = resp.json()
        assert body["detail"] == "TASK_CREATE_FAILED"
        assert "/secret/path" not in str(body)

    def test_update_task_internal_error_hides_detail(self, client, db_session):
        """更新任务：先查询成功再服务层抛异常 → 500 稳定码。"""
        svc = MagicMock()
        svc.get_task.return_value = {
            "account_names": ["acc1"],
            "account_name": "acc1",
        }
        svc.update_task.side_effect = RuntimeError("update exploded")
        with patch(
            "backend.api.routes.sign_tasks_v2.get_sign_task_service",
            return_value=svc,
        ):
            resp = client.put(
                "/api/sign-tasks/t1",
                json={
                    "sign_at": "10:00",
                    "chats": [
                        {
                            "chat_id": 1,
                            "name": "c",
                            "actions": [{"action": 1, "text": "y"}],
                        }
                    ],
                },
                headers=_auth_headers(),
            )
        assert resp.status_code == 500
        body = resp.json()
        assert body["detail"] == "TASK_UPDATE_FAILED"
        assert "update exploded" not in str(body)

    def test_clone_value_error_keeps_business_detail(self, client, db_session):
        """业务校验 ValueError 保持 400 语义（不码化，信息有排障价值）。"""
        svc = MagicMock()
        svc.clone_task.side_effect = ValueError("目标任务名已存在")
        with patch(
            "backend.api.routes.sign_tasks_v2.get_sign_task_service",
            return_value=svc,
        ):
            resp = client.post(
                "/api/sign-tasks/nope/clone",
                json={"new_name": "dup"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 400
        assert "已存在" in resp.json()["detail"]


class TestAccountErrorCodes:
    def test_delete_missing_account_returns_stable_code(self, client, db_session):
        svc = MagicMock()
        svc.delete_account = AsyncMock(return_value=False)
        with patch(
            "backend.api.routes.accounts.get_telegram_service", return_value=svc
        ):
            resp = client.delete("/api/accounts/missing", headers=_auth_headers())
        assert resp.status_code == 404
        assert resp.json()["detail"] == "ACCOUNT_NOT_FOUND"

    def test_list_accounts_internal_error_hides_detail(self, client, db_session):
        svc = MagicMock()
        svc.list_accounts.side_effect = RuntimeError("disk exploded")
        with patch(
            "backend.api.routes.accounts.get_telegram_service", return_value=svc
        ):
            resp = client.get("/api/accounts", headers=_auth_headers())
        assert resp.status_code == 500
        body = resp.json()
        assert body["detail"] == "ACCOUNTS_LOAD_FAILED"
        assert "disk exploded" not in str(body)

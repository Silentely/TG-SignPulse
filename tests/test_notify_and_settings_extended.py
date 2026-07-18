"""扩展设置、Bot 测试、静默时段、导入预览、自动备份测试。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
from backend.core.auth import create_access_token
from backend.services.backup_archive import prune_backups
from backend.services.push_notifications import is_in_quiet_hours


def _auth_headers() -> dict:
    token = create_access_token(
        {"sub": "admin"},
        expires_delta=timedelta(hours=1),
    )
    return {"Authorization": f"Bearer {token}"}


class TestAdvancedSettingsApi:
    def test_get_settings_includes_advanced_keys(self, client, db_session):
        resp = client.get("/api/config/settings", headers=_auth_headers())
        assert resp.status_code == 200
        body = resp.json()
        for key in (
            "sign_interval",
            "sign_task_execution_timeout",
            "sign_task_account_cooldown",
            "sign_task_flow_retry_attempts",
            "sign_task_history_max_age_days",
            "ai_vision_timeout",
            "ai_vision_retry_attempts",
            "telegram_bot_task_success_enabled",
            "telegram_bot_quiet_hours_enabled",
            "telegram_bot_quiet_hours_start",
            "telegram_bot_quiet_hours_end",
            "auto_backup_enabled",
            "auto_backup_interval_hours",
            "auto_backup_keep",
        ):
            assert key in body, f"missing key {key}"

    def test_save_advanced_execution_settings(self, client, db_session):
        resp = client.post(
            "/api/config/settings",
            json={
                "sign_interval": 45,
                "sign_task_execution_timeout": 240,
                "ai_vision_timeout": 20,
            },
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        got = client.get("/api/config/settings", headers=_auth_headers()).json()
        assert got["sign_interval"] == 45
        assert got["sign_task_execution_timeout"] == 240
        assert got["ai_vision_timeout"] == 20


class TestBotTestApi:
    def test_bot_test_requires_config(self, client, db_session):
        # 清空 token/chat
        client.post(
            "/api/config/settings",
            json={"telegram_bot_token": "", "telegram_bot_chat_id": ""},
            headers=_auth_headers(),
        )
        resp = client.post("/api/config/bot/test", headers=_auth_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert "配置" in body["message"] or "Token" in body["message"] or "token" in body["message"].lower()

    def test_bot_test_success(self, client, db_session):
        client.post(
            "/api/config/settings",
            json={
                "telegram_bot_notify_enabled": True,
                "telegram_bot_token": "123:ABC",
                "telegram_bot_chat_id": "999",
            },
            headers=_auth_headers(),
        )
        with patch(
            "backend.services.push_notifications.send_telegram_bot_message",
            new_callable=AsyncMock,
        ) as m:
            resp = client.post("/api/config/bot/test", headers=_auth_headers())
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        m.assert_awaited()

    def test_bot_test_whitespace_message_uses_default(self, client, db_session):
        client.post(
            "/api/config/settings",
            json={
                "telegram_bot_token": "123:ABC",
                "telegram_bot_chat_id": "999",
            },
            headers=_auth_headers(),
        )
        with patch(
            "backend.services.push_notifications.send_telegram_bot_message",
            new_callable=AsyncMock,
        ) as m:
            resp = client.post(
                "/api/config/bot/test",
                json={"message": "   "},
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        sent_text = m.await_args.kwargs.get("text") or m.await_args.args[0]
        # 关键字参数调用
        if m.await_args.kwargs:
            sent_text = m.await_args.kwargs["text"]
        assert sent_text
        assert sent_text.strip() != ""


class TestQuietHours:
    def test_quiet_hours_overnight(self):
        cfg = {
            "telegram_bot_quiet_hours_enabled": True,
            "telegram_bot_quiet_hours_start": "23:00",
            "telegram_bot_quiet_hours_end": "07:00",
            "timezone": "UTC",
        }
        assert is_in_quiet_hours(
            cfg, datetime(2026, 7, 18, 23, 30, tzinfo=ZoneInfo("UTC"))
        )
        assert is_in_quiet_hours(
            cfg, datetime(2026, 7, 18, 6, 0, tzinfo=ZoneInfo("UTC"))
        )
        assert not is_in_quiet_hours(
            cfg, datetime(2026, 7, 18, 12, 0, tzinfo=ZoneInfo("UTC"))
        )

    def test_quiet_hours_disabled(self):
        cfg = {"telegram_bot_quiet_hours_enabled": False}
        assert not is_in_quiet_hours(
            cfg, datetime(2026, 7, 18, 23, 30, tzinfo=ZoneInfo("UTC"))
        )

    def test_quiet_hours_same_day_window(self):
        cfg = {
            "telegram_bot_quiet_hours_enabled": True,
            "telegram_bot_quiet_hours_start": "12:00",
            "telegram_bot_quiet_hours_end": "14:00",
            "timezone": "UTC",
        }
        assert is_in_quiet_hours(
            cfg, datetime(2026, 7, 18, 13, 0, tzinfo=ZoneInfo("UTC"))
        )
        assert not is_in_quiet_hours(
            cfg, datetime(2026, 7, 18, 11, 0, tzinfo=ZoneInfo("UTC"))
        )


class TestImportPreview:
    def test_import_preview_no_write(self, client, db_session):
        payload = {
            "signs": {"demo_task": {"name": "demo_task", "account_name": "a1"}},
            "monitors": {},
            "settings": {"global": {"log_retention_days": 3}},
        }
        resp = client.post(
            "/api/config/import-preview",
            json={"config_json": json.dumps(payload)},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["signs_count"] == 1
        assert body["monitors_count"] == 0
        assert "global" in body["settings_keys"]
        assert "errors" in body

    def test_import_preview_invalid_json(self, client, db_session):
        resp = client.post(
            "/api/config/import-preview",
            json={"config_json": "{not-json"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["errors"]
        assert body["signs_count"] == 0

    def test_import_preview_unauthenticated(self, client, db_session):
        resp = client.post(
            "/api/config/import-preview",
            json={"config_json": "{}"},
        )
        assert resp.status_code in (401, 403)


class TestBackupPrune:
    def test_prune_keeps_n(self, tmp_path: Path):
        d = tmp_path / "backups"
        d.mkdir()
        for i in range(5):
            p = d / f"auto-2026010{i}-000000.tar.gz"
            p.write_bytes(b"x")
            # 保证 mtime 顺序
            import os
            import time

            os.utime(p, (time.time() + i, time.time() + i))
        assert prune_backups(d, 2) == 3
        assert len(list(d.glob("auto-*.tar.gz"))) == 2

    def test_create_tarball_rejects_empty(self, tmp_path: Path):
        from backend.services.backup_archive import create_backup_tarball

        data = tmp_path / "data"
        data.mkdir()
        dest = tmp_path / "out.tar.gz"
        with pytest.raises(ValueError):
            create_backup_tarball(data, dest)

    def test_create_tarball_skips_traversal(self, tmp_path: Path):
        from backend.services.backup_archive import create_backup_tarball

        data = tmp_path / "data"
        data.mkdir()
        (data / "ok.txt").write_text("x", encoding="utf-8")
        dest = tmp_path / "out.tar.gz"
        # 同时含合法与穿越路径时，应只打包合法文件
        create_backup_tarball(data, dest, paths=("ok.txt", "../etc/passwd", "/etc/passwd"))
        assert dest.exists() and dest.stat().st_size > 0

    def test_run_auto_backup_empty_data(self, tmp_path: Path):
        from backend.services.backup_archive import run_auto_backup

        data = tmp_path / "empty"
        data.mkdir()
        result = run_auto_backup(data, keep=1)
        assert result["success"] is False


@pytest.mark.asyncio
async def test_server_chan_channel():
    from backend.services.push_notifications import send_keyword_push

    with patch(
        "tg_signer.notification.server_chan.sc_send", new_callable=AsyncMock
    ) as m:
        m.return_value = {"code": 0}
        await send_keyword_push(
            {
                "keyword_monitor_push_channel": "server_chan",
                "keyword_monitor_server_chan_send_key": "SCT_TEST",
            },
            {"title": "hit", "body": "body"},
        )
        m.assert_awaited()


@pytest.mark.asyncio
async def test_success_notification_respects_quiet_hours():
    from backend.services.push_notifications import send_task_success_notification

    cfg = {
        "telegram_bot_notify_enabled": True,
        "telegram_bot_task_success_enabled": True,
        "telegram_bot_quiet_hours_enabled": True,
        "telegram_bot_quiet_hours_start": "00:00",
        "telegram_bot_quiet_hours_end": "23:59",
        "timezone": "UTC",
        "telegram_bot_token": "1:t",
        "telegram_bot_chat_id": "1",
    }
    with patch(
        "backend.services.push_notifications.send_telegram_bot_message",
        new_callable=AsyncMock,
    ) as m:
        await send_task_success_notification(
            cfg, account_name="a", task_name="t", message="ok"
        )
        m.assert_not_awaited()


def test_global_settings_includes_timezone(client, db_session):
    resp = client.get("/api/config/settings", headers=_auth_headers())
    assert resp.status_code == 200
    assert resp.json().get("timezone")


class TestCloneSignTask:
    """签到任务克隆 API。"""

    def _create_minimal(self, client, name: str = "src_task") -> None:
        with patch("backend.api.routes.sign_tasks_v2.asyncio.ensure_future"):
            # client fixture 使用内存库，需先有账号目录侧的 create 路径
            # create_task 会校验账号列表：通过 mock 扩展账号名解析
            from backend.services.sign_tasks import get_sign_task_service

            svc = get_sign_task_service()
            with patch.object(
                svc,
                "_normalize_account_names",
                return_value=["acc1"],
            ), patch.object(
                svc,
                "_expand_account_names",
                return_value=["acc1"],
            ), patch(
                "backend.scheduler.add_or_update_sign_task_job",
            ), patch(
                "backend.scheduler.remove_sign_task_job",
            ):
                task = svc.create_task(
                    task_name=name,
                    sign_at="09:00",
                    chats=[
                        {
                            "chat_id": 12345,
                            "name": "bot",
                            "actions": [{"action": 1, "text": "/checkin"}],
                            "action_interval": 1,
                        }
                    ],
                    account_name="acc1",
                    account_names=["acc1"],
                    execution_mode="fixed",
                    retry_count=2,
                )
                assert task["name"] == name

    def test_clone_success(self, client, db_session, isolated_env):
        self._create_minimal(client, "src_clone")
        with patch("backend.api.routes.sign_tasks_v2.asyncio.ensure_future"), patch(
            "backend.scheduler.add_or_update_sign_task_job",
        ), patch(
            "backend.scheduler.remove_sign_task_job",
        ):
            from backend.services.sign_tasks import get_sign_task_service

            svc = get_sign_task_service()
            with patch.object(
                svc, "_normalize_account_names", return_value=["acc1"]
            ), patch.object(
                svc, "_expand_account_names", return_value=["acc1"]
            ):
                resp = client.post(
                    "/api/sign-tasks/src_clone/clone",
                    json={"new_name": "src_clone_copy"},
                    headers=_auth_headers(),
                )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["name"] == "src_clone_copy"
        assert body.get("retry_count") == 2

    def test_clone_duplicate_rejected(self, client, db_session, isolated_env):
        self._create_minimal(client, "dup_src")
        self._create_minimal(client, "dup_dst")
        resp = client.post(
            "/api/sign-tasks/dup_src/clone",
            json={"new_name": "dup_dst"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 400
        assert "已存在" in resp.json().get("detail", "")

    def test_clone_missing_source(self, client, db_session):
        resp = client.post(
            "/api/sign-tasks/no_such_task/clone",
            json={"new_name": "x"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 400

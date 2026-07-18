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
            "telegram_bot_token_set",
            "auto_backup_enabled",
            "auto_backup_interval_hours",
            "auto_backup_keep",
            "webdav_url",
            "webdav_username",
            "webdav_password",
            "webdav_password_set",
            "webdav_remote_dir",
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

    def test_notify_on_success_roundtrip(self, client, db_session, isolated_env):
        """创建时写入 notify_on_success，更新后可读回。"""
        from backend.services.sign_tasks import get_sign_task_service

        svc = get_sign_task_service()
        with patch.object(svc, "_normalize_account_names", return_value=["acc1"]), patch.object(
            svc, "_expand_account_names", return_value=["acc1"]
        ), patch("backend.scheduler.add_or_update_sign_task_job"), patch(
            "backend.scheduler.remove_sign_task_job"
        ), patch("backend.api.routes.sign_tasks_v2.asyncio.ensure_future"):
            created = svc.create_task(
                task_name="notify_ok",
                sign_at="10:00",
                chats=[{"chat_id": 1, "name": "c", "actions": [{"action": 1, "text": "x"}]}],
                account_name="acc1",
                account_names=["acc1"],
                notify_on_success=False,
            )
            assert created.get("notify_on_success") is False
            updated = svc.update_task(
                task_name="notify_ok",
                account_name="acc1",
                notify_on_success=True,
            )
            assert updated.get("notify_on_success") is True


class TestWebdavBackupChain:
    """WebDAV 配置落盘 → 备份上传 / 测试连通 链路。"""

    @pytest.fixture(autouse=True)
    def _reset_config_service(self, isolated_env, client):
        """ConfigService 单例绑定 workdir，测试间强制重建避免串配置。"""
        import backend.services.config as config_mod

        config_mod._config_service = None
        yield
        config_mod._config_service = None

    def test_webdav_settings_roundtrip(self, client, db_session):
        resp = client.post(
            "/api/config/settings",
            json={
                "webdav_url": "https://dav.example.com/remote.php/dav/files/u",
                "webdav_username": "user1",
                "webdav_password": "secret",
                "webdav_remote_dir": "my-backups",
            },
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        got = client.get("/api/config/settings", headers=_auth_headers()).json()
        assert got["webdav_url"] == "https://dav.example.com/remote.php/dav/files/u"
        assert got["webdav_username"] == "user1"
        # GET 脱敏：不回传明文，仅标记已设置
        assert got.get("webdav_password") in (None, "")
        assert got.get("webdav_password_set") is True
        assert got["webdav_remote_dir"] == "my-backups"
        # 磁盘上仍为明文供上传使用
        from backend.services.config import get_config_service

        stored = get_config_service().get_global_settings()
        assert stored["webdav_password"] == "secret"

    def test_webdav_password_empty_keeps_existing(self, client, db_session):
        client.post(
            "/api/config/settings",
            json={
                "webdav_url": "https://dav.example.com/files/u",
                "webdav_username": "u",
                "webdav_password": "keep-me",
            },
            headers=_auth_headers(),
        )
        # 不传 password 字段 → 不覆盖
        client.post(
            "/api/config/settings",
            json={"webdav_username": "u2"},
            headers=_auth_headers(),
        )
        got = client.get("/api/config/settings", headers=_auth_headers()).json()
        assert got.get("webdav_password_set") is True
        assert got["webdav_username"] == "u2"
        from backend.services.config import get_config_service

        assert get_config_service().get_global_settings()["webdav_password"] == "keep-me"

    def test_backup_export_uploads_when_webdav_configured(
        self, client, db_session, isolated_env
    ):
        client.post(
            "/api/config/settings",
            json={
                "webdav_url": "https://dav.example.com/dav/files/u",
                "webdav_username": "u",
                "webdav_password": "p",
                "webdav_remote_dir": "tg-backups",
            },
            headers=_auth_headers(),
        )

        def _fake_tarball(data_dir, dest, paths):
            Path(dest).write_bytes(b"fake-tar-gz")
            return Path(dest)

        with patch(
            "backend.services.backup_archive.create_backup_tarball",
            side_effect=_fake_tarball,
        ), patch(
            "backend.services.webdav_client.upload_file_to_webdav",
            return_value={
                "success": True,
                "remote_url": "https://dav.example.com/x.tar.gz",
                "filename": "x.tar.gz",
                "size_bytes": 11,
            },
        ) as upload_m:
            resp = client.post("/api/ops/backup/export", headers=_auth_headers())
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body.get("remote_url")
        assert body.get("filename") == "x.tar.gz"
        upload_m.assert_called_once()
        # 必须使用已落盘配置，而非请求体
        call_kw = upload_m.call_args.kwargs
        assert call_kw["base_url"] == "https://dav.example.com/dav/files/u"
        assert call_kw["username"] == "u"
        assert call_kw["password"] == "p"
        assert call_kw["remote_dir"] == "tg-backups"

    def test_backup_export_requires_files_without_webdav(
        self, client, db_session, isolated_env
    ):
        # 空数据目录且无 WebDAV → 400 无文件
        with patch(
            "backend.services.backup_archive.create_backup_tarball",
            side_effect=ValueError("没有可备份的文件"),
        ):
            resp = client.post("/api/ops/backup/export", headers=_auth_headers())
        assert resp.status_code == 400
        assert "备份" in resp.json().get("detail", "") or "文件" in resp.json().get(
            "detail", ""
        )

    def test_webdav_test_endpoint_uses_saved_config(self, client, db_session):
        client.post(
            "/api/config/settings",
            json={
                "webdav_url": "https://dav.example.com/dav",
                "webdav_username": "u",
                "webdav_password": "p",
                "webdav_remote_dir": "nested/dir",
            },
            headers=_auth_headers(),
        )
        with patch(
            "backend.services.webdav_client.check_webdav_connection",
            return_value={"success": True, "message": "ok", "status_code": 207},
        ) as test_m:
            resp = client.post(
                "/api/ops/backup/webdav/test",
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        test_m.assert_called_once()
        kw = test_m.call_args.kwargs
        assert kw["base_url"] == "https://dav.example.com/dav"
        assert kw["username"] == "u"
        assert kw["password"] == "p"
        assert kw["remote_dir"] == "nested/dir"

    def test_auto_backup_uploads_webdav(self, isolated_env: Path):
        """纯 unit：复用 isolated_env 数据目录，避免与 autouse 抢建 tmp_path/data。"""
        from backend.services.backup_archive import run_auto_backup

        data = isolated_env
        (data / ".global_settings.json").write_text("{}", encoding="utf-8")

        with patch(
            "backend.services.webdav_client.upload_file_to_webdav",
            return_value={
                "success": True,
                "remote_url": "https://x/a.tar.gz",
                "filename": "a.tar.gz",
                "size_bytes": 3,
            },
        ) as m:
            result = run_auto_backup(
                data,
                keep=2,
                webdav_settings={
                    "webdav_url": "https://dav.example.com/dav",
                    "webdav_username": "u",
                    "webdav_password": "p",
                    "webdav_remote_dir": "bk",
                },
            )
        assert result["success"] is True
        assert result["webdav"]["success"] is True
        assert result.get("local_removed") is True
        # 上传成功后本地副本应已删除
        assert not list((data / "backups").glob("auto-*.tar.gz"))
        assert result["path"] == "https://x/a.tar.gz"
        m.assert_called_once()
        assert m.call_args.kwargs["remote_dir"] == "bk"
        assert m.call_args.kwargs["username"] == "u"

    def test_auto_backup_keeps_local_when_webdav_fails(self, isolated_env: Path):
        from backend.services.backup_archive import run_auto_backup

        data = isolated_env
        (data / ".global_settings.json").write_text("{}", encoding="utf-8")

        with patch(
            "backend.services.webdav_client.upload_file_to_webdav",
            side_effect=RuntimeError("HTTP 502"),
        ):
            result = run_auto_backup(
                data,
                keep=2,
                webdav_settings={
                    "webdav_url": "https://dav.example.com/dav",
                    "webdav_username": "u",
                    "webdav_password": "p",
                },
            )
        assert result["success"] is True
        assert result.get("local_removed") is False
        assert result["webdav"]["success"] is False
        assert list((data / "backups").glob("auto-*.tar.gz"))

    def test_backup_export_rejects_missing_credentials(self, client, db_session):
        client.post(
            "/api/config/settings",
            json={
                "webdav_url": "https://dav.example.com/dav",
                "webdav_username": "",
                "webdav_password": "p",
            },
            headers=_auth_headers(),
        )
        # 仅 URL、无用户名
        client.post(
            "/api/config/settings",
            json={"webdav_url": "https://dav.example.com/dav", "webdav_username": None},
            headers=_auth_headers(),
        )
        # 直接设内部配置：有 URL 无用户名
        from backend.services.config import get_config_service

        get_config_service().save_global_settings(
            {
                "webdav_url": "https://dav.example.com/dav",
                "webdav_username": None,
                "webdav_password": "p",
            }
        )
        resp = client.post("/api/ops/backup/export", headers=_auth_headers())
        assert resp.status_code == 400
        assert "用户名" in resp.json().get("detail", "")

    def test_backup_status_includes_webdav_flags(self, client, db_session):
        client.post(
            "/api/config/settings",
            json={
                "webdav_url": "https://dav.example.com/dav",
                "webdav_username": "u",
                "webdav_password": "p",
                "auto_backup_enabled": True,
            },
            headers=_auth_headers(),
        )
        resp = client.get("/api/ops/backup/status", headers=_auth_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["webdav_configured"] is True
        assert body["auto_backup_enabled"] is True
        assert "local_auto_backups" in body

    def test_bot_token_masked_on_get_and_empty_keeps(self, client, db_session):
        unique_token = "123456:AAAsecret-bot-mask-test"
        resp = client.post(
            "/api/config/settings",
            json={"telegram_bot_token": unique_token},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        got = client.get("/api/config/settings", headers=_auth_headers()).json()
        assert got.get("telegram_bot_token") in (None, "")
        assert got.get("telegram_bot_token_set") is True
        # 不传 token → 保留
        resp2 = client.post(
            "/api/config/settings",
            json={"telegram_bot_chat_id": "-1001"},
            headers=_auth_headers(),
        )
        assert resp2.status_code == 200
        from backend.services.config import get_config_service

        stored = get_config_service().get_global_settings()["telegram_bot_token"]
        assert stored == unique_token

    def test_export_masks_webdav_and_bot_secrets(self, client, db_session, isolated_env):
        client.post(
            "/api/config/settings",
            json={
                "webdav_url": "https://dav.example.com/dav",
                "webdav_username": "u",
                "webdav_password": "super-secret",
                "telegram_bot_token": "999:BOTSECRET",
            },
            headers=_auth_headers(),
        )
        resp = client.get("/api/config/export/all", headers=_auth_headers())
        assert resp.status_code == 200
        data = json.loads(resp.content.decode("utf-8"))
        g = data.get("settings", {}).get("global", {})
        assert g.get("webdav_password") == "***MASKED***"
        assert g.get("telegram_bot_token") == "***MASKED***"
        dump = json.dumps(data)
        assert "super-secret" not in dump
        assert "BOTSECRET" not in dump
        meta = data.get("_meta", {})
        assert meta.get("webdav_password_masked") is True
        assert meta.get("telegram_bot_token_masked") is True

    def test_list_webdav_files_endpoint(self, client, db_session):
        client.post(
            "/api/config/settings",
            json={
                "webdav_url": "https://dav.example.com/dav",
                "webdav_username": "u",
                "webdav_password": "p",
                "webdav_remote_dir": "bk",
            },
            headers=_auth_headers(),
        )
        with patch(
            "backend.services.webdav_client.list_webdav_files",
            return_value={
                "success": True,
                "files": [
                    {
                        "name": "auto-x.tar.gz",
                        "href": "/bk/auto-x.tar.gz",
                        "size_bytes": 9,
                        "mtime": "Wed, 01 Jan 2025 00:00:00 GMT",
                    }
                ],
                "message": "ok",
                "status_code": 207,
            },
        ) as m:
            resp = client.get(
                "/api/ops/backup/webdav/files", headers=_auth_headers()
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["files"][0]["name"] == "auto-x.tar.gz"
        m.assert_called_once()
        assert m.call_args.kwargs["remote_dir"] == "bk"

    def test_download_webdav_rejects_bad_name(self, client, db_session):
        resp = client.get(
            "/api/ops/backup/webdav/download",
            params={"name": "../evil.tar.gz"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 400

    def test_download_webdav_endpoint_streams(self, client, db_session, tmp_path):
        client.post(
            "/api/config/settings",
            json={
                "webdav_url": "https://dav.example.com/dav",
                "webdav_username": "u",
                "webdav_password": "p",
                "webdav_remote_dir": "bk",
            },
            headers=_auth_headers(),
        )

        def _fake_iter(**kwargs):
            yield b"gzip-"
            yield b"bytes"

        with patch(
            "backend.services.webdav_client.iter_webdav_file",
            side_effect=lambda **kw: _fake_iter(**kw),
        ):
            resp = client.get(
                "/api/ops/backup/webdav/download",
                params={"name": "auto-1.tar.gz"},
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        assert resp.content == b"gzip-bytes"

    def test_auto_backup_prunes_remote_after_upload(self, isolated_env: Path):
        from backend.services.backup_archive import run_auto_backup

        data = isolated_env
        (data / ".global_settings.json").write_text("{}", encoding="utf-8")
        with patch(
            "backend.services.webdav_client.upload_file_to_webdav",
            return_value={
                "success": True,
                "remote_url": "https://x/a.tar.gz",
                "filename": "a.tar.gz",
                "size_bytes": 3,
            },
        ), patch(
            "backend.services.webdav_client.prune_webdav_backups",
            return_value={"success": True, "removed": 2, "kept": 3},
        ) as prune_m:
            result = run_auto_backup(
                data,
                keep=3,
                webdav_settings={
                    "webdav_url": "https://dav.example.com/dav",
                    "webdav_username": "u",
                    "webdav_password": "p",
                    "webdav_remote_dir": "bk",
                },
            )
        assert result["success"] is True
        assert result.get("remote_pruned") == 2
        prune_m.assert_called_once()
        assert prune_m.call_args.kwargs["keep"] == 3


@pytest.mark.asyncio
async def test_auto_backup_failure_notification_sends():
    from backend.services.push_notifications import send_auto_backup_failure_notification

    with patch(
        "backend.services.push_notifications.send_telegram_bot_message",
        new_callable=AsyncMock,
    ) as m:
        # 不依赖 task_failure 开关（运维事件独立）
        await send_auto_backup_failure_notification(
            {
                "telegram_bot_notify_enabled": True,
                "telegram_bot_task_failure_enabled": False,
                "telegram_bot_token": "1:t",
                "telegram_bot_chat_id": "2",
                "telegram_bot_quiet_hours_enabled": False,
            },
            error="WebDAV 上传失败",
        )
        m.assert_awaited()

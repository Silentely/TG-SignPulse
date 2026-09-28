"""配置导出递归脱敏测试。

导出侧此前只处理四个顶层密钥，任务/监控配置内的推送凭据（Bark 设备密钥、
自定义推送 URL 内嵌凭据、Server 酱 sendkey、外部转发回调鉴权头）会随
tar.gz/JSON 导出外泄。本文件锁定递归脱敏契约与导入往返行为。
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from backend.services.config_mixins import (
    _drop_masked_secret_fields,
    _scrub_export_secrets,
)


def _auth_headers() -> dict:
    from backend.core.auth import create_access_token

    token = create_access_token(
        {"sub": "admin"},
        expires_delta=timedelta(hours=1),
    )
    return {"Authorization": f"Bearer {token}"}


class TestScrubPureFunction:
    def test_bark_device_key_is_redacted_by_path_segment(self):
        out = _scrub_export_secrets(
            {"bark_url": "https://api.day.app/DEVICEKEY123/title/body"}
        )
        assert out["bark_url"] == "https://api.day.app/***MASKED***/title/body"
        assert "DEVICEKEY123" not in json.dumps(out)

    def test_custom_url_embedded_credentials_redacted(self):
        out = _scrub_export_secrets(
            {"custom_url": "https://user:sup3rsecret@hook.example.com/push"}
        )
        assert "sup3rsecret" not in out["custom_url"]
        assert out["custom_url"] == "https://***:***@hook.example.com/push"

    def test_proxy_url_embedded_credentials_redacted(self):
        out = _scrub_export_secrets(
            {"global_proxy": "socks5://user:sup3rsecret@proxy.example.com:1080"}
        )
        assert out["global_proxy"] == "socks5://***:***@proxy.example.com:1080"
        assert "sup3rsecret" not in json.dumps(out)

    def test_s3_access_key_is_redacted_and_dropped_on_import(self):
        out = _scrub_export_secrets({"s3_access_key": "access-key"})
        assert out["s3_access_key"] == "***MASKED***"
        assert "s3_access_key" not in _drop_masked_secret_fields(out)

    def test_serverchan_sendkey_redacted(self):
        out = _scrub_export_secrets({"server_chan_send_key": "SCT123456ABC"})
        assert out["server_chan_send_key"] == "***MASKED***"

    def test_forward_callback_auth_headers_redacted(self):
        out = _scrub_export_secrets(
            {
                "external_forwards": [
                    {
                        "type": "http",
                        "url": "https://relay.example.com/hook",
                        "headers": {
                            "Authorization": "Bearer tok_abc",
                            "X-Api-Key": "key_xyz",
                            "Content-Type": "application/json",
                        },
                    }
                ]
            }
        )
        headers = out["external_forwards"][0]["headers"]
        assert headers["Authorization"] == "***MASKED***"
        assert headers["X-Api-Key"] == "***MASKED***"
        # 非鉴权头保持原值
        assert headers["Content-Type"] == "application/json"

    def test_field_name_match_is_case_insensitive(self):
        out = _scrub_export_secrets(
            {"API_KEY": "sk-123", "Bark_URL": "https://api.day.app/K/t"}
        )
        assert out["API_KEY"] == "***MASKED***"
        assert "K/" not in out["Bark_URL"]

    def test_deeply_nested_structures_are_covered(self):
        payload = {
            "signs": {
                "task@acc": {
                    "chats": [
                        {
                            "actions": [
                                {
                                    "action": 8,
                                    "push_channel": "bark",
                                    "bark_url": "https://api.day.app/NESTEDKEY/t/b",
                                }
                            ]
                        }
                    ]
                }
            }
        }
        out = _scrub_export_secrets(payload)
        assert "NESTEDKEY" not in json.dumps(out)

    def test_non_secret_fields_untouched(self):
        payload = {"name": "task", "sign_at": "08:00", "enabled": True, "chats": []}
        assert _scrub_export_secrets(payload) == payload

    def test_empty_values_are_preserved(self):
        payload = {"api_key": "", "bark_url": None, "custom_url": ""}
        assert _scrub_export_secrets(payload) == payload


class TestDropMaskedOnImport:
    def test_masked_values_are_dropped_not_written(self):
        cleaned = _drop_masked_secret_fields(
            {
                "api_key": "***MASKED***",
                "bark_url": "https://api.day.app/***MASKED***/t/b",
                "name": "keep-me",
            }
        )
        assert "api_key" not in cleaned
        assert "bark_url" not in cleaned
        assert cleaned["name"] == "keep-me"

    def test_real_values_survive(self):
        payload = {"api_key": "sk-real", "bark_url": "https://api.day.app/REAL/t"}
        assert _drop_masked_secret_fields(payload) == payload

    def test_nested_auth_header_masked_is_dropped(self):
        cleaned = _drop_masked_secret_fields(
            {"external_forwards": [{"headers": {"Authorization": "***MASKED***"}}]}
        )
        # headers 是容器，仅其中的鉴权头被丢弃，容器本身保留
        assert cleaned["external_forwards"][0]["headers"] == {}


class TestExportRoundTrip:
    @pytest.fixture
    def seeded_service(self, tmp_path, monkeypatch):
        """构造指向临时目录的 ConfigService，并写入含推送凭据的任务配置。"""
        monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
        from backend.core import config as config_module
        from backend.services.config import get_config_service

        config_module.get_settings.cache_clear()
        svc = get_config_service()
        svc.save_sign_config(
            "push_task",
            {
                "name": "push_task",
                "account_name": "acc1",
                "sign_at": "08:00",
                "chats": [
                    {
                        "chat_id": -100123,
                        "actions": [
                            {
                                "action": 8,
                                "match_mode": "contains",
                                "keywords": ["hi"],
                                "push_channel": "bark",
                                "bark_url": "https://api.day.app/BARKDEVKEY/title/body",
                            }
                        ],
                    }
                ],
            },
        )
        return svc

    def test_export_all_configs_redacts_task_push_secrets(self, seeded_service):
        dumped = seeded_service.export_all_configs()
        assert "BARKDEVKEY" not in dumped
        data = json.loads(dumped)
        entry = next(iter(data["signs"].values()))
        bark = entry["chats"][0]["actions"][0]["bark_url"]
        assert bark == "https://api.day.app/***MASKED***/title/body"

    def test_export_sign_task_redacts_push_secrets(self, seeded_service):
        dumped = seeded_service.export_sign_task("push_task", account_name="acc1")
        assert dumped is not None
        assert "BARKDEVKEY" not in dumped
        data = json.loads(dumped)
        bark = data["config"]["chats"][0]["actions"][0]["bark_url"]
        assert bark == "https://api.day.app/***MASKED***/title/body"

    def test_documented_keys_still_masked_with_meta_flags(self, seeded_service):
        seeded_service.save_global_settings(
            {
                "webdav_url": "https://93.184.216.34/dav",
                "webdav_username": "u",
                "webdav_password": "super-secret",
                "telegram_bot_token": "999:BOTSECRET",
            }
        )
        data = json.loads(seeded_service.export_all_configs())
        g = data["settings"]["global"]
        assert g["webdav_password"] == "***MASKED***"
        assert g["telegram_bot_token"] == "***MASKED***"
        assert data["_meta"]["webdav_password_masked"] is True
        assert data["_meta"]["telegram_bot_token_masked"] is True
        dumped = json.dumps(data)
        assert "super-secret" not in dumped
        assert "BOTSECRET" not in dumped

    def test_export_global_proxy_redacts_embedded_credentials(self, seeded_service):
        seeded_service.save_global_settings(
            {"global_proxy": "socks5://user:proxypass@proxy.example.com:1080"}
        )
        dumped = seeded_service.export_all_configs()
        assert "proxypass" not in dumped
        assert "socks5://***:***@proxy.example.com:1080" in dumped

    def test_import_roundtrip_does_not_overwrite_real_secret(self, seeded_service):
        """导出→导入不得用占位符覆盖已落盘的真实凭据。"""
        exported = json.loads(seeded_service.export_all_configs())
        # 导出键为 name@account 形式
        entry = exported["signs"]["push_task@acc1"]
        assert entry["chats"][0]["actions"][0]["bark_url"] == (
            "https://api.day.app/***MASKED***/title/body"
        )
        result = seeded_service.import_all_configs(json.dumps(exported), overwrite=True)
        assert result["signs_imported"] >= 1
        stored = seeded_service.get_sign_config("push_task", account_name="acc1")
        action = stored["chats"][0]["actions"][0]
        # 占位符绝不被当作真实凭据落盘；其余配置字段完整保留
        assert action.get("bark_url") is None
        assert action["push_channel"] == "bark"
        assert action["keywords"] == ["hi"]
        assert stored["sign_at"] == "08:00"
        dumped = json.dumps(stored)
        assert "***MASKED***" not in dumped


class TestGlobalProxyMasking:
    def test_get_settings_returns_only_proxy_flag(self, client, db_session):
        resp = client.post(
            "/api/config/settings",
            json={"global_proxy": "socks5://user:proxypass@10.20.30.40:1080"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200

        got = client.get("/api/config/settings", headers=_auth_headers())
        assert got.status_code == 200
        body = got.json()
        assert body["global_proxy_set"] is True
        assert body["global_proxy"] is None
        assert "proxypass" not in json.dumps(body)

    def test_global_proxy_not_set_reports_false(self, client, db_session):
        body = client.get("/api/config/settings", headers=_auth_headers()).json()
        assert body["global_proxy_set"] is False
        assert body["global_proxy"] is None

    def test_empty_proxy_keeps_existing(self, client, db_session):
        client.post(
            "/api/config/settings",
            json={"global_proxy": "socks5://127.0.0.1:1080"},
            headers=_auth_headers(),
        )
        from backend.services.config import get_config_service

        assert get_config_service().get_global_proxy() == "socks5://127.0.0.1:1080"

        # 空串表示不修改（与 webdav_password 同口径）
        client.post(
            "/api/config/settings",
            json={"global_proxy": ""},
            headers=_auth_headers(),
        )
        assert get_config_service().get_global_proxy() == "socks5://127.0.0.1:1080"

        # 显式 None 清除
        client.post(
            "/api/config/settings",
            json={"global_proxy": None},
            headers=_auth_headers(),
        )
        assert get_config_service().get_global_proxy() is None

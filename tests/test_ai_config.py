"""AI 配置加密存储测试 — 覆盖 config.py 的 save/get/export/test 路径"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.config import ConfigService


class TestSaveAiConfigEncryption:
    """save_ai_config 应使用 Fernet 加密存储 API Key"""

    def test_save_encrypts_api_key(self, isolated_env: Path):
        """保存后磁盘上的 api_key 是 Fernet 密文而非明文"""
        service = ConfigService()
        service.save_ai_config(api_key="sk-test-12345", base_url="https://api.openai.com/v1", model="gpt-4o")

        config_file = service.workdir / ".openai_config.json"
        raw = json.loads(config_file.read_text(encoding="utf-8"))

        assert raw["api_key"] != "sk-test-12345", "API Key 不应明文存储"
        assert raw["api_key"].startswith("fernet:"), "应为 Fernet 加密格式"

    def test_save_none_key_raises(self, isolated_env: Path):
        """None API Key 且无已有配置时应抛出 ValueError"""
        service = ConfigService()
        # 确保无已有配置
        config_file = service.workdir / ".openai_config.json"
        if config_file.exists():
            config_file.unlink()
        with pytest.raises(ValueError, match="API Key 不能为空"):
            service.save_ai_config(api_key=None)

    def test_save_preserves_base_url_and_model(self, isolated_env: Path):
        """保存时应保留 base_url 和 model"""
        service = ConfigService()
        service.save_ai_config(api_key="sk-test", base_url="https://custom.api.com", model="gpt-4o")

        config_file = service.workdir / ".openai_config.json"
        raw = json.loads(config_file.read_text(encoding="utf-8"))

        assert raw["base_url"] == "https://custom.api.com"
        assert raw["model"] == "gpt-4o"

    def test_save_without_key_preserves_existing(self, isolated_env: Path):
        """仅更新 model/base_url 时不得破坏已有密钥"""
        service = ConfigService()
        service.save_ai_config(
            api_key="sk-original-key", base_url="https://a.example", model="gpt-4o"
        )
        service.save_ai_config(api_key=None, base_url="https://b.example", model="gpt-4o-mini")

        config = service.get_ai_config()
        assert config is not None
        assert config["api_key"] == "sk-original-key"
        assert config["base_url"] == "https://b.example"
        assert config["model"] == "gpt-4o-mini"


class TestGetAiConfig:
    """get_ai_config 应正确读取并解密配置"""

    def test_get_returns_none_when_no_config(self, isolated_env: Path):
        """无配置文件时返回 None"""
        service = ConfigService()
        config_file = service.workdir / ".openai_config.json"
        if config_file.exists():
            config_file.unlink()
        assert service.get_ai_config() is None

    def test_get_returns_decrypted_plaintext(self, isolated_env: Path):
        """保存后读取应返回解密明文，磁盘仍为密文"""
        service = ConfigService()
        service.save_ai_config(
            api_key="sk-test-abc", base_url="https://api.test.com", model="gpt-4o"
        )

        config = service.get_ai_config()
        assert config is not None
        assert config["base_url"] == "https://api.test.com"
        assert config["model"] == "gpt-4o"
        assert config["api_key"] == "sk-test-abc", "业务路径应拿到明文"

        raw = json.loads(
            (service.workdir / ".openai_config.json").read_text(encoding="utf-8")
        )
        assert raw["api_key"].startswith("fernet:"), "磁盘应为密文"
        assert raw["api_key"] != "sk-test-abc"


class TestAiConfigDecryptFailed:
    """APP_SECRET_KEY 不匹配时的解密失败边界"""

    def test_get_marks_decrypt_failed(self, isolated_env: Path):
        """解密失败时返回 api_key=None 且 api_key_decrypt_failed=True"""
        service = ConfigService()
        service.save_ai_config(
            api_key="sk-will-break", base_url="https://a.example", model="gpt-4o"
        )
        config_file = service.workdir / ".openai_config.json"
        raw = json.loads(config_file.read_text(encoding="utf-8"))
        assert raw["api_key"].startswith("fernet:")

        with patch(
            "tg_signer.security.decrypt_secret",
            side_effect=Exception("wrong key"),
        ):
            config = service.get_ai_config()

        assert config is not None
        assert config["api_key"] is None
        assert config["api_key_decrypt_failed"] is True
        assert config["base_url"] == "https://a.example"
        assert config["model"] == "gpt-4o"

    def test_save_without_key_keeps_ciphertext_when_decrypt_failed(
        self, isolated_env: Path
    ):
        """解密失败时仅更新 model/base_url 应保留磁盘密文，不要求重填 Key"""
        service = ConfigService()
        service.save_ai_config(
            api_key="sk-original", base_url="https://a.example", model="gpt-4o"
        )
        config_file = service.workdir / ".openai_config.json"
        cipher_before = json.loads(config_file.read_text(encoding="utf-8"))["api_key"]

        with patch(
            "tg_signer.security.decrypt_secret",
            side_effect=Exception("wrong key"),
        ):
            ok = service.save_ai_config(
                api_key=None, base_url="https://b.example", model="gpt-4o-mini"
            )

        assert ok is True
        raw = json.loads(config_file.read_text(encoding="utf-8"))
        assert raw["api_key"] == cipher_before, "密文应原样保留"
        assert raw["base_url"] == "https://b.example"
        assert raw["model"] == "gpt-4o-mini"

    def test_save_new_key_replaces_after_decrypt_failed(self, isolated_env: Path):
        """解密失败后提供新 Key 应重新加密写入"""
        service = ConfigService()
        service.save_ai_config(api_key="sk-old", model="gpt-4o")
        config_file = service.workdir / ".openai_config.json"
        cipher_before = json.loads(config_file.read_text(encoding="utf-8"))["api_key"]

        with patch(
            "tg_signer.security.decrypt_secret",
            side_effect=Exception("wrong key"),
        ):
            # get 路径失败，但 save 传入新明文
            service.save_ai_config(api_key="sk-new-key", model="gpt-4o-mini")

        raw = json.loads(config_file.read_text(encoding="utf-8"))
        assert raw["api_key"] != cipher_before
        assert raw["api_key"].startswith("fernet:")
        # 正常 SECRET 下应可读出新 key
        stored = service.get_ai_config()
        assert stored is not None
        assert stored["api_key"] == "sk-new-key"
        assert stored.get("api_key_decrypt_failed") is False


class TestTestAiConnection:
    """test_ai_connection 必须使用解密后的明文 Key"""

    @pytest.mark.asyncio
    async def test_uses_decrypted_key_not_ciphertext(self, isolated_env: Path):
        """保存加密 Key 后，测试连接应把明文传给 OpenAI 客户端"""
        service = ConfigService()
        service.save_ai_config(
            api_key="sk-live-plaintext-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
        )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "test ok"

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        captured: dict = {}

        def _fake_openai(**kwargs):
            captured.update(kwargs)
            return mock_client

        with patch("openai.AsyncOpenAI", side_effect=_fake_openai):
            result = await service.test_ai_connection()

        assert result["success"] is True
        assert captured.get("api_key") == "sk-live-plaintext-key"
        assert not str(captured.get("api_key", "")).startswith("fernet:")


class TestExportAllConfigs:
    """export_all_configs 应脱敏 AI 配置"""

    def test_export_masks_api_key(self, isolated_env: Path):
        """导出时 AI 配置的 api_key 应被脱敏为 ***MASKED***"""
        service = ConfigService()
        service.save_ai_config(api_key="sk-test-secret", model="gpt-4o")

        exported = json.loads(service.export_all_configs())
        ai_config = exported["settings"]["ai"]

        assert ai_config["api_key"] == "***MASKED***"
        assert ai_config["model"] == "gpt-4o"
        assert exported.get("_meta", {}).get("ai_api_key_masked") is True
        assert "sessions" in exported["_meta"]["excludes"]

    def test_export_handles_no_ai_config(self, isolated_env: Path):
        """无 AI 配置时导出不应报错"""
        service = ConfigService()
        config_file = service.workdir / ".openai_config.json"
        if config_file.exists():
            config_file.unlink()
        exported = json.loads(service.export_all_configs())
        assert exported["settings"]["ai"] is None

    def test_import_skips_masked_api_key(self, isolated_env: Path):
        """导入脱敏密钥不得覆盖服务器已有 api_key"""
        service = ConfigService()
        service.save_ai_config(
            api_key="sk-real-key", base_url="https://api.orig.com", model="gpt-4o"
        )
        payload = {
            "settings": {
                "ai": {
                    "api_key": "***MASKED***",
                    "base_url": "https://api.new.com",
                    "model": "gpt-4o-mini",
                }
            }
        }
        result = service.import_all_configs(json.dumps(payload), overwrite=True)
        assert result["settings_skipped"] >= 1
        assert any("masked" in w.lower() for w in result["warnings"])
        stored = service.get_ai_config()
        assert stored is not None
        # get_ai_config 返回解密后的明文供使用
        assert stored.get("base_url") == "https://api.new.com"
        assert stored.get("model") == "gpt-4o-mini"
        assert stored.get("api_key") == "sk-real-key"


class TestImportAllConfigsValidation:
    """import_all_configs 根节点与字段类型校验"""

    def test_reject_non_object_root(self, isolated_env: Path):
        service = ConfigService()
        result = service.import_all_configs(json.dumps([1, 2, 3]), overwrite=True)
        assert result["errors"]
        assert any("根节点" in e for e in result["errors"])
        assert result.get("signs_imported", 0) == 0

    def test_invalid_signs_type_recorded(self, isolated_env: Path):
        service = ConfigService()
        result = service.import_all_configs(
            json.dumps({"signs": "not-a-dict", "monitors": {}}),
            overwrite=True,
        )
        assert any("signs" in e for e in result["errors"])

    def test_preview_rejects_non_object(self, isolated_env: Path):
        service = ConfigService()
        preview = service.preview_import_all(json.dumps("x"))
        assert preview["errors"]

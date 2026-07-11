"""AI 配置加密存储测试 — 覆盖 config.py 的 save/get/export 路径"""
from __future__ import annotations

import json
from pathlib import Path

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


class TestGetAiConfig:
    """get_ai_config 应正确读取配置"""

    def test_get_returns_none_when_no_config(self, isolated_env: Path):
        """无配置文件时返回 None"""
        service = ConfigService()
        config_file = service.workdir / ".openai_config.json"
        if config_file.exists():
            config_file.unlink()
        assert service.get_ai_config() is None

    def test_get_returns_saved_config(self, isolated_env: Path):
        """保存后能正确读取配置（返回密文）"""
        service = ConfigService()
        service.save_ai_config(api_key="sk-test-abc", base_url="https://api.test.com", model="gpt-4o")

        config = service.get_ai_config()
        assert config is not None
        assert config["base_url"] == "https://api.test.com"
        assert config["model"] == "gpt-4o"
        # api_key 是密文（Fernet 格式），不是明文
        assert config["api_key"].startswith("fernet:"), "应为 Fernet 加密格式"


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

    def test_export_handles_no_ai_config(self, isolated_env: Path):
        """无 AI 配置时导出不应报错"""
        service = ConfigService()
        config_file = service.workdir / ".openai_config.json"
        if config_file.exists():
            config_file.unlink()
        exported = json.loads(service.export_all_configs())
        assert exported["settings"]["ai"] is None

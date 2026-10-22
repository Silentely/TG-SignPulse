import json

import pytest
from pydantic import ValidationError

from backend.services.semantic import JevServiceConfig
from backend.services.semantic.config import JevConfigStore


def test_jev_config_defaults_and_masking(tmp_path):
    store = JevConfigStore(tmp_path)
    cfg = store.load()
    assert cfg.enabled is False
    assert cfg.mode == "official"
    assert cfg.base_url == "https://api.typesafe.ai/v1"
    assert cfg.model == "jev-1.13.0"
    assert cfg.timeout_seconds == 8.0
    assert store.get_sanitized_config()["has_api_key"] is False

    # 保存新密钥
    store.save_patch({"api_key": "sec_key_1234567890", "enabled": True})
    loaded = store.load()
    assert loaded.enabled is True
    assert loaded.api_key == "sec_key_1234567890"

    sanitized = store.get_sanitized_config()
    assert sanitized["has_api_key"] is True
    assert sanitized["api_key_masked"] == "********"
    assert "1234567890" not in sanitized["api_key_masked"]

    # clear_api_key 测试
    store.save_patch({"clear_api_key": True})
    cleared = store.load()
    assert cleared.api_key == ""
    assert store.get_sanitized_config()["has_api_key"] is False


def test_jev_config_backward_compatibility_old_file(tmp_path):
    """向后兼容测试：老文件没有 mode 字段时，缺失字段走默认，且正确推断模式"""
    # 模拟历史老文件，只有旧字段且无 mode
    old_data = {
        "enabled": True,
        "base_url": "https://api.typesafe.ai/v1",
        "model": "jev-1.13.0",
        "timeout_seconds": 5.0,
        "max_concurrency": 2,
    }
    cfg_file = tmp_path / ".jev_config.json"
    cfg_file.write_text(json.dumps(old_data), encoding="utf-8")

    store = JevConfigStore(tmp_path)
    loaded = store.load()
    assert loaded.enabled is True
    assert loaded.mode == "official"
    assert loaded.timeout_seconds == 5.0

    # 老文件中已包含非官方 base_url 的情况
    old_custom = {
        "enabled": True,
        "base_url": "https://api.example.com/v1",
        "model": "jev",
    }
    cfg_file.write_text(json.dumps(old_custom), encoding="utf-8")
    loaded_custom = store.load()
    assert loaded_custom.mode == "custom"
    assert loaded_custom.base_url == "https://api.example.com/v1"
    assert loaded_custom.timeout_seconds == 8.0


def test_jev_config_timeout_and_base_url_validation():
    """测试超时范围校验放宽至 1–30s 及 base_url 规范化验证"""
    cfg = JevServiceConfig(timeout_seconds=30.0)
    assert cfg.timeout_seconds == 30.0

    cfg_min = JevServiceConfig(timeout_seconds=1.0)
    assert cfg_min.timeout_seconds == 1.0

    with pytest.raises(ValidationError):
        JevServiceConfig(timeout_seconds=0.5)

    with pytest.raises(ValidationError):
        JevServiceConfig(timeout_seconds=30.1)

    # 规范化 base_url
    cfg_norm = JevServiceConfig(base_url="https://api.example.com")
    assert cfg_norm.base_url == "https://api.example.com/v1"

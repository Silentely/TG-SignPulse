from backend.services.semantic.config import JevConfigStore


def test_jev_config_defaults_and_masking(tmp_path):
    store = JevConfigStore(tmp_path)
    cfg = store.load()
    assert cfg.enabled is False
    assert cfg.model == "jev-1.13.0"
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

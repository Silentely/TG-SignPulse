"""面板全局设置 → 环境变量回灌测试。

覆盖场景：
- 保存时同步到 env（原有行为）
- 进程重启后从持久化设置重新回灌（新增：修复重启后 AI_VISION_* 等静默回退）
- 无效值跳过、空值不清除已有 env
"""

from __future__ import annotations

from pathlib import Path

from backend.services.config import ConfigService
from backend.services.config_mixins import (
    GLOBAL_SETTINGS_ENV_SYNC,
    apply_global_settings_to_env,
    normalize_global_settings,
)


class TestApplyGlobalSettingsToEnv:
    def test_maps_all_sync_keys(self, isolated_env: Path, monkeypatch):
        import os

        for env_key in GLOBAL_SETTINGS_ENV_SYNC.values():
            monkeypatch.delenv(env_key, raising=False)
        apply_global_settings_to_env(
            {
                "sign_task_execution_timeout": 300,
                "sign_task_account_cooldown": 5,
                "sign_task_flow_retry_attempts": 1,
                "sign_task_history_max_age_days": 7,
                "ai_vision_timeout": 30,
                "ai_vision_retry_attempts": 4,
            }
        )
        assert os.environ["AI_VISION_TIMEOUT"] == "30"
        assert os.environ["AI_VISION_RETRY_ATTEMPTS"] == "4"
        assert os.environ["SIGN_TASK_EXECUTION_TIMEOUT"] == "300"

    def test_invalid_value_skipped(self, isolated_env: Path, monkeypatch):
        import os

        monkeypatch.delenv("AI_VISION_TIMEOUT", raising=False)
        apply_global_settings_to_env({"ai_vision_timeout": "not-a-number"})
        assert "AI_VISION_TIMEOUT" not in os.environ

    def test_empty_value_keeps_existing_env(self, isolated_env: Path, monkeypatch):
        import os

        monkeypatch.setenv("AI_VISION_TIMEOUT", "42")
        apply_global_settings_to_env({"ai_vision_timeout": None})
        assert os.environ["AI_VISION_TIMEOUT"] == "42"

    def test_restart_reinjects_from_persisted_settings(
        self, isolated_env: Path, monkeypatch
    ):
        """模拟重启：保存设置 → 清空 env → 从持久化回灌，值应恢复。"""
        import os

        service = ConfigService()
        service.save_global_settings({"ai_vision_timeout": 30})
        for env_key in GLOBAL_SETTINGS_ENV_SYNC.values():
            monkeypatch.delenv(env_key, raising=False)

        # 重启后：读持久化设置并回灌
        apply_global_settings_to_env(service.get_global_settings())
        assert os.environ["AI_VISION_TIMEOUT"] == "30"

    def test_save_syncs_env_immediately(self, isolated_env: Path, monkeypatch):
        import os

        for env_key in GLOBAL_SETTINGS_ENV_SYNC.values():
            monkeypatch.delenv(env_key, raising=False)
        service = ConfigService()
        service.save_global_settings({"ai_vision_retry_attempts": 6})
        assert os.environ["AI_VISION_RETRY_ATTEMPTS"] == "6"

    def test_string_sync_sets_env_lowercased(self, isolated_env: Path, monkeypatch):
        """字符串型设置（思考度）应小写透传到 env。"""
        import os

        monkeypatch.delenv("AI_VISION_REASONING_EFFORT", raising=False)
        apply_global_settings_to_env({"ai_vision_reasoning_effort": "None"})
        assert os.environ["AI_VISION_REASONING_EFFORT"] == "none"

    def test_string_sync_clears_env_on_empty(self, isolated_env: Path, monkeypatch):
        """思考度重置为默认（None/空）时，应清除 env 停止透传。"""
        import os

        monkeypatch.setenv("AI_VISION_REASONING_EFFORT", "none")
        apply_global_settings_to_env({"ai_vision_reasoning_effort": None})
        assert "AI_VISION_REASONING_EFFORT" not in os.environ

    def test_string_sync_invalid_value_clears_env(self, isolated_env: Path, monkeypatch):
        """apply 侧兜底：非法思考度值不应透传到 env。"""
        import os

        monkeypatch.setenv("AI_VISION_REASONING_EFFORT", "banana")
        apply_global_settings_to_env({"ai_vision_reasoning_effort": "banana"})
        assert "AI_VISION_REASONING_EFFORT" not in os.environ

    def test_save_syncs_reasoning_effort_immediately(
        self, isolated_env: Path, monkeypatch
    ):
        import os

        monkeypatch.delenv("AI_VISION_REASONING_EFFORT", raising=False)
        service = ConfigService()
        service.save_global_settings({"ai_vision_reasoning_effort": "none"})
        assert os.environ["AI_VISION_REASONING_EFFORT"] == "none"

    def test_reasoning_effort_restart_reinjects_and_reset_clears(
        self, isolated_env: Path, monkeypatch
    ):
        """保存 → 重启回灌；重置为默认后重启不应回灌。"""
        import os

        service = ConfigService()
        service.save_global_settings({"ai_vision_reasoning_effort": "high"})
        monkeypatch.delenv("AI_VISION_REASONING_EFFORT", raising=False)
        apply_global_settings_to_env(service.get_global_settings())
        assert os.environ["AI_VISION_REASONING_EFFORT"] == "high"

        # 重置为默认：持久化 None，重启回灌后 env 应被清除
        service.save_global_settings({"ai_vision_reasoning_effort": None})
        apply_global_settings_to_env(service.get_global_settings())
        assert "AI_VISION_REASONING_EFFORT" not in os.environ


class TestNormalizeReasoningEffort:
    """normalize_global_settings 对思考度字段的归一化。"""

    def test_valid_value_lowercased(self):
        normalized = normalize_global_settings({"ai_vision_reasoning_effort": "NONE"})
        assert normalized["ai_vision_reasoning_effort"] == "none"

    def test_empty_value_normalized_to_none(self):
        normalized = normalize_global_settings({"ai_vision_reasoning_effort": ""})
        assert normalized["ai_vision_reasoning_effort"] is None

    def test_invalid_value_dropped(self):
        normalized = normalize_global_settings({"ai_vision_reasoning_effort": "banana"})
        assert "ai_vision_reasoning_effort" not in normalized

    def test_absent_key_untouched(self):
        normalized = normalize_global_settings({"ai_vision_timeout": 30})
        assert "ai_vision_reasoning_effort" not in normalized


class TestGetGlobalProxy:
    """ConfigService.get_global_proxy() 统一入口测试。"""

    def test_returns_none_when_unset(self, isolated_env: Path):
        service = ConfigService()
        assert service.get_global_proxy() is None

    def test_returns_saved_proxy(self, isolated_env: Path):
        service = ConfigService()
        service.save_global_settings({"global_proxy": "socks5://127.0.0.1:1080"})
        assert service.get_global_proxy() == "socks5://127.0.0.1:1080"

    def test_matches_global_settings_value(self, isolated_env: Path):
        service = ConfigService()
        service.save_global_settings({"global_proxy": "http://u:p@h:8080"})
        assert service.get_global_proxy() == service.get_global_settings()["global_proxy"]

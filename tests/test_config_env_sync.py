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

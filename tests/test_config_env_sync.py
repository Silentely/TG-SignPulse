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


def test_legacy_webdav_skip_ssl_migrates_private_address_opt_in():
    normalized = normalize_global_settings(
        {
            "webdav_url": "http://127.0.0.1:8080/dav",
            "webdav_skip_ssl_verify": True,
        }
    )

    assert normalized["webdav_allow_private"] is True


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

    def test_community_gate_inherits_env_before_first_save(
        self, isolated_env: Path, monkeypatch
    ):
        """设置文件尚无该键时继承环境变量；首次保存后以文件为准。"""
        import os

        monkeypatch.setenv("PLUGINS_ALLOW_COMMUNITY", "true")
        service = ConfigService()

        assert service.get_global_settings()["allow_community_plugins"] is True
        apply_global_settings_to_env(service.get_global_settings())
        assert os.environ["PLUGINS_ALLOW_COMMUNITY"] == "true"

        service.save_global_settings({"allow_community_plugins": False})
        monkeypatch.setenv("PLUGINS_ALLOW_COMMUNITY", "true")
        assert service.get_global_settings()["allow_community_plugins"] is False

    def test_priority_file_over_env_over_default_with_source(
        self, isolated_env: Path, monkeypatch
    ):
        """优先级：设置文件显式键 > 环境变量 > 默认 false；source 标识来源。"""
        monkeypatch.delenv("PLUGINS_ALLOW_COMMUNITY", raising=False)
        service = ConfigService()
        gs = service.get_global_settings()
        assert gs["allow_community_plugins"] is False
        assert gs["allow_community_plugins_source"] == "default"

        monkeypatch.setenv("PLUGINS_ALLOW_COMMUNITY", "true")
        service = ConfigService()
        gs = service.get_global_settings()
        assert gs["allow_community_plugins"] is True
        assert gs["allow_community_plugins_source"] == "env"

        # 文件显式键优先于 env，且标记为 file
        service.save_global_settings({"allow_community_plugins": False})
        monkeypatch.setenv("PLUGINS_ALLOW_COMMUNITY", "true")
        gs = ConfigService().get_global_settings()
        assert gs["allow_community_plugins"] is False
        assert gs["allow_community_plugins_source"] == "file"

    def test_unrelated_save_does_not_persist_env_gate_value(
        self, isolated_env: Path, monkeypatch
    ):
        """保存无关字段时，不应把 env 推导的开关值固化进设置文件。"""
        import json

        monkeypatch.setenv("PLUGINS_ALLOW_COMMUNITY", "true")
        service = ConfigService()
        # 文件迄今没有该键：仅保存时间区，不应写入 allow_community_plugins
        service.save_global_settings({"timezone": "Asia/Tokyo"})
        content = json.loads(
            Path(service._get_global_settings_file()).read_text(encoding="utf-8")
        )
        assert "allow_community_plugins" not in content

        # 随后 env 变化应重新生效（环境变量仍是 < 文件）
        monkeypatch.delenv("PLUGINS_ALLOW_COMMUNITY")
        assert service.get_global_settings()["allow_community_plugins"] is False

    def test_explicit_gate_save_persists_when_no_key_prev(
        self, isolated_env: Path, monkeypatch
    ):
        """用户显式保存开关值时，即使文件此前无该键也应落盘。"""
        import json

        monkeypatch.setenv("PLUGINS_ALLOW_COMMUNITY", "true")
        service = ConfigService()
        service.save_global_settings({"allow_community_plugins": False})
        content = json.loads(
            Path(service._get_global_settings_file()).read_text(encoding="utf-8")
        )
        assert content["allow_community_plugins"] is False
        assert service.get_global_settings()["allow_community_plugins_source"] == "file"

    def test_source_field_never_persists_even_on_full_save(
        self, isolated_env: Path, monkeypatch
    ):
        """模拟配置导入：整份设置（含来源字段）回写时，只读来源不得落盘。"""
        import json

        monkeypatch.setenv("PLUGINS_ALLOW_COMMUNITY", "true")
        service = ConfigService()
        full = dict(service.get_global_settings())
        assert full["allow_community_plugins_source"] == "env"
        service.save_global_settings(full)
        content = json.loads(
            Path(service._get_global_settings_file()).read_text(encoding="utf-8")
        )
        assert "allow_community_plugins_source" not in content

    def test_default_source_survives_startup_env_backfill(
        self, isolated_env: Path, monkeypatch
    ):
        """启动回灌不应把默认关闭伪装成「环境变量来源」。"""
        import os

        monkeypatch.delenv("PLUGINS_ALLOW_COMMUNITY", raising=False)
        service = ConfigService()
        assert (
            service.get_global_settings()["allow_community_plugins_source"] == "default"
        )
        apply_global_settings_to_env(service.get_global_settings())
        assert "PLUGINS_ALLOW_COMMUNITY" not in os.environ
        service.invalidate_global_settings_cache()
        assert (
            service.get_global_settings()["allow_community_plugins_source"] == "default"
        )

    def test_export_omits_derived_gate_and_source(
        self, isolated_env: Path, monkeypatch
    ):
        """导出只携带文件显式配置的开关，避免导入时固化 env/默认推导值。"""
        import json

        monkeypatch.setenv("PLUGINS_ALLOW_COMMUNITY", "true")
        service = ConfigService()
        exported = json.loads(service.export_all_configs())
        global_settings = exported["settings"]["global"]
        assert "allow_community_plugins_source" not in global_settings
        assert "allow_community_plugins" not in global_settings

        # 面板显式保存后（来源 file）才随导出迁移
        service.save_global_settings({"allow_community_plugins": False})
        exported = json.loads(service.export_all_configs())
        global_settings = exported["settings"]["global"]
        assert global_settings["allow_community_plugins"] is False
        assert "allow_community_plugins_source" not in global_settings

    def test_save_keeps_external_gate_edit_despite_stale_cache(
        self, isolated_env: Path, monkeypatch
    ):
        """先读并缓存，再外部写入显式关闭键；保存无关字段不得删掉该键。"""
        import json

        monkeypatch.delenv("PLUGINS_ALLOW_COMMUNITY", raising=False)
        service = ConfigService()
        service.get_global_settings()  # 先用默认值填充缓存
        settings_file = Path(service._get_global_settings_file())
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings_file.write_text(
            json.dumps({"allow_community_plugins": False}), encoding="utf-8"
        )

        service.save_global_settings({"log_retention_days": 15})
        content = json.loads(settings_file.read_text(encoding="utf-8"))
        assert content["allow_community_plugins"] is False
        assert content["log_retention_days"] == 15

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

    def test_string_sync_invalid_value_clears_env(
        self, isolated_env: Path, monkeypatch
    ):
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
        assert (
            service.get_global_proxy() == service.get_global_settings()["global_proxy"]
        )

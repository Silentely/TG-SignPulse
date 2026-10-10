# tests/test_flow_routing.py
import os
from unittest.mock import MagicMock, patch

from tg_signer.config import SignChatV3
from tg_signer.core.flow_routing import (
    ENGINE_V3,
    ENGINE_V4,
    resolve_execution_engine,
)
from backend.services.sign_task_config_build import (
    build_sign_task_config,
    resolve_update_field_values,
)


def test_routing_default_fallback():
    # 没有任何覆盖时，返回 v3, default
    with patch.dict(os.environ, {}, clear=True):
        chat = SignChatV3(chat_id=123, actions=[])
        code, name, source = resolve_execution_engine(chat)
        assert code == ENGINE_V3
        assert name == "Classic (v3)"
        assert source == "default"


def test_routing_env_override():
    # 环境变量 USE_PULSEFLOW_ENGINE=1 兜底开启
    with patch.dict(os.environ, {"USE_PULSEFLOW_ENGINE": "1"}):
        chat = SignChatV3(chat_id=123, actions=[])
        code, name, source = resolve_execution_engine(chat)
        assert code == ENGINE_V4
        assert name == "PulseFlow (v4)"
        assert source == "env"


def test_routing_settings_override_beats_env():
    # 全局设置优先于环境变量
    with patch.dict(os.environ, {"USE_PULSEFLOW_ENGINE": "1"}):
        mock_svc = MagicMock()
        mock_svc.get_global_settings.return_value = {"execution_engine": "v3"}
        with patch("backend.services.config.get_config_service", return_value=mock_svc):
            chat = SignChatV3(chat_id=123, actions=[])
            code, name, source = resolve_execution_engine(chat)
            # 全局设置设为 v3，覆盖环境变量的 1
            assert code == ENGINE_V3
            assert name == "Classic (v3)"
            assert source == "settings"


def test_routing_task_override_beats_all():
    # 任务级覆盖优先于一切（全局设置 + 环境变量）
    with patch.dict(os.environ, {"USE_PULSEFLOW_ENGINE": "0"}):
        mock_svc = MagicMock()
        mock_svc.get_global_settings.return_value = {"execution_engine": "v3"}
        with patch("backend.services.config.get_config_service", return_value=mock_svc):
            chat = SignChatV3(chat_id=123, actions=[], execution_engine="v4")
            code, name, source = resolve_execution_engine(chat)
            assert code == ENGINE_V4
            assert name == "PulseFlow (v4)"
            assert source == "task"


def test_routing_task_explicit_v3_override():
    # 任务显式指定 v3 时，即使全局或环境变量开了 v4，也保持 v3
    with patch.dict(os.environ, {"USE_PULSEFLOW_ENGINE": "1"}):
        mock_svc = MagicMock()
        mock_svc.get_global_settings.return_value = {"execution_engine": "v4"}
        with patch("backend.services.config.get_config_service", return_value=mock_svc):
            chat = SignChatV3(chat_id=123, actions=[], execution_engine="v3")
            code, name, source = resolve_execution_engine(chat)
            assert code == ENGINE_V3
            assert name == "Classic (v3)"
            assert source == "task"


def test_task_config_build_preserves_execution_engine():
    # 验证任务配置生成器在创建和更新时正确保留 execution_engine
    cfg = build_sign_task_config(
        account_name="acc1",
        account_names=["acc1"],
        sign_at="08:00",
        chats=[],
        execution_engine="v4",
    )
    assert cfg["execution_engine"] == "v4"

    # 更新合并测试：显式更新为 v3
    updated_fields = resolve_update_field_values(
        cfg,
        execution_engine="v3",
    )
    assert updated_fields["execution_engine"] == "v3"

    # 更新合并测试：传 None 表示不修改沿用旧值
    retained_fields = resolve_update_field_values(
        cfg,
        execution_engine=None,
    )
    assert retained_fields["execution_engine"] == "v4"

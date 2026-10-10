# tests/test_flow_routing.py
import os
from unittest.mock import MagicMock, patch

from tg_signer.config import SignChatV3
from tg_signer.core.flow_routing import (
    ENGINE_V3,
    ENGINE_V4,
    resolve_execution_engine,
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

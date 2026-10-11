# tests/test_flow_routing.py
import os
from unittest.mock import MagicMock, patch

from backend.services.config_mixins import apply_global_settings_to_env
from backend.services.sign_task_config_build import (
    build_sign_task_config,
    resolve_update_field_values,
)
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
        chat = SignChatV3(chat_id=123, actions=[])
        code, name, source = resolve_execution_engine(chat, global_engine="v3")
        assert code == ENGINE_V3
        assert name == "Classic (v3)"
        assert source == "settings"


def test_routing_task_override_beats_all():
    # 任务级覆盖优先于一切（全局设置 + 环境变量）
    with patch.dict(os.environ, {"USE_PULSEFLOW_ENGINE": "0"}):
        chat = SignChatV3(chat_id=123, actions=[], execution_engine="v4")
        code, name, source = resolve_execution_engine(chat, global_engine="v3")
        assert code == ENGINE_V4
        assert name == "PulseFlow (v4)"
        assert source == "task"


def test_routing_task_explicit_v3_override():
    # 任务显式指定 v3 时，即使全局或环境变量开了 v4，也保持 v3
    with patch.dict(os.environ, {"USE_PULSEFLOW_ENGINE": "1"}):
        chat = SignChatV3(chat_id=123, actions=[], execution_engine="v3")
        code, name, source = resolve_execution_engine(chat, global_engine="v4")
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


def test_routing_task_engine_arg_override():
    # 任务级参数覆盖（chat.execution_engine 为 None 时，task_engine 能够生效）
    with patch.dict(os.environ, {}, clear=True):
        chat = SignChatV3(chat_id=123, actions=[])
        code, name, source = resolve_execution_engine(
            chat, task_engine="v4", global_engine="v3"
        )
        assert code == ENGINE_V4
        assert name == "PulseFlow (v4)"
        assert source == "task"


def test_routing_env_boolean_variants():
    for val in ["true", "True", "yes", "YES", "on", "v4"]:
        with patch.dict(os.environ, {"USE_PULSEFLOW_ENGINE": val}):
            code, name, source = resolve_execution_engine(None)
            assert code == ENGINE_V4
            assert source == "env"


def test_global_engine_setting_syncs_through_explicit_environment_boundary():
    with patch.dict(os.environ, {}, clear=True):
        apply_global_settings_to_env({"execution_engine": "v4"})
        code, _, source = resolve_execution_engine(None)
        assert code == ENGINE_V4
        assert source == "settings"

        apply_global_settings_to_env({"execution_engine": "v3"})
        code, _, source = resolve_execution_engine(None)
        assert code == ENGINE_V3
        assert source == "settings"


def test_sign_config_v3_parses_execution_engine():
    from tg_signer.config import SignConfigV3

    cfg = SignConfigV3(
        chats=[SignChatV3(chat_id=123, actions=[])],
        sign_at="08:00",
        execution_engine="v4",
    )
    assert cfg.execution_engine == "v4"


def test_aggregate_tasks_preserves_execution_engine():
    from backend.services.sign_task_group import aggregate_tasks

    tasks = [
        {
            "task_group_id": "grp1",
            "name": "task1",
            "account_name": "acc1",
            "execution_engine": "v4",
        },
        {"task_group_id": "grp1", "name": "task1", "account_name": "acc2"},
    ]
    grouped = aggregate_tasks(
        tasks, normalize_account_names=lambda names, primary: list(names or [primary])
    )
    assert len(grouped) == 1
    assert grouped[0]["execution_engine"] == "v4"


def test_clone_task_preserves_execution_engine():
    from backend.services.sign_tasks import SignTaskService

    svc = SignTaskService.__new__(SignTaskService)
    svc.get_task = MagicMock(
        return_value={
            "name": "task1",
            "sign_at": "08:00",
            "chats": [],
            "account_name": "acc1",
            "execution_engine": "v4",
        }
    )
    svc._find_related_task_infos = MagicMock(return_value=[])
    svc.create_task = MagicMock(return_value={"status": "ok"})

    svc.clone_task("task1", "task1_clone", account_name="acc1")
    svc.create_task.assert_called_once()
    assert svc.create_task.call_args[1].get("execution_engine") == "v4"

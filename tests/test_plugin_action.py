import pytest
from pydantic import ValidationError

from tg_signer.config import (
    ActionT,
    PluginAction,
    SignChatV3,
    SupportAction,
)
from backend.services.sign_task_config_inspect import task_requires_updates
from tg_signer.core.signer_matchers import SignerMatchersMixin
from backend.services.keyword_monitor.continue_actions import describe_continue_action


def test_custom_plugin_enum_and_desc():
    assert SupportAction.CUSTOM_PLUGIN == 99
    assert SupportAction.CUSTOM_PLUGIN.desc == "自定义插件"
    assert SupportAction(99) == SupportAction.CUSTOM_PLUGIN


def test_plugin_action_serialization_and_defaults():
    action = PluginAction(plugin_name="math_solver")
    assert action.action == SupportAction.CUSTOM_PLUGIN
    assert action.plugin_name == "math_solver"
    assert action.mode == "reactive"
    assert action.timeout is None
    assert action.params == {}

    data = (
        action.to_jsonable()
        if hasattr(action, "to_jsonable")
        else (action.model_dump() if hasattr(action, "model_dump") else action.dict())
    )
    assert data["action"] == 99
    assert data["plugin_name"] == "math_solver"
    assert data["mode"] == "reactive"


def test_plugin_action_in_sign_chat_v3():
    chat = SignChatV3(
        chat_id=123456,
        actions=[
            PluginAction(plugin_name="test_active", mode="active"),
        ],
    )
    assert not chat.requires_updates

    reactive_chat = SignChatV3(
        chat_id=123456,
        actions=[
            PluginAction(plugin_name="test_reactive", mode="reactive"),
        ],
    )
    assert reactive_chat.requires_updates


def test_task_requires_updates_with_plugin():
    active_cfg = {"chats": [{"actions": [{"action": 99, "mode": "active"}]}]}
    assert not task_requires_updates(active_cfg)

    reactive_cfg = {"chats": [{"actions": [{"action": 99, "mode": "reactive"}]}]}
    assert task_requires_updates(reactive_cfg)

    default_mode_cfg = {"chats": [{"actions": [{"action": 99}]}]}
    assert task_requires_updates(default_mode_cfg)


def test_describe_action_for_plugin():
    class DummyMatcher(SignerMatchersMixin):
        pass

    matcher = DummyMatcher()
    action = PluginAction(plugin_name="math_solver", mode="reactive")
    assert matcher._describe_action(action) == "自定义插件「math_solver」(reactive)"


def test_describe_continue_action_for_plugin():
    action = {"action": 99, "plugin_name": "math_solver"}
    assert describe_continue_action(action) == "自定义插件: math_solver"

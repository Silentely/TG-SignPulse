# tests/test_flow_inspectors_comprehensive.py
import pytest
from backend.services.sign_task_config_inspect import task_requires_updates
from backend.services.sign_task_crud import _validate_chats_regex_safety
from tg_signer.config import SignChatV3


def test_inspect_detects_wait_event_with_visited_anti_loop():
    subflow_data = {"nodes": {}}
    # 制造逻辑自引用结构测试防环
    subflow_data["nodes"]["sub"] = {"node_type": "subflow", "subflow_graph": subflow_data}
    cfg = {"chats": [{"chat_id": 123, "flow_graph": subflow_data}]}
    # 不应发生 RecursionError
    res = task_requires_updates(cfg)
    assert res is False


def test_inspect_detects_wait_event_node_in_flow_graph():
    cfg = {
        "chats": [
            {
                "chat_id": 123,
                "flow_graph": {
                    "entry_node_id": "w1",
                    "nodes": {
                        "w1": {
                            "id": "w1",
                            "node_type": "wait_event",
                            "next_node_id": "_TERMINAL_COMPLETE",
                        }
                    },
                },
            }
        ]
    }
    assert task_requires_updates(cfg) is True


def test_requires_ai_detects_ai_actions_in_flow_graph():
    chat = SignChatV3(
        chat_id=123,
        flow_graph={
            "entry_node_id": "ai_1",
            "nodes": {
                "ai_1": {
                    "id": "ai_1",
                    "node_type": "action",
                    "action_type": "CHOOSE_OPTION_BY_IMAGE",
                    "params": {"ai_prompt": "choose"},
                    "next_node_id": "_TERMINAL_COMPLETE",
                }
            },
        },
    )
    assert chat.requires_ai is True


def test_requires_updates_detects_wait_event_in_flow_graph():
    chat = SignChatV3(
        chat_id=123,
        flow_graph={
            "entry_node_id": "w1",
            "nodes": {
                "w1": {
                    "id": "w1",
                    "node_type": "wait_event",
                    "next_node_id": "_TERMINAL_COMPLETE",
                }
            },
        },
    )
    assert chat.requires_updates is True


def test_validate_chats_regex_safety_rejects_redos_in_flow_extractor():
    chats = [
        {
            "chat_id": 123,
            "flow_graph": {
                "entry_node_id": "e1",
                "nodes": {
                    "e1": {
                        "id": "e1",
                        "node_type": "extractor",
                        "regex": r"^(\w+\s?)*$",
                        "next_node_id": "_TERMINAL_COMPLETE",
                    }
                },
            },
        }
    ]
    with pytest.raises(ValueError, match="灾难性回溯"):
        _validate_chats_regex_safety(chats)

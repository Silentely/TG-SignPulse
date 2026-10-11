# tests/test_flow_routing_adaptive.py
import pytest
from backend.services.sign_task_crud import _validate_chats_workflow
from tg_signer.config import FlowNodeType, FlowStepConfig, SignChatV3, WorkflowConfigError
from tg_signer.core.flow_routing import resolve_execution_engine


def test_adaptive_routing_promotes_flow_graph_to_v4():
    task_cfg = {
        "execution_engine": None,
        "chats": [{"chat_id": 123, "flow_graph": {"entry_node_id": "s1", "nodes": {}}}],
    }
    engine = resolve_execution_engine(task_cfg)
    assert engine == "v4"


def test_adaptive_routing_rejects_v3_on_flow_graph():
    task_cfg = {
        "execution_engine": "v3",
        "chats": [{"chat_id": 123, "flow_graph": {"entry_node_id": "s1", "nodes": {}}}],
    }
    with pytest.raises(ValueError, match="无法在经典执行引擎上运行"):
        resolve_execution_engine(task_cfg)


def test_adaptive_routing_promotes_flow_step_config_to_v4():
    chat = SignChatV3(
        chat_id=123,
        steps=[
            FlowStepConfig(
                step_id="s1",
                node_type=FlowNodeType.DELAY,
                delay_seconds=2,
            )
        ],
    )
    code, name, source = resolve_execution_engine(chat)
    assert code == "v4"
    assert source == "auto"


def test_adaptive_routing_rejects_v3_on_flow_step_config():
    chat = SignChatV3(
        chat_id=123,
        execution_engine="v3",
        steps=[
            FlowStepConfig(
                step_id="s1",
                node_type=FlowNodeType.DELAY,
                delay_seconds=2,
            )
        ],
    )
    with pytest.raises(ValueError, match="无法在经典执行引擎上运行"):
        resolve_execution_engine(chat)


def test_validate_chats_workflow_rejects_dangling_edge_on_save():
    chats = [
        {
            "chat_id": 123,
            "steps": [
                {"step_id": "s1", "node_type": "delay", "delay_seconds": 1, "next_step_id": "non_exist"}
            ],
        }
    ]
    with pytest.raises(WorkflowConfigError):
        _validate_chats_workflow(chats)


def test_validate_chats_workflow_accepts_valid_flow_graph():
    chats = [
        {
            "chat_id": 123,
            "flow_graph": {
                "entry_node_id": "s1",
                "nodes": {
                    "s1": {
                        "id": "s1",
                        "type": "delay",
                        "delay_seconds": 1,
                        "next_node_id": "_TERMINAL_COMPLETE",
                    }
                },
            },
        }
    ]
    # Should not raise
    _validate_chats_workflow(chats)

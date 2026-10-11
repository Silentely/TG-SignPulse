# tests/test_flow_normalizer_polymorphic.py
import pytest
from tg_signer.config import FlowNodeType, FlowStepConfig, SignChatV3
from tg_signer.core.flow_models import (
    ActionNode,
    ConditionNode,
    DelayNode,
    ExtractorNode,
    WaitEventNode,
)
from tg_signer.core.flow_normalizer import GraphNormalizer


def test_normalizer_injects_chat_id_to_wait_event():
    chat = SignChatV3(
        chat_id=999888,
        steps=[
            FlowStepConfig(
                step_id="w1",
                node_type=FlowNodeType.WAIT_EVENT,
                event_type="NEW_MESSAGE",
                filter_patterns=["code: \\d+"],
                next_step_id="COMPLETE",
            )
        ],
    )
    graph = GraphNormalizer.from_chat(chat)
    node = graph.nodes["w1"]
    assert isinstance(node, WaitEventNode)
    assert node.metadata.get("chat_id") == 999888


def test_action_node_reconstructs_raw_action_for_executor():
    chat = SignChatV3(
        chat_id=123,
        steps=[
            FlowStepConfig(
                step_id="act_1",
                node_type=FlowNodeType.ACTION,
                action_type="SEND_TEXT",
                params={"text": "/checkin"},
                next_step_id="COMPLETE",
            )
        ],
    )
    graph = GraphNormalizer.from_chat(chat)
    node = graph.nodes["act_1"]
    assert isinstance(node, ActionNode)
    assert node.metadata.get("raw_action") is not None
    assert getattr(node.metadata["raw_action"], "text", None) == "/checkin"


def test_normalizer_from_flow_graph_direct():
    chat = SignChatV3(
        chat_id=111,
        flow_graph={
            "entry_node_id": "d1",
            "nodes": {
                "d1": {
                    "id": "d1",
                    "node_type": "delay",
                    "seconds": 3.0,
                    "next_node_id": "_TERMINAL_COMPLETE",
                }
            },
        },
    )
    graph = GraphNormalizer.from_chat(chat)
    assert "d1" in graph.nodes
    assert isinstance(graph.nodes["d1"], DelayNode)
    assert graph.nodes["d1"].seconds == 3.0


def test_normalizer_from_polymorphic_steps_condition_and_extractor():
    chat = SignChatV3(
        chat_id=222,
        steps=[
            FlowStepConfig(
                step_id="step_delay",
                node_type=FlowNodeType.DELAY,
                delay_seconds=2.5,
                next_step_id="step_cond",
            ),
            FlowStepConfig(
                step_id="step_cond",
                node_type=FlowNodeType.CONDITION,
                cases=[{"condition": "vars.ok == true", "target_id": "step_extract"}],
                default_target_id="COMPLETE",
            ),
            FlowStepConfig(
                step_id="step_extract",
                node_type=FlowNodeType.EXTRACTOR,
                source_field="prev.output",
                regex=r"code=(\d+)",
                next_step_id="COMPLETE",
            ),
        ],
    )
    graph = GraphNormalizer.from_chat(chat)
    assert isinstance(graph.nodes["step_delay"], DelayNode)
    assert graph.nodes["step_delay"].seconds == 2.5
    assert isinstance(graph.nodes["step_cond"], ConditionNode)
    assert len(graph.nodes["step_cond"].cases) == 1
    assert isinstance(graph.nodes["step_extract"], ExtractorNode)

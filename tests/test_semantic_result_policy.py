from tg_signer.config import FlowNodeType, FlowStepConfig, SignAction
from tg_signer.core.flow_models import WaitEventNode
from tg_signer.core.flow_normalizer import GraphNormalizer


def test_sign_action_accepts_semantic_result_policy():
    action = SignAction(
        action=1,
        text="/checkin",
        wait_for_reply=True,
        semantic_result={
            "mode": "observe",
            "goal": "确认到账",
            "min_probability": 0.95,
            "min_margin": 0.20,
        },
    )
    assert action.semantic_result is not None
    assert action.semantic_result.get("mode") == "observe"
    assert action.semantic_result.get("goal") == "确认到账"


def test_flow_step_config_semantic_result_normalizes_to_wait_event():
    step = FlowStepConfig(
        step_id="step_1",
        node_type=FlowNodeType.WAIT_EVENT,
        event_type="NEW_MESSAGE",
        semantic_result={
            "mode": "observe",
            "goal": "确认到账",
        },
    )
    normalizer = GraphNormalizer()
    from tg_signer.config import SignChatV3

    chat = SignChatV3(chat_id=123, steps=[step])
    graph = normalizer.from_chat(chat)
    wait_node = graph.nodes.get("step_1")
    assert isinstance(wait_node, WaitEventNode)
    assert wait_node.semantic_result is not None
    assert wait_node.semantic_result.get("goal") == "确认到账"

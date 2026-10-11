from unittest.mock import MagicMock

from tg_signer.config import ClickKeyboardByTextAction, SendTextAction, SignChatV3
from tg_signer.core.flow_compat import FlowCompatibilityBridge
from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_models import NodeStatus, StepOutcome
from tg_signer.core.flow_normalizer import GraphNormalizer


def test_bridge_builds_legacy_template_aliases_from_scoped_context():
    chat = SignChatV3(chat_id=123, actions=[SendTextAction(text="/next")])
    runner = MagicMock()
    runner.context.last_received_text = "收到验证码"
    context = ScopedFlowContext(account={"name": "acc"})
    context.record_step_outcome(
        StepOutcome(
            node_id="step_0",
            status=NodeStatus.SUCCESS,
            output_text="Token: ABC",
            extracted_vars={"token": "ABC"},
        )
    )

    scope = FlowCompatibilityBridge(runner, chat).build_template_context(
        context, MagicMock(username="alice"), "acc"
    )

    assert scope["steps"]["step_0"]["token"] == "ABC"
    assert scope["step"]["step_0"]["output"] == "Token: ABC"
    assert scope["prev_output"] == "Token: ABC"
    assert scope["last_message"] == "收到验证码"


def test_bridge_ignores_stale_legacy_last_output_for_skip_matching():
    chat = SignChatV3(chat_id=123, actions=[])
    runner = MagicMock()
    runner.context.last_output = "STALE previous chat"
    runner.context.last_received_text = "new message"
    context = ScopedFlowContext()

    bridge = FlowCompatibilityBridge(runner, chat)

    assert bridge.skip_match_source(context) == "new message"


def test_bridge_consumes_terminal_flag_once():
    chat = SignChatV3(chat_id=123, actions=[])
    runner = MagicMock()
    runner.context.stop_after_current_action = True
    bridge = FlowCompatibilityBridge(runner, chat)

    assert bridge.consume_matched_terminal() is True
    assert runner.context.stop_after_current_action is False
    assert bridge.consume_matched_terminal() is False


def test_bridge_resolves_next_action_from_graph():
    chat = SignChatV3(
        chat_id=123,
        actions=[
            SendTextAction(text="/start"),
            ClickKeyboardByTextAction(text="确认"),
        ],
    )
    graph = GraphNormalizer.from_chat(chat)
    bridge = FlowCompatibilityBridge(MagicMock(), chat, graph)

    next_action = bridge.resolve_next_action(graph.nodes["step_0"])

    assert next_action.text == "确认"

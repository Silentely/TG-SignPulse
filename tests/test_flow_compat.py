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
    assert scope["step"][1]["output"] == "Token: ABC"
    assert scope["step"]["1"]["output"] == "Token: ABC"
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

    # 验证 check_terminal_stop 只读不消费
    assert bridge.check_terminal_stop() is True
    assert runner.context.stop_after_current_action is True

    # 验证 consume_matched_terminal / consume_stop_signal 消费一次后重置
    assert bridge.consume_matched_terminal() is True
    assert runner.context.stop_after_current_action is False
    assert bridge.consume_matched_terminal() is False
    assert bridge.check_terminal_stop() is False


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


def test_bridge_discrete_snapshot_reading():
    chat = SignChatV3(chat_id=888, actions=[])
    runner = MagicMock()
    msg_mock = MagicMock(text="bot reply 1")
    runner.context.last_received_text = "welcome user"
    runner.context.stop_reason = "already signed in"
    runner.context.last_callback_answer = "button clicked"
    runner.context.last_output = "previous result"
    runner.context.chat_messages = {
        888: {1: msg_mock},
        999: {2: MagicMock(text="other")},
    }

    bridge = FlowCompatibilityBridge(runner, chat)

    assert bridge.get_last_received_text() == "welcome user"
    assert bridge.get_stop_reason() == "already signed in"
    assert bridge.get_last_callback_answer() == "button clicked"
    assert bridge.get_last_output() == "previous result"

    # 测试会话消息快照与只读性
    msgs_888 = bridge.get_chat_messages(888)
    assert 1 in msgs_888
    assert msgs_888[1].text == "bot reply 1"

    # 默认 chat_id 测试
    default_msgs = bridge.get_chat_messages()
    assert 1 in default_msgs

    # 检查浅拷贝独立性
    msgs_888[99] = "temporary"
    assert 99 not in runner.context.chat_messages[888]


def test_bridge_side_effect_and_output_commit():
    chat = SignChatV3(chat_id=123, actions=[])
    runner = MagicMock()
    runner.context.pulseflow_side_effect_started = False
    runner.context.last_output = ""

    bridge = FlowCompatibilityBridge(runner, chat)

    bridge.mark_side_effect_started()
    assert runner.context.pulseflow_side_effect_started is True

    bridge.set_last_output("new output text")
    assert runner.context.last_output == "new output text"
    assert bridge.get_last_output() == "new output text"


def test_bridge_action_context_governance():
    chat = SignChatV3(chat_id=123, actions=[])
    runner = MagicMock()
    action = SendTextAction(text="/ping")

    bridge = FlowCompatibilityBridge(runner, chat)

    bridge.set_current_action_context(2, 5, action)
    runner._set_current_action_context.assert_called_once_with(2, 5, action)

    bridge.clear_current_action_context()
    runner._clear_current_action_context.assert_called_once()


def test_bridge_graceful_handling_null_or_missing_context():
    chat = SignChatV3(chat_id=123, actions=[])
    # runner 没有 context 属性
    runner_no_ctx = object()
    bridge = FlowCompatibilityBridge(runner_no_ctx, chat)

    assert bridge.runner_context is None
    assert bridge.get_last_received_text() == ""
    assert bridge.get_chat_messages() == {}
    assert bridge.get_stop_reason() == ""
    assert bridge.get_last_callback_answer() == ""
    assert bridge.get_last_output() == ""
    assert bridge.check_terminal_stop() is False
    assert bridge.consume_stop_signal() is False

    # 提交操作不抛出异常
    bridge.mark_side_effect_started()
    bridge.set_last_output("ignored")
    bridge.set_current_action_context(1, 1, None)
    bridge.clear_current_action_context()
    bridge.reset_before_action()

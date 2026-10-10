# tests/test_flow_models.py
import pytest
from tg_signer.core.flow_models import (
    TERMINAL_COMPLETE_ID,
    TERMINAL_FAIL_ID,
    NodeType,
    TerminalPolicy,
    NodeStatus,
    FlowSignal,
    StepOutcome,
    RetryPolicy,
    LoopPolicy,
    ActionNode,
    ConditionNode,
    ExtractorNode,
    ExecutionGraph,
)

def test_flow_node_types_and_defaults():
    action_node = ActionNode(
        id="step_send",
        name="发送打卡指令",
        action_type="SEND_TEXT",
        params={"text": "/checkin"},
        next_node_id="step_wait",
        retry_policy=RetryPolicy(max_attempts=2, backoff_seconds=1.5),
        loop_policy=LoopPolicy(allow_loop=True, max_visits=3),
    )
    assert action_node.node_type == NodeType.ACTION
    assert action_node.terminal_policy == TerminalPolicy.IGNORE
    assert action_node.retry_policy.max_attempts == 2
    assert action_node.loop_policy.max_visits == 3
    assert action_node.params["text"] == "/checkin"

def test_condition_and_extractor_nodes():
    cond_node = ConditionNode(
        id="check_balance",
        cases=[
            {"condition": "prev.output contains '成功'", "target_id": "step_done"},
            {"condition": "prev.output contains '不足'", "target_id": "step_alert"},
        ],
        default_target_id=TERMINAL_FAIL_ID,
    )
    assert cond_node.node_type == NodeType.CONDITION
    assert len(cond_node.cases) == 2
    assert cond_node.default_target_id == TERMINAL_FAIL_ID

    ext_node = ExtractorNode(
        id="ext_code",
        regex=r"验证码：(?P<code>\d+)",
        export_vars={"code": "auth_code"},
        next_node_id="step_next",
    )
    assert ext_node.node_type == NodeType.EXTRACTOR
    assert ext_node.regex == r"验证码：(?P<code>\d+)"

def test_step_outcome_defaults():
    outcome = StepOutcome(
        node_id="step_1",
        status=NodeStatus.SUCCESS,
        output_text="签到成功",
        matched_terminal=True,
    )
    assert outcome.signal == FlowSignal.PROCEED
    assert outcome.matched_terminal is True
    assert outcome.extracted_vars == {}
    assert outcome.error is None

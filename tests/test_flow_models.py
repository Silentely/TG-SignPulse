# tests/test_flow_models.py
from tg_signer.core.flow_models import (
    TERMINAL_COMPLETE_ID,
    TERMINAL_FAIL_ID,
    ActionNode,
    ConditionNode,
    DelayNode,
    ExecutionGraph,
    ExtractorNode,
    FlowSignal,
    LoopPolicy,
    NodeStatus,
    NodeType,
    RetryPolicy,
    StepOutcome,
    SubflowNode,
    TerminalPolicy,
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


def test_execution_graph_from_dict_polymorphic():
    data = {
        "entry_node_id": "step_delay",
        "nodes": {
            "step_delay": {
                "node_type": "delay",
                "seconds": 2.5,
                "next_node_id": "step_action",
            },
            "step_action": {
                "node_type": "action",
                "action_type": "SEND_TEXT",
                "params": {"text": "/ping"},
                "next_node_id": "step_subflow",
            },
            "step_subflow": {
                "node_type": "subflow",
                "subflow_graph": {
                    "entry_node_id": "sub_act",
                    "nodes": {
                        "sub_act": {
                            "node_type": "action",
                            "action_type": "SEND_TEXT",
                            "params": {"text": "/inner"},
                            "next_node_id": TERMINAL_COMPLETE_ID,
                        }
                    },
                },
                "next_node_id": TERMINAL_COMPLETE_ID,
            },
        },
    }
    graph = ExecutionGraph.from_dict(data)
    assert graph.entry_node_id == "step_delay"
    assert isinstance(graph.nodes["step_delay"], DelayNode)
    assert graph.nodes["step_delay"].seconds == 2.5
    assert isinstance(graph.nodes["step_action"], ActionNode)
    assert isinstance(graph.nodes["step_subflow"], SubflowNode)
    assert isinstance(graph.nodes["step_subflow"].subflow_graph, ExecutionGraph)
    assert graph.nodes["step_subflow"].subflow_graph.entry_node_id == "sub_act"

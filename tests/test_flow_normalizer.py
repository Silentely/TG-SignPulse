# tests/test_flow_normalizer.py
import pytest
from tg_signer.config import (
    SignChatV3,
    SendTextAction,
    ClickKeyboardByTextAction,
    ChooseOptionByImageAction,
    WorkflowStepConfig,
)
from tg_signer.core.flow_models import (
    TERMINAL_COMPLETE_ID,
    TERMINAL_FAIL_ID,
    NodeType,
    TerminalPolicy,
)
from tg_signer.core.flow_normalizer import GraphNormalizer, GraphValidationError

def test_normalize_legacy_actions_with_exact_fields():
    # 严格对齐真实模型字段：ChooseOptionByImageAction 只有 ai_prompt 字段
    chat = SignChatV3(
        chat_id=12345,
        actions=[
            SendTextAction(text="/start", delay="2.0", skip_if_matched="已开启"),
            ChooseOptionByImageAction(ai_prompt="识别图片选项"),
            ClickKeyboardByTextAction(text="每日打卡", stop_flow_on_terminal=True),
        ],
    )
    graph = GraphNormalizer.from_chat(chat)
    assert graph.entry_node_id == "step_0"
    assert len(graph.nodes) == 3
    
    node0 = graph.nodes["step_0"]
    assert node0.next_node_id == "step_1"
    assert node0.params["text"] == "/start"
    assert str(node0.params["delay"]) == "2.0"
    assert node0.params["skip_if_matched"] == "已开启"

    node1 = graph.nodes["step_1"]
    assert node1.action_type == "CHOOSE_OPTION_BY_IMAGE"
    assert node1.params["ai_prompt"] == "识别图片选项"

    node2 = graph.nodes["step_2"]
    assert node2.next_node_id == TERMINAL_COMPLETE_ID
    assert node2.terminal_policy == TerminalPolicy.STOP_FLOW

def test_normalize_workflow_steps_with_config_dict():
    # 严格对齐真实模型字段：WorkflowStepConfig 使用 config 字典
    chat = SignChatV3(
        chat_id=12345,
        initial_step_id="step_a",
        steps=[
            WorkflowStepConfig(
                step_id="step_a",
                action_type=1,
                config={"text": "/start"},
                next_step_id="step_b",
                on_failure_step_id="FAIL",
                allow_loop=True,
                max_retries=2,
            ),
            WorkflowStepConfig(
                step_id="step_b",
                action_type=3,
                config={"text": "确认"},
                next_step_id="COMPLETE",
            ),
        ],
    )
    graph = GraphNormalizer.from_chat(chat)
    assert graph.entry_node_id == "step_a"
    node_a = graph.nodes["step_a"]
    assert node_a.next_node_id == "step_b"
    assert node_a.on_failure_node_id == TERMINAL_FAIL_ID
    assert node_a.loop_policy.allow_loop is True
    assert node_a.loop_policy.max_visits == 3

def test_graph_validator_detects_dangling_nodes():
    # 验证静态拓扑校验器检测悬空目标节点
    from tg_signer.core.flow_models import ExecutionGraph, ActionNode
    bad_graph = ExecutionGraph(
        entry_node_id="s1",
        nodes={"s1": ActionNode(id="s1", next_node_id="s_missing")},
    )
    with pytest.raises(GraphValidationError, match="指向不存在的节点"):
        GraphNormalizer.validate_graph(bad_graph)

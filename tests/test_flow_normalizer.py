# tests/test_flow_normalizer.py
import pytest

from tg_signer.config import (
    ChooseOptionByImageAction,
    ClickKeyboardByTextAction,
    PluginAction,
    SendDiceAction,
    SendTextAction,
    SignChatV3,
    WorkflowStepConfig,
)
from tg_signer.core.flow_models import (
    TERMINAL_COMPLETE_ID,
    TERMINAL_FAIL_ID,
    ActionNode,
    ConditionNode,
    ExecutionGraph,
    LoopPolicy,
    TerminalPolicy,
)
from tg_signer.core.flow_normalizer import GraphNormalizer, GraphValidationError


def test_normalize_legacy_actions_with_exact_fields():
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


def test_normalize_dice_and_plugin_actions_uses_current_model_fields():
    chat = SignChatV3(
        chat_id=12345,
        actions=[
            SendDiceAction(dice="🎲"),
            PluginAction(plugin_name="daily_bonus", mode="active", timeout=3.0),
        ],
    )

    graph = GraphNormalizer.from_chat(chat)

    assert graph.nodes["step_0"].params["dice"] == "🎲"
    assert graph.nodes["step_1"].params["plugin_name"] == "daily_bonus"
    assert graph.nodes["step_1"].params["mode"] == "active"
    assert graph.nodes["step_1"].params["timeout"] == 3.0


def test_normalize_empty_actions_rejects_invalid_v4_graph():
    with pytest.raises(GraphValidationError, match="没有配置任何可执行动作"):
        GraphNormalizer.from_chat(SignChatV3(chat_id=12345, actions=[]))


def test_normalize_workflow_steps_with_config_dict():
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
    bad_graph = ExecutionGraph(
        entry_node_id="s1",
        nodes={"s1": ActionNode(id="s1", next_node_id="s_missing")},
    )
    with pytest.raises(GraphValidationError, match="指向不存在的节点"):
        GraphNormalizer.validate_graph(bad_graph)


def test_graph_validator_detects_dangling_branch_and_condition_targets():
    # 1. terminal_branch_target 悬空
    bad_branch_graph = ExecutionGraph(
        entry_node_id="s1",
        nodes={
            "s1": ActionNode(
                id="s1",
                next_node_id=TERMINAL_COMPLETE_ID,
                terminal_branch_target="s_missing",
            )
        },
    )
    with pytest.raises(
        GraphValidationError,
        match="terminal_branch_target 's_missing' 指向不存在的节点",
    ):
        GraphNormalizer.validate_graph(bad_branch_graph)

    # 2. ConditionNode 分支目标悬空
    bad_cond_graph = ExecutionGraph(
        entry_node_id="c1",
        nodes={
            "c1": ConditionNode(
                id="c1",
                cases=[{"condition": "x > 1", "target_id": "c_missing"}],
                default_target_id=TERMINAL_COMPLETE_ID,
            )
        },
    )
    with pytest.raises(
        GraphValidationError, match="条件节点 c1 的目标 'c_missing' 指向不存在的节点"
    ):
        GraphNormalizer.validate_graph(bad_cond_graph)


def test_graph_validator_detects_unallowed_cycle():
    # 检测未声明 allow_loop 的自环或环路
    cycle_graph = ExecutionGraph(
        entry_node_id="s1",
        nodes={
            "s1": ActionNode(id="s1", next_node_id="s2"),
            "s2": ActionNode(
                id="s2", next_node_id="s1", loop_policy=LoopPolicy(allow_loop=False)
            ),
        },
    )
    with pytest.raises(
        GraphValidationError, match="检测到未允许的环路: s1 -> s2 -> s1"
    ):
        GraphNormalizer.validate_graph(cycle_graph)


def test_graph_validator_accepts_allowed_cycle():
    # 环路上的每个节点都必须声明可循环，才能与运行时访问上限一致
    allowed_cycle_graph = ExecutionGraph(
        entry_node_id="s1",
        nodes={
            "s1": ActionNode(
                id="s1",
                next_node_id="s2",
                loop_policy=LoopPolicy(allow_loop=True, max_visits=3),
            ),
            "s2": ActionNode(
                id="s2",
                next_node_id="s1",
                loop_policy=LoopPolicy(allow_loop=True, max_visits=3),
            ),
        },
    )
    # 不应抛出异常
    GraphNormalizer.validate_graph(allowed_cycle_graph)

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


def test_graph_validator_detects_dangling_error_handler():
    bad_err_graph = ExecutionGraph(
        entry_node_id="s1",
        error_handler_node_id="missing_err_handler",
        nodes={
            "s1": ActionNode(
                id="s1",
                next_node_id=TERMINAL_COMPLETE_ID,
            )
        },
    )
    with pytest.raises(
        GraphValidationError,
        match="全局错误处理节点 error_handler_node_id 'missing_err_handler' 指向不存在的节点",
    ):
        GraphNormalizer.validate_graph(bad_err_graph)


def test_normalize_workflow_steps_node_guards():
    chat = SignChatV3(
        chat_id=12345,
        initial_step_id="step_guarded",
        steps=[
            WorkflowStepConfig(
                step_id="step_guarded",
                action_type=1,
                config={
                    "text": "/hello",
                    "run_if": "vars.enabled == true",
                    "skip_if": "vars.balance < 10",
                },
                next_step_id="COMPLETE",
            )
        ],
    )
    graph = GraphNormalizer.from_chat(chat)
    node = graph.nodes["step_guarded"]
    assert node.run_if == "vars.enabled == true"
    assert node.skip_if == "vars.balance < 10"


def test_graph_validator_detects_dangling_resume_node():
    bad_resume_graph = ExecutionGraph(
        entry_node_id="s1",
        resume_from_node_id="s_nonexistent",
        nodes={
            "s1": ActionNode(
                id="s1",
                next_node_id=TERMINAL_COMPLETE_ID,
            )
        },
    )
    with pytest.raises(
        GraphValidationError,
        match="断点恢复节点 resume_from_node_id 's_nonexistent' 不在图节点中",
    ):
        GraphNormalizer.validate_graph(bad_resume_graph)


def test_graph_normalizer_to_mermaid():
    graph = ExecutionGraph(
        entry_node_id="step_1",
        error_handler_node_id="step_err",
        nodes={
            "step_1": ActionNode(
                id="step_1",
                name="发送签到",
                next_node_id="step_cond",
                on_failure_node_id="step_err",
            ),
            "step_cond": ConditionNode(
                id="step_cond",
                cases=[{"condition": "vars.ok == true", "target_id": "COMPLETE"}],
                default_target_id="FAIL",
            ),
            "step_err": ActionNode(
                id="step_err",
                next_node_id=TERMINAL_FAIL_ID,
            ),
        },
    )

    mermaid_str = GraphNormalizer.to_mermaid(graph)
    assert "graph TD" in mermaid_str
    assert "Start([开始]) --> step_1" in mermaid_str
    assert "发送签到 [action]" in mermaid_str
    assert "step_1 -->|next| step_cond" in mermaid_str
    assert "step_1 -.->|on_failure| step_err" in mermaid_str
    assert "vars.ok == true" in mermaid_str
    assert "ErrorHandler[全局降级错误处理] -.-> step_err" in mermaid_str


def test_normalize_ai_action_timeout_adaptation():
    """验证普通动作使用默认超时（25s），AI 视觉动作自适应放宽超时（60s），显式配置优先。"""
    chat = SignChatV3(
        chat_id=12345,
        actions=[
            SendTextAction(text="/checkin"),
            ChooseOptionByImageAction(ai_prompt="识别图片"),
            PluginAction(plugin_name="custom", mode="active", timeout=90.0),
        ],
    )
    graph = GraphNormalizer.from_chat(chat)
    node0 = graph.nodes["step_0"]
    assert node0.timeout_seconds == 25.0

    node1 = graph.nodes["step_1"]
    assert node1.timeout_seconds >= 60.0

    node2 = graph.nodes["step_2"]
    assert node2.timeout_seconds == 90.0


def test_execution_graph_compile_non_mutating_input_dict():
    """验证 ExecutionGraph.compile 对传入的原始字典具有严格的非破坏性（不变异）。"""
    import copy

    source_dict = {
        "chat_id": 99999,
        "name": "non_mutating_test",
        "flow_graph": {
            "entry_node_id": "wait_step",
            "nodes": {
                "wait_step": {
                    "node_type": "wait_event",
                    "event_type": "NEW_MESSAGE",
                    "filter_patterns": [r"code: (\d+)"],
                    "next_node_id": "act_step",
                    "metadata": {"custom_meta": 123},
                },
                "act_step": {
                    "node_type": "action",
                    "action_type": "SEND_TEXT",
                    "params": {"text": "done"},
                    "next_node_id": "_TERMINAL_COMPLETE",
                },
            },
        },
    }

    snapshot = copy.deepcopy(source_dict)
    graph = ExecutionGraph.compile(source_dict)

    # 1. 编译结果正确生成
    assert isinstance(graph, ExecutionGraph)
    assert graph.entry_node_id == "wait_step"
    assert len(graph.nodes) == 2
    # 2. 编译出的节点元数据包含了自动注入的上下文
    assert graph.nodes["wait_step"].metadata.get("chat_id") == 99999
    # 3. 严格断言调用方的原始字典未被任何原地变异
    assert source_dict == snapshot
    assert "chat_id" not in source_dict["flow_graph"]["nodes"]["wait_step"]["metadata"]


def test_execution_graph_compile_non_mutating_chat_flow_graph():
    """验证以 SignChatV3 编译时，其内部的 flow_graph 字典对象同样不被变异。"""
    import copy

    flow_graph_dict = {
        "entry_node_id": "wait_step",
        "nodes": {
            "wait_step": {
                "node_type": "wait_event",
                "event_type": "NEW_MESSAGE",
                "filter_patterns": ["hello"],
                "next_node_id": "_TERMINAL_COMPLETE",
                "metadata": {"init": True},
            }
        },
    }
    chat = SignChatV3(
        chat_id=88888,
        name="chat_with_fg",
        flow_graph=copy.deepcopy(flow_graph_dict),
    )

    fg_snapshot = copy.deepcopy(chat.flow_graph)
    graph = ExecutionGraph.compile(chat)

    assert isinstance(graph, ExecutionGraph)
    assert graph.nodes["wait_step"].metadata.get("chat_id") == 88888
    # 原始 chat.flow_graph 保持纯净未被修改
    assert chat.flow_graph == fg_snapshot
    assert "chat_id" not in chat.flow_graph["nodes"]["wait_step"]["metadata"]


def test_execution_graph_compile_cross_chat_budget_tracking():
    """验证跨 chat 编译时，节点预算累积与超限熔断机制。"""
    chat1 = SignChatV3(
        chat_id=101,
        actions=[
            SendTextAction(text="1"),
            SendTextAction(text="2"),
        ],
    )
    chat2 = SignChatV3(
        chat_id=102,
        actions=[
            SendTextAction(text="3"),
            SendTextAction(text="4"),
        ],
    )

    budget = {"current_total_nodes": 0, "max_total_task_nodes": 5}
    g1 = ExecutionGraph.compile(chat1, budget=budget)
    assert len(g1.nodes) == 2
    assert budget["current_total_nodes"] == 2
    assert budget["total_nodes"] == 2

    g2 = ExecutionGraph.compile(chat2, budget=budget)
    assert len(g2.nodes) == 2
    assert budget["current_total_nodes"] == 4
    assert budget["total_nodes"] == 4

    # 第三个 chat 包含 2 个节点，4 + 2 = 6 > 5，预期触发 GraphValidationError
    chat3 = SignChatV3(
        chat_id=103,
        actions=[
            SendTextAction(text="5"),
            SendTextAction(text="6"),
        ],
    )
    with pytest.raises(GraphValidationError, match="全任务流程图节点总数超过上限"):
        ExecutionGraph.compile(chat3, budget=budget)


def test_execution_graph_compile_collects_warnings():
    """验证 ExecutionGraph.compile 收集孤立不可达节点告警。"""
    fg_data = {
        "entry_node_id": "start",
        "nodes": {
            "start": {
                "node_type": "action",
                "action_type": "SEND_TEXT",
                "params": {"text": "hi"},
                "next_node_id": "_TERMINAL_COMPLETE",
            },
            "orphan_step": {
                "node_type": "action",
                "action_type": "SEND_TEXT",
                "params": {"text": "unreachable"},
                "next_node_id": "_TERMINAL_COMPLETE",
            },
        },
    }
    warn_list = []
    graph = ExecutionGraph.compile(fg_data, warnings=warn_list)
    assert len(graph.nodes) == 2
    assert len(warn_list) == 1
    assert "orphan_step" in warn_list[0]
    assert "不可达" in warn_list[0]


def test_execution_graph_compile_polymorphic_sources():
    """验证 ExecutionGraph.compile 支持 SignChatV3、字典、直接 ExecutionGraph 以及拒绝非法类型。"""
    # 1. 直接 ExecutionGraph 对象
    base_graph = ExecutionGraph(
        entry_node_id="n1",
        nodes={"n1": ActionNode(id="n1", next_node_id="_TERMINAL_COMPLETE")},
    )
    compiled_1 = ExecutionGraph.compile(base_graph)
    assert compiled_1.entry_node_id == "n1"
    assert compiled_1 is not base_graph  # 拷贝副本

    # 2. 纯 flow_graph 格式 dict
    fg_dict = {
        "entry_node_id": "n1",
        "nodes": {
            "n1": {
                "node_type": "action",
                "action_type": "SEND_TEXT",
                "params": {"text": "hi"},
                "next_node_id": "_TERMINAL_COMPLETE",
            }
        },
    }
    compiled_2 = ExecutionGraph.compile(fg_dict)
    assert compiled_2.entry_node_id == "n1"

    # 3. SignChatV3 dict
    chat_dict = {
        "chat_id": 1234,
        "actions": [{"action": "SEND_TEXT", "text": "foo"}],
    }
    compiled_3 = ExecutionGraph.compile(chat_dict)
    assert compiled_3.entry_node_id == "step_0"

    # 4. 非法类型拒绝
    with pytest.raises(GraphValidationError, match="无法从类型 int 编译执行图"):
        ExecutionGraph.compile(12345)

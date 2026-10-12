# tests/test_flow_validation_full_graph.py
import pytest

from tg_signer.core.flow_models import (
    MAX_NODES_PER_GRAPH,
    ActionNode,
    ExecutionGraph,
)
from tg_signer.core.flow_normalizer import GraphNormalizer, GraphValidationError


def test_reject_unreachable_dead_cycle():
    # entry 正常指向完成，但存在孤立的死循环 dead_1 <-> dead_2
    nodes = {
        "entry": ActionNode(id="entry", next_node_id="_TERMINAL_COMPLETE"),
        "dead_1": ActionNode(id="dead_1", next_node_id="dead_2"),
        "dead_2": ActionNode(id="dead_2", next_node_id="dead_1"),
    }
    graph = ExecutionGraph(entry_node_id="entry", nodes=nodes)
    with pytest.raises(GraphValidationError, match="检测到未允许的环路"):
        GraphNormalizer.validate_graph(graph)


def test_reject_exceeding_max_nodes_per_graph():
    nodes = {}
    for i in range(MAX_NODES_PER_GRAPH + 1):
        nid = f"step_{i}"
        nxt = f"step_{i + 1}" if i < MAX_NODES_PER_GRAPH else "_TERMINAL_COMPLETE"
        nodes[nid] = ActionNode(id=nid, next_node_id=nxt)
    graph = ExecutionGraph(entry_node_id="step_0", nodes=nodes)
    with pytest.raises(GraphValidationError, match="单图节点总数超过上限"):
        GraphNormalizer.validate_graph(graph)


def test_to_mermaid_escapes_special_characters():
    nodes = {
        "s1": ActionNode(
            id="s1",
            name='User "Inject" <script>',
            next_node_id="_TERMINAL_COMPLETE",
        )
    }
    graph = ExecutionGraph(entry_node_id="s1", nodes=nodes)
    mermaid = GraphNormalizer.to_mermaid(graph)
    assert "<script>" not in mermaid
    assert "&quot;" in mermaid or "#quot;" in mermaid


def test_to_mermaid_escapes_condition_expressions():
    from tg_signer.core.flow_models import ConditionNode

    nodes = {
        "cond_1": ConditionNode(
            id="cond_1",
            cases=[
                {"condition": 'vars.text == "hello"', "target_id": "target_a"},
                {"condition": "<script>alert(1)</script>", "target_id": "target_b"},
            ],
            default_target_id="_TERMINAL_COMPLETE",
        ),
        "target_a": ActionNode(id="target_a", next_node_id="_TERMINAL_COMPLETE"),
        "target_b": ActionNode(id="target_b", next_node_id="_TERMINAL_COMPLETE"),
    }
    graph = ExecutionGraph(entry_node_id="cond_1", nodes=nodes)
    mermaid = GraphNormalizer.to_mermaid(graph)
    assert "<script>" not in mermaid
    assert "&lt;script&gt;" in mermaid
    assert "&quot;hello&quot;" in mermaid


def test_reject_exceeding_max_total_task_nodes_in_subflows():
    from tg_signer.core.flow_models import SubflowNode

    # 构造两个合法子图，每个节点数 40 (< 50)，主图 40，再加一个 40，总共 160 > 150
    def make_subgraph(prefix: str, count: int = 40) -> ExecutionGraph:
        s_nodes = {}
        for i in range(count):
            sid = f"{prefix}_{i}"
            nxt = f"{prefix}_{i + 1}" if i < count - 1 else "_TERMINAL_COMPLETE"
            s_nodes[sid] = ActionNode(id=sid, next_node_id=nxt)
        return ExecutionGraph(entry_node_id=f"{prefix}_0", nodes=s_nodes)

    sub1 = make_subgraph("sub1", 45)
    sub2 = make_subgraph("sub2", 45)
    sub3 = make_subgraph("sub3", 45)

    # 主图 40 节点，加上 3 个 45 节点的子图 = 175 > 150
    root_nodes = {}
    for i in range(20):
        nid = f"root_{i}"
        nxt = f"root_{i + 1}" if i < 19 else "_TERMINAL_COMPLETE"
        root_nodes[nid] = ActionNode(id=nid, next_node_id=nxt)

    root_nodes["sf_1"] = SubflowNode(id="sf_1", subflow_graph=sub1, next_node_id="sf_2")
    root_nodes["sf_2"] = SubflowNode(id="sf_2", subflow_graph=sub2, next_node_id="sf_3")
    root_nodes["sf_3"] = SubflowNode(
        id="sf_3", subflow_graph=sub3, next_node_id="_TERMINAL_COMPLETE"
    )
    root_nodes["root_0"].next_node_id = "sf_1"

    root_graph = ExecutionGraph(entry_node_id="root_0", nodes=root_nodes)
    with pytest.raises(GraphValidationError, match="全任务流程图节点总数超过上限"):
        GraphNormalizer.validate_graph(root_graph)


def test_to_mermaid_sanitizes_node_ids_with_special_characters():
    # 节点 ID 包含破坏性特殊字符，如空格、连字符、括号、引号
    nodes = {
        "node with spaces (and brackets)": ActionNode(
            id="node with spaces (and brackets)",
            name="Normal Name",
            next_node_id="target-id.with.dots",
        ),
        "target-id.with.dots": ActionNode(
            id="target-id.with.dots",
            name="Target Name",
            next_node_id="_TERMINAL_COMPLETE",
        ),
    }
    graph = ExecutionGraph(entry_node_id="node with spaces (and brackets)", nodes=nodes)
    mermaid = GraphNormalizer.to_mermaid(graph)
    # 不应出现原始未转义的空格或括号作为标识符
    assert "node with spaces (and brackets)[" not in mermaid
    assert "node_with_spaces__and_brackets_[" in mermaid
    assert "-->|next| target_id_with_dots" in mermaid

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
        nxt = f"step_{i+1}" if i < MAX_NODES_PER_GRAPH else "_TERMINAL_COMPLETE"
        nodes[nid] = ActionNode(id=nid, next_node_id=nxt)
    graph = ExecutionGraph(entry_node_id="step_0", nodes=nodes)
    with pytest.raises(GraphValidationError, match="节点总数超过上限"):
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
    assert '&quot;' in mermaid or '#quot;' in mermaid

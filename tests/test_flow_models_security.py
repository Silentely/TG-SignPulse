# tests/test_flow_models_security.py
import pytest
from tg_signer.core.flow_models import (
    MAX_NODES_PER_GRAPH,
    MAX_PARALLEL_BRANCHES,
    MAX_SUBFLOW_DEPTH,
    MAX_TOTAL_TASK_NODES,
    ExecutionGraph,
)


def test_resource_constants_exist():
    assert MAX_NODES_PER_GRAPH == 50
    assert MAX_SUBFLOW_DEPTH == 3
    assert MAX_PARALLEL_BRANCHES == 10
    assert MAX_TOTAL_TASK_NODES == 150


def test_reject_unknown_node_type():
    data = {
        "entry_node_id": "step_1",
        "nodes": {
            "step_1": {
                "id": "step_1",
                "node_type": "wait_evet",  # 拼写错误
                "next_node_id": "_TERMINAL_COMPLETE",
            }
        },
    }
    with pytest.raises(ValueError, match="未知或不支持的节点类型"):
        ExecutionGraph.from_dict(data)


def test_reject_mismatched_key_and_node_id():
    data = {
        "entry_node_id": "step_1",
        "nodes": {
            "step_1": {
                "id": "step_2",  # key 与 node.id 不一致
                "node_type": "delay",
                "next_node_id": "_TERMINAL_COMPLETE",
            }
        },
    }
    with pytest.raises(ValueError, match="节点 ID 不一致"):
        ExecutionGraph.from_dict(data)

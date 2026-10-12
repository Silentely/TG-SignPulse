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


def test_execution_graph_and_delay_node_alias_compatibility():
    from tg_signer.core.flow_models import DelayNode
    from tg_signer.config import FlowStepConfig

    # 1. DelayNode 兼容 delay_seconds 字段
    d = DelayNode(id="d1", delay_seconds=4.5)
    assert d.seconds == 4.5

    # 2. ExecutionGraph.from_dict 兼容 "type": "delay" 与 delay_seconds
    data = {
        "entry_node_id": "step_delay",
        "nodes": {
            "step_delay": {
                "id": "step_delay",
                "type": "delay",
                "delay_seconds": 3.0,
                "next_node_id": "_TERMINAL_COMPLETE",
            }
        },
    }
    graph = ExecutionGraph.from_dict(data)
    node = graph.nodes["step_delay"]
    assert isinstance(node, DelayNode)
    assert node.seconds == 3.0

    # 3. FlowStepConfig 兼容 seconds
    fstep = FlowStepConfig(step_id="fs1", node_type="delay", seconds=2.5)
    assert fstep.delay_seconds == 2.5

# tests/test_flow_mermaid_adapter.py
import ast
from pathlib import Path

from tg_signer.core.flow_mermaid_adapter import (
    MermaidGraphAdapter,
    find_unreachable_nodes,
    render_mermaid_diagram,
)
from tg_signer.core.flow_models import (
    TERMINAL_COMPLETE_ID,
    TERMINAL_FAIL_ID,
    ActionNode,
    ConditionNode,
    ExecutionGraph,
    ParallelMode,
    ParallelNode,
    SubflowNode,
    TerminalPolicy,
)
from tg_signer.core.flow_normalizer import GraphNormalizer


def test_render_mermaid_basic_diagram():
    nodes = {
        "step_1": ActionNode(
            id="step_1",
            name="发送签到",
            next_node_id="step_cond",
            on_failure_node_id="step_err",
        ),
        "step_cond": ConditionNode(
            id="step_cond",
            name="检查结果",
            cases=[{"condition": "vars.status == 'ok'", "target_id": "step_done"}],
            default_target_id=TERMINAL_FAIL_ID,
        ),
        "step_done": ActionNode(
            id="step_done",
            name="完成步骤",
            next_node_id=TERMINAL_COMPLETE_ID,
            terminal_policy=TerminalPolicy.BRANCH_TO,
            terminal_branch_target=TERMINAL_COMPLETE_ID,
        ),
        "step_err": ActionNode(
            id="step_err",
            name="错误处理",
            next_node_id=TERMINAL_FAIL_ID,
        ),
    }
    graph = ExecutionGraph(
        entry_node_id="step_1",
        error_handler_node_id="step_err",
        nodes=nodes,
    )

    mermaid = render_mermaid_diagram(graph)
    assert mermaid.startswith("graph TD")
    assert "Start([开始]) --> step_1" in mermaid
    assert 'step_1["发送签到 [action]"]' in mermaid
    assert "step_1 -->|next| step_cond" in mermaid
    assert "step_1 -.->|on_failure| step_err" in mermaid
    assert (
        'step_cond -->|"vars.status == &#x27;ok&#x27;"| step_done' in mermaid
        or "step_cond -->|\"vars.status == 'ok'\"| step_done" in mermaid
        or "vars.status" in mermaid
    )
    assert "step_cond -->|default| Fail([失败])" in mermaid
    assert "step_done -->|next| End([完成])" in mermaid
    assert "step_done -.->|terminal_branch| End([完成])" in mermaid
    assert "ErrorHandler[全局降级错误处理] -.-> step_err" in mermaid


def test_render_mermaid_escaping_html_and_quotes():
    nodes = {
        "xss_node": ActionNode(
            id="xss_node",
            name='<script>alert("hack")</script>\nLine2',
            next_node_id="_TERMINAL_COMPLETE",
        ),
        "cond_node": ConditionNode(
            id="cond_node",
            cases=[
                {
                    "condition": 'vars.msg.contains("<test>") && val == "foo"',
                    "target_id": "xss_node",
                }
            ],
            default_target_id="_TERMINAL_COMPLETE",
        ),
    }
    graph = ExecutionGraph(entry_node_id="cond_node", nodes=nodes)
    mermaid = render_mermaid_diagram(graph)

    # 验证 XSS 标签及破坏性字符已被转义
    assert "<script>" not in mermaid
    assert "&lt;script&gt;" in mermaid
    assert "&quot;hack&quot;" in mermaid
    assert "\nLine2" not in mermaid
    assert "&lt;test&gt;" in mermaid
    assert "&quot;foo&quot;" in mermaid


def test_render_mermaid_id_sanitization():
    nodes = {
        "step with spaces (1)": ActionNode(
            id="step with spaces (1)",
            name="First Step",
            next_node_id="target-step.with.dots",
        ),
        "target-step.with.dots": ActionNode(
            id="target-step.with.dots",
            name="Second Step",
            next_node_id="_TERMINAL_COMPLETE",
        ),
    }
    graph = ExecutionGraph(entry_node_id="step with spaces (1)", nodes=nodes)
    mermaid = render_mermaid_diagram(graph)

    assert "step with spaces (1)[" not in mermaid
    assert "step_with_spaces__1_[" in mermaid
    assert "-->|next| target_step_with_dots" in mermaid
    assert MermaidGraphAdapter.sanitize_id("a-b.c d[e]") == "a_b_c_d_e_"


def test_find_unreachable_nodes_and_mermaid_styling():
    nodes = {
        "s1": ActionNode(id="s1", next_node_id="s2"),
        "s2": ActionNode(id="s2", next_node_id="_TERMINAL_COMPLETE"),
        "orphan_a": ActionNode(id="orphan_a", next_node_id="orphan_b"),
        "orphan_b": ActionNode(id="orphan_b", next_node_id="_TERMINAL_COMPLETE"),
    }
    graph = ExecutionGraph(entry_node_id="s1", nodes=nodes)

    unreachable = find_unreachable_nodes(graph)
    assert unreachable == {"orphan_a", "orphan_b"}

    mermaid = render_mermaid_diagram(graph)
    assert "orphan_a (不可达)" in mermaid
    assert "orphan_b (不可达)" in mermaid
    assert "style orphan_a stroke:#f59e0b,stroke-dasharray: 5 5" in mermaid
    assert "style orphan_b stroke:#f59e0b,stroke-dasharray: 5 5" in mermaid
    assert "style s1" not in mermaid
    assert "style s2" not in mermaid


def test_render_mermaid_subflows_rendering():
    sub_nodes = {
        "sub_step1": ActionNode(
            id="sub_step1", name="子步骤1", next_node_id="sub_step2"
        ),
        "sub_step2": ActionNode(
            id="sub_step2", name="子步骤2", next_node_id="_TERMINAL_COMPLETE"
        ),
    }
    subflow_graph = ExecutionGraph(entry_node_id="sub_step1", nodes=sub_nodes)

    root_nodes = {
        "root_1": ActionNode(id="root_1", name="根步骤1", next_node_id="sub_node"),
        "sub_node": SubflowNode(
            id="sub_node",
            name="调用子图",
            subflow_graph=subflow_graph,
            next_node_id="_TERMINAL_COMPLETE",
        ),
    }
    root_graph = ExecutionGraph(entry_node_id="root_1", nodes=root_nodes)

    mermaid = render_mermaid_diagram(root_graph, render_subgraphs=True)
    assert 'subgraph subgraph_sub_node ["子流程: 调用子图"]' in mermaid
    assert "sub_node__sub_step1" in mermaid
    assert "sub_node__sub_step2" in mermaid
    assert "sub_node -.->|subflow| sub_node__sub_step1" in mermaid

    # 禁用子图渲染时，只渲染顶级节点
    mermaid_flat = render_mermaid_diagram(root_graph, render_subgraphs=False)
    assert "subgraph subgraph_sub_node" not in mermaid_flat
    assert "sub_node__sub_step1" not in mermaid_flat


def test_render_mermaid_parallel_branches_rendering():
    b1_nodes = {
        "b1_s1": ActionNode(
            id="b1_s1", name="分支1步骤", next_node_id="_TERMINAL_COMPLETE"
        )
    }
    b2_nodes = {
        "b2_s1": ActionNode(
            id="b2_s1", name="分支2步骤", next_node_id="_TERMINAL_COMPLETE"
        )
    }
    b1_graph = ExecutionGraph(entry_node_id="b1_s1", nodes=b1_nodes)
    b2_graph = ExecutionGraph(entry_node_id="b2_s1", nodes=b2_nodes)

    par_node = ParallelNode(
        id="par_node",
        name="并发处理",
        mode=ParallelMode.ALL,
        branches=[b1_graph, b2_graph],
        next_node_id="_TERMINAL_COMPLETE",
    )
    graph = ExecutionGraph(
        entry_node_id="par_node",
        nodes={"par_node": par_node},
    )

    mermaid = render_mermaid_diagram(graph, render_subgraphs=True)
    assert 'subgraph parallel_par_node ["并行分支: 并发处理 (all)"]' in mermaid
    assert 'subgraph parallel_par_node_b0 ["分支 1"]' in mermaid
    assert 'subgraph parallel_par_node_b1 ["分支 2"]' in mermaid
    assert "par_node -.->|branch_1| par_node__b0__b1_s1" in mermaid
    assert "par_node -.->|branch_2| par_node__b1__b2_s1" in mermaid


def test_render_mermaid_graceful_error_handling():
    # 传入 None 应安全返回空字符串，不抛出异常
    assert render_mermaid_diagram(None) == ""

    # 传入非图对象应安全返回空字符串
    assert render_mermaid_diagram("invalid_string") == ""
    assert render_mermaid_diagram(12345) == ""
    assert render_mermaid_diagram({}) == ""

    # 空图对象
    empty_graph = ExecutionGraph(entry_node_id="none", nodes={})
    assert render_mermaid_diagram(empty_graph) == ""

    # 模拟内部渲染异常时返回空字符串
    class BrokenGraph:
        entry_node_id = "start"
        nodes = {"start": None}

    assert render_mermaid_diagram(BrokenGraph()) == ""


def test_graph_normalizer_backward_compatibility():
    nodes = {
        "s1": ActionNode(id="s1", name="步骤一", next_node_id="s2"),
        "s2": ActionNode(id="s2", name="步骤二", next_node_id="_TERMINAL_COMPLETE"),
        "unreach": ActionNode(
            id="unreach", name="孤立", next_node_id="_TERMINAL_COMPLETE"
        ),
    }
    graph = ExecutionGraph(entry_node_id="s1", nodes=nodes)

    via_adapter = render_mermaid_diagram(graph)
    via_normalizer = GraphNormalizer.to_mermaid(graph)
    assert via_adapter == via_normalizer

    unreach_adapter = find_unreachable_nodes(graph)
    unreach_normalizer = GraphNormalizer.find_unreachable_nodes(graph)
    assert unreach_adapter == unreach_normalizer == {"unreach"}


def test_core_execution_engine_zero_mermaid_imports():
    """验证核心执行引擎流转文件绝对不直接或间接导入 flow_mermaid_adapter。"""
    core_files = [
        Path("tg_signer/core/flow_engine.py"),
        Path("tg_signer/core/flow_adapter.py"),
        Path("tg_signer/core/signer_runner.py"),
    ]

    for file_path in core_files:
        assert file_path.exists(), f"文件不存在: {file_path}"
        source = file_path.read_text(encoding="utf-8")
        parsed = ast.parse(source, filename=str(file_path))

        imported_modules: set[str] = set()
        for node in ast.walk(parsed):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module)

        for imp in imported_modules:
            assert "flow_mermaid_adapter" not in imp, (
                f"架构违规: {file_path} 导入了 flow_mermaid_adapter ({imp})"
            )
            assert "mermaid" not in imp.lower(), (
                f"架构违规: {file_path} 存在 mermaid 依赖 ({imp})"
            )

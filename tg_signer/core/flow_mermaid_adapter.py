# tg_signer/core/flow_mermaid_adapter.py
from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Optional, Set, Union

from tg_signer.core.flow_models import (
    TERMINAL_COMPLETE_ID,
    TERMINAL_FAIL_ID,
    BaseFlowNode,
    ConditionNode,
    ExecutionGraph,
    ParallelNode,
    SubflowNode,
)

_SENTINELS: Set[str] = {
    TERMINAL_COMPLETE_ID,
    TERMINAL_FAIL_ID,
    "COMPLETE",
    "FAIL",
    "SUCCESS",
    "DONE",
    "FAILED",
    "ERROR",
}


def find_unreachable_nodes(graph: ExecutionGraph) -> Set[str]:
    """计算图中所有从入口步骤 (entry_node_id) 不可达的孤立节点集合。"""
    if (
        not graph
        or not getattr(graph, "nodes", None)
        or not getattr(graph, "entry_node_id", None)
        or graph.entry_node_id not in graph.nodes
    ):
        return set(graph.nodes.keys()) if (graph and getattr(graph, "nodes", None)) else set()

    visited: Set[str] = set()

    def _dfs(cur: str) -> None:
        if cur in _SENTINELS or cur not in graph.nodes or cur in visited:
            return
        visited.add(cur)
        cur_node = graph.nodes[cur]
        neighbors: List[str] = []
        if getattr(cur_node, "next_node_id", None):
            neighbors.append(cur_node.next_node_id)
        if getattr(cur_node, "on_failure_node_id", None):
            neighbors.append(cur_node.on_failure_node_id)
        if getattr(cur_node, "terminal_branch_target", None):
            neighbors.append(cur_node.terminal_branch_target)
        if isinstance(cur_node, ConditionNode):
            for c in getattr(cur_node, "cases", []):
                if c.get("target_id"):
                    neighbors.append(c["target_id"])
            if getattr(cur_node, "default_target_id", None):
                neighbors.append(cur_node.default_target_id)
        for nxt in neighbors:
            _dfs(nxt)

    _dfs(graph.entry_node_id)
    return set(graph.nodes.keys()) - visited


class MermaidGraphAdapter:
    """Mermaid 流程图序列化适配器，将 ExecutionGraph 转换为 Mermaid graph TD 语法。"""

    def __init__(
        self,
        graph: ExecutionGraph,
        *,
        render_subgraphs: bool = True,
    ) -> None:
        self.graph = graph
        self.render_subgraphs = render_subgraphs

    @staticmethod
    def sanitize_id(raw_id: Any) -> str:
        """净化节点 ID 为合法 Mermaid 标识符，非字母数字下划线替换为下划线。"""
        return re.sub(r"[^a-zA-Z0-9_]", "_", str(raw_id))

    @staticmethod
    def escape_label(raw_label: Any) -> str:
        """转义文本标签，防止 HTML/XSS 破坏以及换行和双引号问题。"""
        return html.escape(str(raw_label)).replace('"', "&quot;").replace("\n", " ")

    @classmethod
    def find_unreachable_nodes(cls, graph: ExecutionGraph) -> Set[str]:
        return find_unreachable_nodes(graph)

    def render(self) -> str:
        """渲染 Mermaid 图表完整字符串。"""
        if not self.graph or not getattr(self.graph, "nodes", None):
            return ""

        lines: List[str] = ["graph TD"]
        entry_safe = self.sanitize_id(self.graph.entry_node_id)
        lines.append(f"    Start([开始]) --> {entry_safe}")

        unreachable = self.find_unreachable_nodes(self.graph)
        lines.extend(
            self._render_graph_nodes(
                self.graph, unreachable=unreachable, prefix="", indent="    "
            )
        )

        if getattr(self.graph, "error_handler_node_id", None):
            eh_safe = self.sanitize_id(self.graph.error_handler_node_id)
            lines.append(f"    ErrorHandler[全局降级错误处理] -.-> {eh_safe}")

        return "\n".join(lines)

    def to_mermaid(self) -> str:
        """兼容别名方法。"""
        return self.render()

    def _resolve_target_label(self, target_id: str, prefix: str = "") -> str:
        if target_id in {TERMINAL_COMPLETE_ID, "COMPLETE", "SUCCESS", "DONE"}:
            return "End([完成])"
        elif target_id in {TERMINAL_FAIL_ID, "FAIL", "FAILED", "ERROR"}:
            return "Fail([失败])"
        else:
            return f"{prefix}{self.sanitize_id(target_id)}"

    def _render_graph_nodes(
        self,
        graph: ExecutionGraph,
        unreachable: Set[str],
        prefix: str = "",
        indent: str = "    ",
    ) -> List[str]:
        lines: List[str] = []

        for nid, node in graph.nodes.items():
            nid_safe = self.sanitize_id(nid)
            scoped_id = f"{prefix}{nid_safe}"
            is_unreach = nid in unreachable
            suffix = " (不可达)" if is_unreach else ""
            raw_node_type = (
                node.node_type.value
                if hasattr(node, "node_type") and hasattr(node.node_type, "value")
                else str(getattr(node, "node_type", "action"))
            )
            raw_label = f"{node.name or nid}{suffix} [{raw_node_type}]"
            sanitized_label = self.escape_label(raw_label)
            lines.append(f'{indent}{scoped_id}["{sanitized_label}"]')
            if is_unreach:
                lines.append(
                    f"{indent}style {scoped_id} stroke:#f59e0b,stroke-dasharray: 5 5"
                )

            if getattr(node, "next_node_id", None):
                target = self._resolve_target_label(node.next_node_id, prefix=prefix)
                lines.append(f"{indent}{scoped_id} -->|next| {target}")

            if getattr(node, "on_failure_node_id", None):
                target = self._resolve_target_label(node.on_failure_node_id, prefix=prefix)
                lines.append(f"{indent}{scoped_id} -.->|on_failure| {target}")

            if getattr(node, "terminal_branch_target", None):
                t_target = self._resolve_target_label(node.terminal_branch_target, prefix=prefix)
                lines.append(f"{indent}{scoped_id} -.->|terminal_branch| {t_target}")

            if isinstance(node, ConditionNode):
                for c in getattr(node, "cases", []):
                    t = c.get("target_id")
                    cond = c.get("condition", "")
                    if t:
                        t_lbl = self._resolve_target_label(t, prefix=prefix)
                        clean_cond = self.escape_label(cond)
                        lines.append(f'{indent}{scoped_id} -->|"{clean_cond}"| {t_lbl}')
                if getattr(node, "default_target_id", None):
                    def_t = self._resolve_target_label(node.default_target_id, prefix=prefix)
                    lines.append(f"{indent}{scoped_id} -->|default| {def_t}")

            # 子流程节点嵌套子图渲染
            if (
                isinstance(node, SubflowNode)
                and getattr(node, "subflow_graph", None)
                and self.render_subgraphs
                and getattr(node.subflow_graph, "nodes", None)
            ):
                sub_graph = node.subflow_graph
                sub_prefix = f"{scoped_id}__"
                sub_unreach = self.find_unreachable_nodes(sub_graph)
                sub_title = self.escape_label(node.name or f"Subflow {nid}")
                sub_id = f"subgraph_{scoped_id}"
                lines.append(f'{indent}subgraph {sub_id} ["子流程: {sub_title}"]')
                inner_lines = self._render_graph_nodes(
                    sub_graph,
                    unreachable=sub_unreach,
                    prefix=sub_prefix,
                    indent=indent + "    ",
                )
                lines.extend(inner_lines)
                lines.append(f"{indent}end")
                sub_entry = f"{sub_prefix}{self.sanitize_id(sub_graph.entry_node_id)}"
                lines.append(f"{indent}{scoped_id} -.->|subflow| {sub_entry}")

            # 并行分支节点嵌套子图渲染
            if (
                isinstance(node, ParallelNode)
                and getattr(node, "branches", None)
                and self.render_subgraphs
            ):
                par_id = f"parallel_{scoped_id}"
                mode_str = (
                    node.mode.value
                    if hasattr(node, "mode") and hasattr(node.mode, "value")
                    else str(getattr(node, "mode", "all"))
                )
                par_title = self.escape_label(f"并行分支: {node.name or nid} ({mode_str})")
                lines.append(f'{indent}subgraph {par_id} ["{par_title}"]')
                for b_idx, branch in enumerate(node.branches):
                    if not getattr(branch, "nodes", None):
                        continue
                    b_id = f"{par_id}_b{b_idx}"
                    b_prefix = f"{scoped_id}__b{b_idx}__"
                    lines.append(f'{indent}    subgraph {b_id} ["分支 {b_idx + 1}"]')
                    b_unreach = self.find_unreachable_nodes(branch)
                    b_lines = self._render_graph_nodes(
                        branch,
                        unreachable=b_unreach,
                        prefix=b_prefix,
                        indent=indent + "        ",
                    )
                    lines.extend(b_lines)
                    lines.append(f"{indent}    end")
                    b_entry = f"{b_prefix}{self.sanitize_id(branch.entry_node_id)}"
                    lines.append(f"{indent}    {scoped_id} -.->|branch_{b_idx + 1}| {b_entry}")
                lines.append(f"{indent}end")

        return lines


def render_mermaid_diagram(
    graph: Optional[ExecutionGraph],
    *,
    render_subgraphs: bool = True,
) -> str:
    """统一渲染入口：将 ExecutionGraph 导出为 Mermaid 图表字符串。

    契约：任何异常或无效输入均静默捕获并返回空字符串 ""，保证上层调用安全。
    """
    if graph is None or not hasattr(graph, "nodes") or not hasattr(graph, "entry_node_id"):
        return ""
    try:
        adapter = MermaidGraphAdapter(graph, render_subgraphs=render_subgraphs)
        return adapter.render()
    except Exception:
        return ""

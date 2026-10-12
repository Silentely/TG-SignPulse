# tg_signer/core/flow_normalizer.py
from __future__ import annotations

import html
from typing import Any, Dict, List, Optional

from tg_signer.config import (
    ChooseOptionByImageAction,
    ClickButtonByCalculationProblemAction,
    ClickKeyboardByTextAction,
    KeywordNotifyAction,
    PluginAction,
    ReplyByCalculationProblemAction,
    ReplyByImageRecognitionAction,
    SendDiceAction,
    SendTextAction,
    SignChatV3,
    action_from_step,
)
from tg_signer.core.flow_models import (
    MAX_NODES_PER_GRAPH,
    MAX_PARALLEL_BRANCHES,
    MAX_SUBFLOW_DEPTH,
    MAX_TOTAL_TASK_NODES,
    TERMINAL_COMPLETE_ID,
    TERMINAL_FAIL_ID,
    ActionNode,
    BaseFlowNode,
    ConditionNode,
    DelayNode,
    ExecutionGraph,
    ExtractorNode,
    LoopPolicy,
    ParallelMode,
    ParallelNode,
    RetryPolicy,
    SubflowNode,
    TerminalPolicy,
    WaitEventNode,
)


class GraphValidationError(ValueError):
    """图拓扑结构静态校验失败"""


class GraphNormalizer:
    """负责将旧版 SignChatV3 (actions/steps) 归一化为统一的 ExecutionGraph IR，并支持静态分析与可视化导出"""

    @classmethod
    def from_chat(cls, chat: SignChatV3) -> ExecutionGraph:
        if getattr(chat, "flow_graph", None):
            return cls._from_flow_graph(chat)
        if getattr(chat, "steps", None) and len(chat.steps) > 0:
            return cls._from_workflow_steps(chat)
        return cls._from_linear_actions(chat)

    @classmethod
    def _from_flow_graph(cls, chat: SignChatV3) -> ExecutionGraph:
        raw_graph = chat.flow_graph
        if isinstance(raw_graph, ExecutionGraph):
            graph = raw_graph
        elif isinstance(raw_graph, dict):
            graph = ExecutionGraph.from_dict(raw_graph)
        else:
            raise GraphValidationError("flow_graph 必须为字典对象或 ExecutionGraph")

        # 为 wait_event 节点自动注入 chat 上下文
        for node in graph.nodes.values():
            if isinstance(node, WaitEventNode):
                node.metadata.setdefault("chat_id", chat.chat_id)
                node.metadata.setdefault("chat_name", getattr(chat, "name", None))

        # 动态对齐单流程最大执行步数
        graph.max_total_steps = max(60, len(graph.nodes) * 2)
        cls.validate_graph(graph)
        return graph

    @classmethod
    def _from_linear_actions(cls, chat: SignChatV3) -> ExecutionGraph:
        nodes: Dict[str, BaseFlowNode] = {}
        raw_actions = getattr(chat, "actions", None) or []
        actions = list(raw_actions)
        total = len(actions)
        if total == 0:
            raise GraphValidationError("任务配置不合法：没有配置任何可执行动作")

        entry_id = "step_0"
        for i, act in enumerate(actions):
            node_id = f"step_{i}"
            next_id = f"step_{i + 1}" if i + 1 < total else TERMINAL_COMPLETE_ID

            # 向后兼容：只有当动作显式标记了 stop_flow_on_terminal 时才设置 STOP_FLOW
            is_stop_on_term = getattr(act, "stop_flow_on_terminal", False)
            term_policy = (
                TerminalPolicy.STOP_FLOW if is_stop_on_term else TerminalPolicy.IGNORE
            )

            action_type, params = cls._extract_action_type_and_params(act)

            # 若配置了 continue_on_error，失败后亦可继续走向下一步
            cont_on_err = getattr(act, "continue_on_error", False)
            fail_id = next_id if cont_on_err else TERMINAL_FAIL_ID

            run_if = getattr(act, "run_if", None) or getattr(act, "condition", None)
            skip_if = getattr(act, "skip_if", None)

            node = ActionNode(
                id=node_id,
                name=f"Action-{i + 1}",
                action_type=action_type,
                params=params,
                next_node_id=next_id,
                on_failure_node_id=fail_id,
                terminal_policy=term_policy,
                run_if=run_if,
                skip_if=skip_if,
                metadata={"raw_action": act},
            )
            nodes[node_id] = node

        graph = ExecutionGraph(entry_node_id=entry_id, nodes=nodes)
        cls.validate_graph(graph)
        return graph

    @classmethod
    def _from_workflow_steps(cls, chat: SignChatV3) -> ExecutionGraph:
        from tg_signer.config import FlowStepConfig

        nodes: Dict[str, BaseFlowNode] = {}
        entry_id = chat.initial_step_id or (
            chat.steps[0].step_id if chat.steps else TERMINAL_COMPLETE_ID
        )

        for step in chat.steps or []:
            next_id = cls._resolve_sentinel_id(step.next_step_id)
            fail_id = cls._resolve_sentinel_id(step.on_failure_step_id)

            # 区分 FlowStepConfig 与 WorkflowStepConfig
            if isinstance(step, FlowStepConfig):
                node = cls._build_node_from_flow_step(step, chat, next_id, fail_id)
            else:
                raw_act = action_from_step(step)
                action_type, params = cls._extract_action_type_and_params(raw_act)
                if step.config:
                    params.update(step.config)

                loop_pol = LoopPolicy(
                    allow_loop=step.allow_loop,
                    max_visits=step.max_retries + 1 if step.allow_loop else 1,
                )

                is_stop_on_term = getattr(
                    raw_act, "stop_flow_on_terminal", False
                ) or bool(
                    step.config.get("stop_flow_on_terminal", False)
                    if step.config
                    else False
                )
                term_policy = (
                    TerminalPolicy.STOP_FLOW
                    if is_stop_on_term
                    else TerminalPolicy.IGNORE
                )

                run_if = (step.config.get("run_if") if step.config else None) or (
                    step.config.get("condition") if step.config else None
                )
                skip_if = step.config.get("skip_if") if step.config else None

                node = ActionNode(
                    id=step.step_id,
                    name=f"Step-{step.step_id}",
                    action_type=action_type,
                    params=params,
                    next_node_id=next_id,
                    on_failure_node_id=fail_id,
                    loop_policy=loop_pol,
                    terminal_policy=term_policy,
                    run_if=run_if,
                    skip_if=skip_if,
                    metadata={"raw_action": raw_act, "workflow_step": step},
                )
            nodes[step.step_id] = node

        graph = ExecutionGraph(entry_node_id=entry_id, nodes=nodes)
        graph.max_total_steps = max(60, len(graph.nodes) * 2)
        cls.validate_graph(graph)
        return graph

    @classmethod
    def _build_node_from_flow_step(
        cls,
        step: Any,
        chat: SignChatV3,
        next_id: Optional[str],
        fail_id: Optional[str],
    ) -> BaseFlowNode:
        from tg_signer.config import FlowNodeType

        # 解析 terminal policy
        term_policy_str = str(
            getattr(step, "terminal_policy", "ignore") or "ignore"
        ).lower()
        if term_policy_str == "stop_flow":
            term_policy = TerminalPolicy.STOP_FLOW
        elif term_policy_str == "branch_to":
            term_policy = TerminalPolicy.BRANCH_TO
        else:
            term_policy = TerminalPolicy.IGNORE

        term_target = cls._resolve_sentinel_id(
            getattr(step, "terminal_branch_target", None)
        )

        # 解析 retry policy
        rp_data = getattr(step, "retry_policy", None)
        if isinstance(rp_data, RetryPolicy):
            retry_pol = rp_data
        elif isinstance(rp_data, dict) and rp_data:
            retry_pol = RetryPolicy(**rp_data)
        else:
            retry_pol = RetryPolicy()

        # 解析 loop policy
        lp_data = getattr(step, "loop_policy", None)
        if isinstance(lp_data, LoopPolicy):
            loop_pol = lp_data
        elif isinstance(lp_data, dict) and lp_data:
            loop_pol = LoopPolicy(**lp_data)
        else:
            allow_loop = getattr(step, "allow_loop", False)
            max_retries = getattr(step, "max_retries", None)
            max_visits = (
                (max_retries + 1) if (allow_loop and max_retries is not None) else 1
            )
            loop_pol = LoopPolicy(allow_loop=allow_loop, max_visits=max_visits)

        common_kwargs = {
            "id": step.step_id,
            "name": step.name or f"{step.node_type.value.capitalize()}-{step.step_id}",
            "next_node_id": next_id,
            "on_failure_node_id": fail_id,
            "terminal_policy": term_policy,
            "terminal_branch_target": term_target,
            "retry_policy": retry_pol,
            "loop_policy": loop_pol,
            "timeout_seconds": getattr(step, "timeout_seconds", 25.0) or 25.0,
            "run_if": step.run_if,
            "skip_if": step.skip_if,
            "metadata": dict(getattr(step, "metadata", {}) or {}),
        }

        ntype = step.node_type
        if ntype == FlowNodeType.ACTION:
            raw_act = None
            try:
                raw_act = action_from_step(step)
            except Exception:
                pass
            if raw_act is not None:
                action_type, params = cls._extract_action_type_and_params(raw_act)
            else:
                action_type = (
                    step.action_type.name
                    if hasattr(step.action_type, "name")
                    else str(step.action_type or "SEND_TEXT").upper()
                )
                params = dict(step.params or {})
            if step.config:
                params.update(step.config)
            common_kwargs["metadata"]["raw_action"] = raw_act
            common_kwargs["metadata"]["workflow_step"] = step
            return ActionNode(action_type=action_type, params=params, **common_kwargs)

        elif ntype == FlowNodeType.WAIT_EVENT:
            common_kwargs["metadata"].setdefault("chat_id", chat.chat_id)
            common_kwargs["metadata"].setdefault(
                "chat_name", getattr(chat, "name", None)
            )
            return WaitEventNode(
                event_type=step.event_type,
                filter_patterns=list(step.filter_patterns or []),
                **common_kwargs,
            )

        elif ntype == FlowNodeType.CONDITION:
            parsed_cases = [
                {
                    "condition": c.get("condition", ""),
                    "target_id": cls._resolve_sentinel_id(c.get("target_id")),
                }
                for c in (step.cases or [])
            ]
            default_target = cls._resolve_sentinel_id(step.default_target_id)
            return ConditionNode(
                cases=parsed_cases,
                default_target_id=default_target,
                **common_kwargs,
            )

        elif ntype == FlowNodeType.DELAY:
            return DelayNode(
                seconds=float(getattr(step, "delay_seconds", 1.0) or 1.0),
                **common_kwargs,
            )

        elif ntype == FlowNodeType.EXTRACTOR:
            export_vars = dict(step.export_vars or {})
            if not export_vars and getattr(step, "variable_name", None):
                export_vars["1"] = step.variable_name
            return ExtractorNode(
                source_field=step.source_field,
                regex=step.regex,
                export_vars=export_vars,
                **common_kwargs,
            )

        elif ntype == FlowNodeType.SUBFLOW:
            sub_graph = None
            if step.subflow_graph:
                sub_graph = (
                    step.subflow_graph
                    if isinstance(step.subflow_graph, ExecutionGraph)
                    else ExecutionGraph.from_dict(step.subflow_graph)
                )
            return SubflowNode(
                subflow_graph=sub_graph,
                subflow_id=step.subflow_id,
                input_vars=dict(step.input_vars or {}),
                output_vars=dict(step.output_vars or {}),
                **common_kwargs,
            )

        elif ntype == FlowNodeType.PARALLEL:
            branches = []
            for b in step.branches or []:
                branches.append(
                    b if isinstance(b, ExecutionGraph) else ExecutionGraph.from_dict(b)
                )
            mode_str = str(getattr(step, "parallel_mode", "all") or "all").lower()
            try:
                parallel_mode = ParallelMode(mode_str)
            except ValueError:
                parallel_mode = ParallelMode.ALL
            return ParallelNode(
                branches=branches,
                mode=parallel_mode,
                max_concurrency=step.max_concurrency,
                join_strategy=getattr(step, "join_strategy", "merge"),
                **common_kwargs,
            )

        raise GraphValidationError(f"不支持的节点类型: {ntype}")

    @staticmethod
    def _resolve_sentinel_id(step_id: str | None) -> str | None:
        if not step_id:
            return None
        sid = step_id.strip()
        if sid.upper() == "COMPLETE":
            return TERMINAL_COMPLETE_ID
        if sid.upper() == "FAIL":
            return TERMINAL_FAIL_ID
        return sid

    @classmethod
    def _extract_action_type_and_params(cls, act: Any) -> tuple[str, Dict[str, Any]]:
        params: Dict[str, Any] = {}
        action_type = "UNKNOWN"

        if isinstance(act, SendTextAction):
            action_type = "SEND_TEXT"
            params["text"] = act.text
        elif isinstance(act, SendDiceAction):
            action_type = "SEND_DICE"
            params["dice"] = act.dice
        elif isinstance(act, ClickKeyboardByTextAction):
            action_type = "CLICK_KEYBOARD_BY_TEXT"
            params["text"] = act.text
        elif isinstance(act, ChooseOptionByImageAction):
            action_type = "CHOOSE_OPTION_BY_IMAGE"
            params["ai_prompt"] = act.ai_prompt
        elif isinstance(act, ClickButtonByCalculationProblemAction):
            action_type = "CLICK_BUTTON_BY_CALCULATION"
            params["ai_prompt"] = act.ai_prompt
        elif isinstance(act, ReplyByCalculationProblemAction):
            action_type = "REPLY_BY_CALCULATION"
            params["ai_prompt"] = act.ai_prompt
        elif isinstance(act, ReplyByImageRecognitionAction):
            action_type = "REPLY_BY_IMAGE_RECOGNITION"
            params["ai_prompt"] = act.ai_prompt
        elif isinstance(act, KeywordNotifyAction):
            action_type = "KEYWORD_NOTIFY"
            params["keywords"] = act.keywords
        elif isinstance(act, PluginAction):
            action_type = "PLUGIN"
            params["plugin_name"] = act.plugin_name
            params["mode"] = act.mode
            params["timeout"] = act.timeout
            params["params"] = act.params
        elif isinstance(act, dict):
            raw_act_type = act.get("action") or act.get("action_type") or "UNKNOWN"
            action_type = str(raw_act_type).upper()
            params.update(act)

        if hasattr(act, "delay") and act.delay is not None:
            params["delay"] = act.delay
        if hasattr(act, "skip_if_matched"):
            params["skip_if_matched"] = getattr(act, "skip_if_matched", None)
        if hasattr(act, "continue_on_error"):
            params["continue_on_error"] = getattr(act, "continue_on_error", False)
        if hasattr(act, "stop_flow_on_terminal"):
            params["stop_flow_on_terminal"] = getattr(
                act, "stop_flow_on_terminal", False
            )

        return action_type, params

    @classmethod
    def validate_graph(
        cls,
        graph: ExecutionGraph,
        depth: int = 1,
        budget: Optional[Dict[str, int]] = None,
    ) -> None:
        """检查悬空边、分支目标与全连通分量死循环及资源上限"""
        if not graph.nodes:
            raise GraphValidationError("执行图不能为空")
        if len(graph.nodes) > MAX_NODES_PER_GRAPH:
            raise GraphValidationError(
                f"单图节点总数超过上限: 当前 {len(graph.nodes)} > 最大允许 {MAX_NODES_PER_GRAPH}"
            )
        if depth > MAX_SUBFLOW_DEPTH:
            raise GraphValidationError(
                f"子图嵌套深度超过上限: 当前 {depth} > 最大允许 {MAX_SUBFLOW_DEPTH}"
            )

        if budget is None:
            budget = {"total_nodes": 0}
        budget["total_nodes"] += len(graph.nodes)
        if budget["total_nodes"] > MAX_TOTAL_TASK_NODES:
            raise GraphValidationError(
                f"全任务流程图节点总数超过上限: 当前 {budget['total_nodes']} > 最大允许 {MAX_TOTAL_TASK_NODES}"
            )

        if graph.entry_node_id not in graph.nodes:
            raise GraphValidationError(f"初始步骤 {graph.entry_node_id} 不在图节点中")

        sentinels = {TERMINAL_COMPLETE_ID, TERMINAL_FAIL_ID, "COMPLETE", "FAIL"}

        if graph.resume_from_node_id and graph.resume_from_node_id not in sentinels:
            if graph.resume_from_node_id not in graph.nodes:
                raise GraphValidationError(
                    f"断点恢复节点 resume_from_node_id '{graph.resume_from_node_id}' 不在图节点中"
                )

        # 1. 检查边完整性
        for node_id, node in graph.nodes.items():
            if node.next_node_id and node.next_node_id not in sentinels:
                if node.next_node_id not in graph.nodes:
                    raise GraphValidationError(
                        f"步骤 {node_id} 的 next_node_id '{node.next_node_id}' 指向不存在的节点"
                    )
            if node.on_failure_node_id and node.on_failure_node_id not in sentinels:
                if node.on_failure_node_id not in graph.nodes:
                    raise GraphValidationError(
                        f"步骤 {node_id} 的 on_failure_node_id '{node.on_failure_node_id}' 指向不存在的节点"
                    )
            if (
                node.terminal_branch_target
                and node.terminal_branch_target not in sentinels
            ):
                if node.terminal_branch_target not in graph.nodes:
                    raise GraphValidationError(
                        f"步骤 {node_id} 的 terminal_branch_target '{node.terminal_branch_target}' 指向不存在的节点"
                    )
            if isinstance(node, ConditionNode):
                for c in node.cases:
                    t_id = c.get("target_id")
                    if t_id and t_id not in sentinels and t_id not in graph.nodes:
                        raise GraphValidationError(
                            f"条件节点 {node_id} 的目标 '{t_id}' 指向不存在的节点"
                        )
                if (
                    node.default_target_id
                    and node.default_target_id not in sentinels
                    and node.default_target_id not in graph.nodes
                ):
                    raise GraphValidationError(
                        f"条件节点 {node_id} 的默认目标 '{node.default_target_id}' 指向不存在的节点"
                    )

        if graph.error_handler_node_id and graph.error_handler_node_id not in sentinels:
            if graph.error_handler_node_id not in graph.nodes:
                raise GraphValidationError(
                    f"全局错误处理节点 error_handler_node_id '{graph.error_handler_node_id}' 指向不存在的节点"
                )

        # 2. 环路检测 (DFS)
        visited = set()
        rec_stack: List[str] = []

        def _dfs(cur: str):
            if cur in sentinels or cur not in graph.nodes:
                return
            if cur in rec_stack:
                cycle_start = rec_stack.index(cur)
                cycle_steps = rec_stack[cycle_start:]
                # 环路中的每个节点都必须允许重复访问，否则运行时必然在某个节点熔断。
                all_allowed = all(
                    (
                        graph.nodes[sid].loop_policy.allow_loop
                        and graph.nodes[sid].loop_policy.max_visits > 1
                    )
                    for sid in cycle_steps
                    if sid in graph.nodes
                )
                if not all_allowed:
                    raise GraphValidationError(
                        f"检测到未允许的环路: {' -> '.join(cycle_steps)} -> {cur}"
                    )
                return

            if cur in visited:
                return

            visited.add(cur)
            rec_stack.append(cur)

            cur_node = graph.nodes[cur]
            neighbors = []
            if cur_node.next_node_id:
                neighbors.append(cur_node.next_node_id)
            if cur_node.on_failure_node_id:
                neighbors.append(cur_node.on_failure_node_id)
            if cur_node.terminal_branch_target:
                neighbors.append(cur_node.terminal_branch_target)
            if isinstance(cur_node, ConditionNode):
                for c in cur_node.cases:
                    if c.get("target_id"):
                        neighbors.append(c["target_id"])
                if cur_node.default_target_id:
                    neighbors.append(cur_node.default_target_id)
            if isinstance(cur_node, SubflowNode) and cur_node.subflow_graph:
                cls.validate_graph(
                    cur_node.subflow_graph, depth=depth + 1, budget=budget
                )
            if isinstance(cur_node, ParallelNode) and cur_node.branches:
                if len(cur_node.branches) > MAX_PARALLEL_BRANCHES:
                    raise GraphValidationError(
                        f"并行分支数超过上限: 当前 {len(cur_node.branches)} > 最大允许 {MAX_PARALLEL_BRANCHES}"
                    )
                for branch in cur_node.branches:
                    cls.validate_graph(branch, depth=depth + 1, budget=budget)

            for nxt in neighbors:
                _dfs(nxt)

            rec_stack.pop()

        # 1. 从入口节点出发做 DFS
        _dfs(graph.entry_node_id)

        # 2. 遍历全图中所有未访问到的连通分量，检测孤立子图中的死循环
        for nid in list(graph.nodes.keys()):
            if nid not in visited:
                _dfs(nid)

    @classmethod
    def to_mermaid(cls, graph: ExecutionGraph) -> str:
        """将执行图导出为标准 Mermaid 流程图文本 (graph TD)"""
        import re

        def _safe_id(raw_id: str) -> str:
            return re.sub(r"[^a-zA-Z0-9_]", "_", str(raw_id))

        lines = ["graph TD"]
        entry_safe = _safe_id(graph.entry_node_id)
        lines.append(f"    Start([开始]) --> {entry_safe}")

        for nid, node in graph.nodes.items():
            nid_safe = _safe_id(nid)
            raw_label = f"{node.name or nid} [{node.node_type.value}]"
            sanitized_label = (
                html.escape(raw_label).replace('"', "&quot;").replace("\n", " ")
            )
            lines.append(f'    {nid_safe}["{sanitized_label}"]')

            if node.next_node_id:
                if node.next_node_id == TERMINAL_COMPLETE_ID:
                    target = "End([完成])"
                elif node.next_node_id == TERMINAL_FAIL_ID:
                    target = "Fail([失败])"
                else:
                    target = _safe_id(node.next_node_id)
                lines.append(f"    {nid_safe} -->|next| {target}")

            if node.on_failure_node_id:
                if node.on_failure_node_id == TERMINAL_FAIL_ID:
                    target = "Fail([失败])"
                else:
                    target = _safe_id(node.on_failure_node_id)
                lines.append(f"    {nid_safe} -.->|on_failure| {target}")

            if isinstance(node, ConditionNode):
                for c in node.cases:
                    t = c.get("target_id")
                    cond = c.get("condition", "")
                    if t:
                        if t == TERMINAL_COMPLETE_ID:
                            t_lbl = "End([完成])"
                        elif t == TERMINAL_FAIL_ID:
                            t_lbl = "Fail([失败])"
                        else:
                            t_lbl = _safe_id(t)
                        clean_cond = (
                            html.escape(str(cond))
                            .replace('"', "&quot;")
                            .replace("\n", " ")
                        )
                        lines.append(f'    {nid_safe} -->|"{clean_cond}"| {t_lbl}')
                if node.default_target_id:
                    if node.default_target_id == TERMINAL_COMPLETE_ID:
                        def_t = "End([完成])"
                    elif node.default_target_id == TERMINAL_FAIL_ID:
                        def_t = "Fail([失败])"
                    else:
                        def_t = _safe_id(node.default_target_id)
                    lines.append(f"    {nid_safe} -->|default| {def_t}")

        if graph.error_handler_node_id:
            lines.append(
                f"    ErrorHandler[全局降级错误处理] -.-> {_safe_id(graph.error_handler_node_id)}"
            )

        return "\n".join(lines)

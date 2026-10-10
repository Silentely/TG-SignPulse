# tg_signer/core/flow_normalizer.py
from __future__ import annotations

from typing import Any, Dict, List

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
    TERMINAL_COMPLETE_ID,
    TERMINAL_FAIL_ID,
    ActionNode,
    BaseFlowNode,
    ConditionNode,
    ExecutionGraph,
    LoopPolicy,
    TerminalPolicy,
)


class GraphValidationError(ValueError):
    """图拓扑结构静态校验失败"""


class GraphNormalizer:
    """负责将旧版 SignChatV3 (actions/steps) 归一化为统一的 ExecutionGraph IR"""

    @classmethod
    def from_chat(cls, chat: SignChatV3) -> ExecutionGraph:
        if getattr(chat, "steps", None) and len(chat.steps) > 0:
            return cls._from_workflow_steps(chat)
        return cls._from_linear_actions(chat)

    @classmethod
    def _from_linear_actions(cls, chat: SignChatV3) -> ExecutionGraph:
        nodes: Dict[str, BaseFlowNode] = {}
        total = len(chat.actions)
        if total == 0:
            return ExecutionGraph(entry_node_id=TERMINAL_COMPLETE_ID, nodes={})

        entry_id = "step_0"
        for i, act in enumerate(chat.actions):
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

            node = ActionNode(
                id=node_id,
                name=f"Action-{i + 1}",
                action_type=action_type,
                params=params,
                next_node_id=next_id,
                on_failure_node_id=fail_id,
                terminal_policy=term_policy,
                metadata={"raw_action": act},
            )
            nodes[node_id] = node

        graph = ExecutionGraph(entry_node_id=entry_id, nodes=nodes)
        cls.validate_graph(graph)
        return graph

    @classmethod
    def _from_workflow_steps(cls, chat: SignChatV3) -> ExecutionGraph:
        nodes: Dict[str, BaseFlowNode] = {}
        entry_id = chat.initial_step_id or (
            chat.steps[0].step_id if chat.steps else TERMINAL_COMPLETE_ID
        )

        for step in chat.steps:
            raw_act = action_from_step(step)
            action_type, params = cls._extract_action_type_and_params(raw_act)
            if step.config:
                params.update(step.config)

            next_id = cls._resolve_sentinel_id(step.next_step_id)
            fail_id = cls._resolve_sentinel_id(step.on_failure_step_id)

            loop_pol = LoopPolicy(
                allow_loop=step.allow_loop,
                max_visits=step.max_retries + 1 if step.allow_loop else 1,
            )

            is_stop_on_term = getattr(raw_act, "stop_flow_on_terminal", False)
            term_policy = (
                TerminalPolicy.STOP_FLOW if is_stop_on_term else TerminalPolicy.IGNORE
            )

            node = ActionNode(
                id=step.step_id,
                name=f"Step-{step.step_id}",
                action_type=action_type,
                params=params,
                next_node_id=next_id,
                on_failure_node_id=fail_id,
                loop_policy=loop_pol,
                terminal_policy=term_policy,
                metadata={"raw_action": raw_act, "workflow_step": step},
            )
            nodes[step.step_id] = node

        graph = ExecutionGraph(entry_node_id=entry_id, nodes=nodes)
        cls.validate_graph(graph)
        return graph

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
            params["emoji"] = act.emoji
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
            params["plugin_id"] = act.plugin_id
            params["params"] = act.params

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
    def validate_graph(cls, graph: ExecutionGraph) -> None:
        """检查悬空边、分支目标与死循环"""
        if not graph.nodes:
            raise GraphValidationError("执行图不能为空")
        if graph.entry_node_id not in graph.nodes:
            raise GraphValidationError(f"初始步骤 {graph.entry_node_id} 不在图节点中")

        sentinels = {TERMINAL_COMPLETE_ID, TERMINAL_FAIL_ID, "COMPLETE", "FAIL"}

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

        # 2. 环路检测 (DFS)
        visited = set()
        rec_stack: List[str] = []

        def _dfs(cur: str):
            if cur in sentinels or cur not in graph.nodes:
                return
            if cur in rec_stack:
                cycle_start = rec_stack.index(cur)
                cycle_steps = rec_stack[cycle_start:]
                # 环路中若至少存在一个显式声明 allow_loop=True 且 max_visits > 1 的节点，则认为属于合法的循环重试流
                has_allowed = any(
                    (
                        graph.nodes[sid].loop_policy.allow_loop
                        and graph.nodes[sid].loop_policy.max_visits > 1
                    )
                    for sid in cycle_steps
                    if sid in graph.nodes
                )
                if not has_allowed:
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

            for nxt in neighbors:
                _dfs(nxt)

            rec_stack.pop()

        _dfs(graph.entry_node_id)

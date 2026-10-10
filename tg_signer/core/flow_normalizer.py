# tg_signer/core/flow_normalizer.py
from __future__ import annotations

from typing import Any, Dict
from tg_signer.config import (
    SignChatV3,
    SignAction,
    SendTextAction,
    SendDiceAction,
    ClickKeyboardByTextAction,
    ChooseOptionByImageAction,
    ReplyByCalculationProblemAction,
    ReplyByImageRecognitionAction,
    ClickButtonByCalculationProblemAction,
    KeywordNotifyAction,
    PluginAction,
    action_from_step,
)
from tg_signer.core.flow_models import (
    ActionNode,
    BaseFlowNode,
    ExecutionGraph,
    LoopPolicy,
    NodeType,
    TerminalPolicy,
    TERMINAL_COMPLETE_ID,
    TERMINAL_FAIL_ID,
)

class GraphValidationError(ValueError):
    """图拓扑结构静态校验失败"""

class GraphNormalizer:
    """将既有配置模型无损编译归一化为标准的 ExecutionGraph 并完成拓扑校验"""

    @classmethod
    def from_chat(cls, chat: SignChatV3) -> ExecutionGraph:
        if getattr(chat, "steps", None):
            graph = cls._normalize_workflow_steps(chat)
        else:
            graph = cls._normalize_legacy_actions(chat)

        cls.validate_graph(graph)
        return graph

    @classmethod
    def _normalize_legacy_actions(cls, chat: SignChatV3) -> ExecutionGraph:
        actions = chat.actions or []
        if not actions:
            raise ValueError("任务配置不合法：没有配置任何可执行动作或工作流步骤")

        nodes: Dict[str, BaseFlowNode] = {}
        total = len(actions)
        for i, act in enumerate(actions):
            node_id = f"step_{i}"
            next_id = f"step_{i + 1}" if i + 1 < total else TERMINAL_COMPLETE_ID

            is_stop_on_term = getattr(act, "stop_flow_on_terminal", False)
            term_policy = (
                TerminalPolicy.STOP_FLOW if is_stop_on_term else TerminalPolicy.IGNORE
            )

            action_type, params = cls._extract_action_type_and_params(act)

            node = ActionNode(
                id=node_id,
                name=f"Action-{i + 1}",
                action_type=action_type,
                params=params,
                next_node_id=next_id,
                on_failure_node_id=TERMINAL_FAIL_ID,
                terminal_policy=term_policy,
                metadata={"raw_action": act},
            )
            nodes[node_id] = node

        return ExecutionGraph(entry_node_id="step_0", nodes=nodes)

    @classmethod
    def _normalize_workflow_steps(cls, chat: SignChatV3) -> ExecutionGraph:
        steps = chat.steps or []
        nodes: Dict[str, BaseFlowNode] = {}
        for s in steps:
            raw_act = action_from_step(s)
            action_type, params = cls._extract_action_type_and_params(raw_act)

            next_target = s.next_step_id
            if next_target == "COMPLETE" or not next_target:
                next_id = TERMINAL_COMPLETE_ID
            elif next_target == "FAIL":
                next_id = TERMINAL_FAIL_ID
            else:
                next_id = next_target

            fail_target = s.on_failure_step_id
            if fail_target == "FAIL" or not fail_target:
                fail_id = TERMINAL_FAIL_ID
            elif fail_target == "COMPLETE":
                fail_id = TERMINAL_COMPLETE_ID
            else:
                fail_id = fail_target

            loop_policy = LoopPolicy(
                allow_loop=bool(getattr(s, "allow_loop", False)),
                max_visits=(s.max_retries + 1) if getattr(s, "allow_loop", False) and s.max_retries is not None else 1,
            )

            node = ActionNode(
                id=s.step_id,
                name=getattr(s, "name", "") or s.step_id,
                action_type=action_type,
                params=params,
                next_node_id=next_id,
                on_failure_node_id=fail_id,
                loop_policy=loop_policy,
                metadata={"raw_action": raw_act, "step_cfg": s},
            )
            nodes[s.step_id] = node

        initial_id = str(chat.initial_step_id or (steps[0].step_id if steps else ""))
        return ExecutionGraph(entry_node_id=initial_id, nodes=nodes)

    @classmethod
    def _extract_action_type_and_params(cls, act: Any) -> tuple[str, Dict[str, Any]]:
        # 保留所有公共属性
        params: Dict[str, Any] = {
            "delay": getattr(act, "delay", None),
            "continue_on_error": getattr(act, "continue_on_error", False),
            "skip_if_matched": getattr(act, "skip_if_matched", None),
            "stop_flow_on_terminal": getattr(act, "stop_flow_on_terminal", False),
        }
        if isinstance(act, SendTextAction):
            params["text"] = act.text
            return "SEND_TEXT", params
        elif isinstance(act, SendDiceAction):
            params["dice"] = act.dice
            return "SEND_DICE", params
        elif isinstance(act, ClickKeyboardByTextAction):
            params["text"] = act.text
            return "CLICK_KEYBOARD", params
        elif isinstance(act, ChooseOptionByImageAction):
            params["ai_prompt"] = act.ai_prompt
            return "CHOOSE_OPTION_BY_IMAGE", params
        elif isinstance(act, ReplyByCalculationProblemAction):
            params["ai_prompt"] = act.ai_prompt
            return "REPLY_CALCULATION", params
        elif isinstance(act, ReplyByImageRecognitionAction):
            params["ai_prompt"] = act.ai_prompt
            return "REPLY_IMAGE_RECOGNITION", params
        elif isinstance(act, ClickButtonByCalculationProblemAction):
            params["ai_prompt"] = act.ai_prompt
            return "CLICK_BUTTON_CALCULATION", params
        elif isinstance(act, KeywordNotifyAction):
            params["keywords"] = act.keywords
            return "KEYWORD_NOTIFY", params
        elif isinstance(act, PluginAction):
            params["plugin_name"] = act.plugin_name
            params["params"] = act.params
            params["mode"] = act.mode
            params["timeout"] = act.timeout
            return "PLUGIN", params
        else:
            return getattr(act, "__class__", type(act)).__name__, getattr(act, "__dict__", {})

    @classmethod
    def validate_graph(cls, graph: ExecutionGraph) -> None:
        """检查悬空边与死循环"""
        if not graph.nodes:
            raise GraphValidationError("执行图不能为空")
        if graph.entry_node_id not in graph.nodes:
            raise GraphValidationError(f"初始步骤 {graph.entry_node_id} 不在图节点中")

        sentinels = {TERMINAL_COMPLETE_ID, TERMINAL_FAIL_ID, "COMPLETE", "FAIL"}
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

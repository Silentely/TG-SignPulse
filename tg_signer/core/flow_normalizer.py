# tg_signer/core/flow_normalizer.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

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


AI_ACTION_TYPES = {
    "CHOOSE_OPTION_BY_IMAGE",
    "REPLY_BY_IMAGE_RECOGNITION",
    "CLICK_BUTTON_BY_CALCULATION",
    "CLICK_BUTTON_BY_CALCULATION_PROBLEM",
    "REPLY_BY_CALCULATION",
    "REPLY_BY_CALCULATION_PROBLEM",
}


class GraphNormalizer:
    """负责将旧版 SignChatV3 (actions/steps) 归一化为统一的 ExecutionGraph IR，并支持静态分析与可视化导出"""

    @classmethod
    def compile(
        cls,
        source: Union[SignChatV3, Dict[str, Any], ExecutionGraph],
        *,
        budget: Optional[Dict[str, int]] = None,
        warnings: Optional[List[str]] = None,
    ) -> ExecutionGraph:
        """统一图编译入口：
        1. 保证输入非破坏性（调用方传入的 dict 不会被原地修改）
        2. 将 SignChatV3 / 字典 / 图对象规范化为 ExecutionGraph
        3. 统一执行拓扑与连通性校验，支持跨 chat 预算累积与 warnings 收集
        """
        import copy

        if isinstance(source, ExecutionGraph):
            graph = source.copy(deep=True)
            cls.validate_graph(graph, budget=budget, warnings=warnings)
            return graph

        if isinstance(source, dict):
            src = copy.deepcopy(source)
            if "nodes" in src and ("entry_node_id" in src or "max_total_steps" in src):
                graph = ExecutionGraph.from_dict(src)
                graph.max_total_steps = max(60, len(graph.nodes) * 2)
                cls.validate_graph(graph, budget=budget, warnings=warnings)
                return graph
            else:
                from tg_signer.config import SignChatV3, SupportAction

                src.setdefault("chat_id", 0)
                if "actions" in src and isinstance(src["actions"], list):
                    for act in src["actions"]:
                        if isinstance(act, dict) and isinstance(act.get("action"), str):
                            try:
                                act["action"] = SupportAction[act["action"].upper()]
                            except (KeyError, ValueError):
                                pass
                chat_obj = SignChatV3(**src)
                return cls.from_chat(chat_obj, budget=budget, warnings=warnings)

        from tg_signer.config import SignChatV3

        if isinstance(source, SignChatV3):
            return cls.from_chat(source, budget=budget, warnings=warnings)

        raise GraphValidationError(f"无法从类型 {type(source).__name__} 编译执行图")

    @classmethod
    def from_chat(
        cls,
        chat: SignChatV3,
        *,
        budget: Optional[Dict[str, int]] = None,
        warnings: Optional[List[str]] = None,
    ) -> ExecutionGraph:
        if getattr(chat, "flow_graph", None):
            return cls._from_flow_graph(chat, budget=budget, warnings=warnings)
        if getattr(chat, "steps", None) and len(chat.steps) > 0:
            return cls._from_workflow_steps(chat, budget=budget, warnings=warnings)
        return cls._from_linear_actions(chat, budget=budget, warnings=warnings)

    @classmethod
    def _from_flow_graph(
        cls,
        chat: SignChatV3,
        budget: Optional[Dict[str, int]] = None,
        warnings: Optional[List[str]] = None,
    ) -> ExecutionGraph:
        import copy

        raw_graph = chat.flow_graph
        if isinstance(raw_graph, ExecutionGraph):
            graph = raw_graph.copy(deep=True)
        elif isinstance(raw_graph, dict):
            graph = ExecutionGraph.from_dict(copy.deepcopy(raw_graph))
        else:
            raise GraphValidationError("flow_graph 必须为字典对象或 ExecutionGraph")

        # 为 wait_event 节点自动注入 chat 上下文
        for node in graph.nodes.values():
            if isinstance(node, WaitEventNode):
                node.metadata.setdefault("chat_id", chat.chat_id)
                node.metadata.setdefault("chat_name", getattr(chat, "name", None))
                if getattr(chat, "message_thread_id", None) is not None:
                    node.metadata.setdefault(
                        "message_thread_id", chat.message_thread_id
                    )

        # 动态对齐单流程最大执行步数
        graph.max_total_steps = max(60, len(graph.nodes) * 2)
        cls.validate_graph(graph, budget=budget, warnings=warnings)
        return graph

    @classmethod
    def _from_linear_actions(
        cls,
        chat: SignChatV3,
        budget: Optional[Dict[str, int]] = None,
        warnings: Optional[List[str]] = None,
    ) -> ExecutionGraph:
        nodes: Dict[str, BaseFlowNode] = {}
        raw_actions = getattr(chat, "actions", None) or []
        actions = list(raw_actions)
        total = len(actions)
        if total == 0:
            raise GraphValidationError("任务配置不合法：没有配置任何可执行动作")

        entry_id = "step_0"
        for i, act in enumerate(actions):
            node_id = f"step_{i}"
            next_action_id = f"step_{i + 1}" if i + 1 < total else TERMINAL_COMPLETE_ID

            # 向后兼容：只有当动作显式标记了 stop_flow_on_terminal 时才设置 STOP_FLOW
            is_stop_on_term = (
                getattr(act, "stop_flow_on_terminal", False)
                if not isinstance(act, dict)
                else bool(act.get("stop_flow_on_terminal", False))
            )
            term_policy = (
                TerminalPolicy.STOP_FLOW if is_stop_on_term else TerminalPolicy.IGNORE
            )

            action_type, params = cls._extract_action_type_and_params(act)

            wait_for_reply = (
                getattr(act, "wait_for_reply", False)
                if not isinstance(act, dict)
                else bool(act.get("wait_for_reply", False))
            )
            wait_node_id = f"step_{i}_wait" if wait_for_reply else None
            effective_next_id = wait_node_id if wait_for_reply else next_action_id

            # 若配置了 continue_on_error，失败后亦可继续走向下一步
            cont_on_err = (
                getattr(act, "continue_on_error", False)
                if not isinstance(act, dict)
                else bool(act.get("continue_on_error", False))
            )
            fail_id = effective_next_id if cont_on_err else TERMINAL_FAIL_ID

            run_if = (
                (getattr(act, "run_if", None) or getattr(act, "condition", None))
                if not isinstance(act, dict)
                else (act.get("run_if") or act.get("condition"))
            )
            skip_if = (
                getattr(act, "skip_if", None)
                if not isinstance(act, dict)
                else act.get("skip_if")
            )

            from tg_signer.utils import read_positive_float_env

            base_timeout = read_positive_float_env(
                "SIGN_TASK_ACTION_TIMEOUT", 25.0, 5.0
            )
            ai_default_timeout = read_positive_float_env(
                "SIGN_TASK_AI_ACTION_TIMEOUT", 60.0, 10.0
            )
            if action_type in AI_ACTION_TYPES:
                step_timeout = max(base_timeout, ai_default_timeout)
            else:
                step_timeout = base_timeout

            raw_timeout = (
                getattr(act, "timeout", None)
                if not isinstance(act, dict)
                else (act.get("timeout") or act.get("timeout_seconds"))
            )
            if raw_timeout is not None:
                try:
                    step_timeout = max(5.0, float(raw_timeout))
                except (ValueError, TypeError):
                    pass

            node = ActionNode(
                id=node_id,
                name=f"Action-{i + 1}",
                action_type=action_type,
                params=params,
                next_node_id=effective_next_id,
                on_failure_node_id=fail_id,
                terminal_policy=term_policy,
                timeout_seconds=step_timeout,
                run_if=run_if,
                skip_if=skip_if,
                metadata={"raw_action": act},
            )
            nodes[node_id] = node

            if wait_for_reply:
                from tg_signer.reply_settings import (
                    get_reply_timeout,
                    get_retry_interval,
                    get_retry_keywords,
                    get_retry_max_attempts,
                )

                success_pats = (
                    getattr(act, "reply_success_patterns", None)
                    if not isinstance(act, dict)
                    else act.get("reply_success_patterns")
                ) or []
                failure_pats = (
                    getattr(act, "reply_failure_patterns", None)
                    if not isinstance(act, dict)
                    else act.get("reply_failure_patterns")
                ) or []
                reply_timeout = cls._explicit_setting(act, "reply_timeout_seconds")
                try:
                    reply_timeout = max(
                        30.0,
                        min(
                            3600.0,
                            float(
                                reply_timeout
                                if reply_timeout is not None
                                else get_reply_timeout()
                            ),
                        ),
                    )
                except (ValueError, TypeError):
                    reply_timeout = get_reply_timeout()
                reply_retry_keywords = cls._explicit_setting(
                    act, "reply_retry_keywords"
                )
                if reply_retry_keywords is None:
                    reply_retry_keywords = get_retry_keywords()
                reply_retry_interval = cls._explicit_setting(
                    act, "reply_retry_interval"
                )
                if reply_retry_interval is None:
                    reply_retry_interval = get_retry_interval()
                reply_retry_interval = max(1.0, min(300.0, float(reply_retry_interval)))
                reply_retry_max_attempts = cls._explicit_setting(
                    act, "reply_retry_max_attempts"
                )
                if reply_retry_max_attempts is None:
                    reply_retry_max_attempts = get_retry_max_attempts()
                reply_retry_max_attempts = max(
                    0, min(10, int(reply_retry_max_attempts))
                )

                sem_res = (
                    getattr(act, "semantic_result", None)
                    if not isinstance(act, dict)
                    else act.get("semantic_result")
                )
                wait_node = WaitEventNode(
                    id=wait_node_id,
                    name="等待机器人回复",
                    event_type="ANY",
                    success_patterns=list(success_pats),
                    failure_patterns=list(failure_pats),
                    timeout_seconds=reply_timeout,
                    retry_keywords=reply_retry_keywords,
                    retry_interval=reply_retry_interval,
                    max_retries=reply_retry_max_attempts,
                    action_node_id=node_id,
                    next_node_id=next_action_id,
                    on_failure_node_id=TERMINAL_FAIL_ID,
                    semantic_result=sem_res,
                    metadata={
                        "chat_id": chat.chat_id,
                        "chat_name": getattr(chat, "name", None),
                        "message_thread_id": chat.message_thread_id,
                        "action_node_id": node_id,
                    },
                )
                nodes[wait_node_id] = wait_node

        graph = ExecutionGraph(entry_node_id=entry_id, nodes=nodes)
        for flow_node in nodes.values():
            if isinstance(flow_node, WaitEventNode):
                flow_node.metadata.setdefault("retry_entry_node_id", entry_id)
        cls.validate_graph(graph, budget=budget, warnings=warnings)
        return graph

    @classmethod
    def _from_workflow_steps(
        cls,
        chat: SignChatV3,
        budget: Optional[Dict[str, int]] = None,
        warnings: Optional[List[str]] = None,
    ) -> ExecutionGraph:
        from tg_signer.config import FlowStepConfig

        nodes: Dict[str, BaseFlowNode] = {}
        entry_id = chat.initial_step_id or (
            chat.steps[0].step_id if chat.steps else TERMINAL_COMPLETE_ID
        )

        for raw_step in chat.steps or []:
            if isinstance(raw_step, dict):
                from tg_signer.config import WorkflowStepConfig

                step = WorkflowStepConfig(**raw_step)
            else:
                step = raw_step

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

                max_visits = (
                    (step.max_retries + 1)
                    if (step.allow_loop and step.max_retries is not None)
                    else 1
                )
                loop_pol = LoopPolicy(
                    allow_loop=bool(step.allow_loop),
                    max_visits=max_visits,
                )

                is_stop_on_term = (
                    getattr(raw_act, "stop_flow_on_terminal", False)
                    or bool(
                        step.config.get("stop_flow_on_terminal", False)
                        if step.config
                        else False
                    )
                    or bool(getattr(step, "stop_flow_on_terminal", False))
                )

                term_policy_raw = (
                    (step.config.get("terminal_policy") if step.config else None)
                    or getattr(step, "terminal_policy", None)
                    or ("stop_flow" if is_stop_on_term else "ignore")
                )
                if isinstance(term_policy_raw, TerminalPolicy):
                    term_policy = term_policy_raw
                elif str(term_policy_raw).lower() == "stop_flow":
                    term_policy = TerminalPolicy.STOP_FLOW
                elif str(term_policy_raw).lower() == "branch_to":
                    term_policy = TerminalPolicy.BRANCH_TO
                else:
                    term_policy = TerminalPolicy.IGNORE

                term_target = cls._resolve_sentinel_id(
                    (step.config.get("terminal_branch_target") if step.config else None)
                    or getattr(step, "terminal_branch_target", None)
                )

                run_if = (step.config.get("run_if") if step.config else None) or (
                    step.config.get("condition") if step.config else None
                )
                skip_if = step.config.get("skip_if") if step.config else None

                from tg_signer.utils import read_positive_float_env

                base_timeout = read_positive_float_env(
                    "SIGN_TASK_ACTION_TIMEOUT", 25.0, 5.0
                )
                ai_default_timeout = read_positive_float_env(
                    "SIGN_TASK_AI_ACTION_TIMEOUT", 60.0, 10.0
                )
                if action_type in AI_ACTION_TYPES:
                    step_timeout = max(base_timeout, ai_default_timeout)
                else:
                    step_timeout = base_timeout

                if step.config and (
                    "timeout" in step.config or "timeout_seconds" in step.config
                ):
                    raw_to = step.config.get("timeout") or step.config.get(
                        "timeout_seconds"
                    )
                    try:
                        step_timeout = max(5.0, float(raw_to))
                    except (ValueError, TypeError):
                        pass

                node = ActionNode(
                    id=step.step_id,
                    name=f"Step-{step.step_id}",
                    action_type=action_type,
                    params=params,
                    next_node_id=next_id,
                    on_failure_node_id=fail_id,
                    loop_policy=loop_pol,
                    terminal_policy=term_policy,
                    terminal_branch_target=term_target,
                    timeout_seconds=step_timeout,
                    run_if=run_if,
                    skip_if=skip_if,
                    metadata={"raw_action": raw_act, "workflow_step": step},
                )
            nodes[step.step_id] = node

        graph = ExecutionGraph(entry_node_id=entry_id, nodes=nodes)
        graph.max_total_steps = max(60, len(graph.nodes) * 2)
        for flow_node in nodes.values():
            if isinstance(flow_node, WaitEventNode):
                flow_node.metadata.setdefault("retry_entry_node_id", entry_id)
        cls.validate_graph(graph, budget=budget, warnings=warnings)
        return graph

    @staticmethod
    def _explicit_setting(source: Any, key: str) -> Any:
        if isinstance(source, dict):
            return source.get(key)
        if key in getattr(source, "__fields_set__", set()):
            return getattr(source, key, None)
        return None

    @staticmethod
    def _resolve_flow_step_timeout(step: Any) -> float:
        from tg_signer.config import FlowNodeType
        from tg_signer.utils import read_positive_float_env

        timeout_val = (
            GraphNormalizer._explicit_setting(step, "timeout_seconds")
            if getattr(step, "node_type", None) == FlowNodeType.WAIT_EVENT
            else getattr(step, "timeout_seconds", None)
        )
        if timeout_val is None or timeout_val <= 0:
            if getattr(step, "node_type", None) == FlowNodeType.WAIT_EVENT:
                from tg_signer.reply_settings import get_reply_timeout

                timeout_val = get_reply_timeout()
            else:
                base_timeout = read_positive_float_env(
                    "SIGN_TASK_ACTION_TIMEOUT", 25.0, 5.0
                )
                timeout_val = base_timeout
        else:
            timeout_val = float(timeout_val)

        if getattr(step, "node_type", None) == FlowNodeType.WAIT_EVENT:
            timeout_val = max(30.0, min(3600.0, timeout_val))
        elif getattr(step, "node_type", None) == FlowNodeType.ACTION:
            act_type_str = ""
            if hasattr(step, "action_type") and step.action_type:
                act_type_str = (
                    step.action_type.name
                    if hasattr(step.action_type, "name")
                    else str(step.action_type)
                ).upper()
            if act_type_str in AI_ACTION_TYPES:
                ai_default = read_positive_float_env(
                    "SIGN_TASK_AI_ACTION_TIMEOUT", 60.0, 10.0
                )
                timeout_val = max(timeout_val, ai_default)
        return timeout_val

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
            "timeout_seconds": cls._resolve_flow_step_timeout(step),
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
            from tg_signer.reply_settings import (
                get_retry_interval,
                get_retry_keywords,
                get_retry_max_attempts,
            )

            common_kwargs["metadata"].setdefault("chat_id", chat.chat_id)
            common_kwargs["metadata"].setdefault(
                "chat_name", getattr(chat, "name", None)
            )
            if getattr(chat, "message_thread_id", None) is not None:
                common_kwargs["metadata"].setdefault(
                    "message_thread_id", chat.message_thread_id
                )

            step_retry_keywords = cls._explicit_setting(step, "retry_keywords")
            if step_retry_keywords is None:
                step_retry_keywords = get_retry_keywords()
            step_retry_interval = cls._explicit_setting(step, "retry_interval")
            if step_retry_interval is None:
                step_retry_interval = get_retry_interval()
            step_max_retries = cls._explicit_setting(step, "max_retries")
            if step_max_retries is None:
                step_max_retries = get_retry_max_attempts()

            return WaitEventNode(
                event_type=getattr(step, "event_type", "ANY") or "ANY",
                filter_patterns=list(getattr(step, "filter_patterns", []) or []),
                success_patterns=list(getattr(step, "success_patterns", []) or []),
                failure_patterns=list(getattr(step, "failure_patterns", []) or []),
                semantic_result=getattr(step, "semantic_result", None),
                retry_keywords=step_retry_keywords,
                retry_interval=max(1.0, min(300.0, float(step_retry_interval))),
                max_retries=max(0, min(10, int(step_max_retries))),
                action_node_id=getattr(step, "action_node_id", None),
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
        if sid.upper() in {"COMPLETE", "SUCCESS", "DONE", TERMINAL_COMPLETE_ID}:
            return TERMINAL_COMPLETE_ID
        if sid.upper() in {"FAIL", "FAILED", "ERROR", TERMINAL_FAIL_ID}:
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
    def find_unreachable_nodes(cls, graph: ExecutionGraph) -> set[str]:
        """计算图中所有从入口步骤 (entry_node_id) 不可达的孤立节点集合（委托至 flow_mermaid_adapter）"""
        from tg_signer.core.flow_mermaid_adapter import find_unreachable_nodes

        return find_unreachable_nodes(graph)

    @classmethod
    def validate_graph(
        cls,
        graph: ExecutionGraph,
        depth: int = 1,
        budget: Optional[Dict[str, int]] = None,
        warnings: Optional[List[str]] = None,
    ) -> None:
        """检查悬空边、分支目标与全连通分量死循环及资源上限，并收集不可达步骤告警"""
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

        if budget is not None:
            current_total = budget.get(
                "current_total_nodes", budget.get("total_nodes", 0)
            )
            max_limit = budget.get(
                "max_total_task_nodes", budget.get("max_nodes", MAX_TOTAL_TASK_NODES)
            )
            new_total = current_total + len(graph.nodes)
            if new_total > max_limit:
                raise GraphValidationError(
                    f"全任务流程图节点总数超过上限: 当前 {new_total} > 最大允许 {max_limit}"
                )
            budget["current_total_nodes"] = new_total
            budget["total_nodes"] = new_total
        else:
            if depth == 1:
                budget = {
                    "current_total_nodes": len(graph.nodes),
                    "total_nodes": len(graph.nodes),
                    "max_total_task_nodes": MAX_TOTAL_TASK_NODES,
                }
                if len(graph.nodes) > MAX_TOTAL_TASK_NODES:
                    raise GraphValidationError(
                        f"全任务流程图节点总数超过上限: 当前 {len(graph.nodes)} > 最大允许 {MAX_TOTAL_TASK_NODES}"
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
                    cur_node.subflow_graph,
                    depth=depth + 1,
                    budget=budget,
                    warnings=warnings,
                )
            if isinstance(cur_node, ParallelNode) and cur_node.branches:
                if len(cur_node.branches) > MAX_PARALLEL_BRANCHES:
                    raise GraphValidationError(
                        f"并行分支数超过上限: 当前 {len(cur_node.branches)} > 最大允许 {MAX_PARALLEL_BRANCHES}"
                    )
                for branch in cur_node.branches:
                    cls.validate_graph(
                        branch,
                        depth=depth + 1,
                        budget=budget,
                        warnings=warnings,
                    )

            for nxt in neighbors:
                _dfs(nxt)

            rec_stack.pop()

        # 1. 从入口节点出发做 DFS
        _dfs(graph.entry_node_id)
        entry_visited = set(visited)

        # 2. 遍历全图中所有未访问到的连通分量，检测孤立子图中的死循环
        for nid in list(graph.nodes.keys()):
            if nid not in visited:
                _dfs(nid)

        # 3. 收集从入口步骤不可达的步骤告警 (对齐 Spec 4.4)
        unreachable = set(graph.nodes.keys()) - entry_visited
        if unreachable and warnings is not None:
            for un_id in sorted(unreachable):
                warnings.append(
                    f"步骤 '{un_id}' 从入口步骤 '{graph.entry_node_id}' 不可达"
                )

    @classmethod
    def to_mermaid(cls, graph: ExecutionGraph) -> str:
        """将执行图导出为标准 Mermaid 流程图文本 (graph TD)（委托至 flow_mermaid_adapter）"""
        from tg_signer.core.flow_mermaid_adapter import render_mermaid_diagram

        return render_mermaid_diagram(graph)

# tg_signer/core/flow_models.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

TERMINAL_COMPLETE_ID = "_TERMINAL_COMPLETE"
TERMINAL_FAIL_ID = "_TERMINAL_FAIL"

SENSITIVE_KEY_PATTERNS = (
    "token",
    "password",
    "secret",
    "api_key",
    "apikey",
    "auth_key",
    "session",
    "private_key",
    "credential",
)


def redact_sensitive_value(val: Any) -> Any:
    """递归脱敏敏感字段，保留结构并保护私密信息"""
    if isinstance(val, str):
        if len(val) <= 6:
            return "***"
        return f"{val[:2]}***{val[-2:]}"
    elif isinstance(val, dict):
        return {
            k: (
                redact_sensitive_value(v)
                if any(p in str(k).lower() for p in SENSITIVE_KEY_PATTERNS)
                else (redact_sensitive_value(v) if isinstance(v, (dict, list)) else v)
            )
            for k, v in val.items()
        }
    elif isinstance(val, list):
        return [redact_sensitive_value(item) for item in val]
    return val


class NodeType(str, Enum):
    ACTION = "action"
    WAIT_EVENT = "wait_event"
    CONDITION = "condition"
    EXTRACTOR = "extractor"
    DELAY = "delay"
    SUBFLOW = "subflow"
    PARALLEL = "parallel"


class ParallelMode(str, Enum):
    ALL = "all"
    ANY = "any"
    ALL_SETTLED = "all_settled"


class TerminalPolicy(str, Enum):
    IGNORE = "ignore"
    STOP_FLOW = "stop_flow"
    BRANCH_TO = "branch_to"


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    TERMINAL_EARLY = "terminal_early"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


class FlowSignal(str, Enum):
    PROCEED = "proceed"
    HALT_SUCCESS = "halt_success"
    HALT_FAIL = "halt_fail"
    BRANCH = "branch"
    RETRY_NODE = "retry_node"


@dataclass
class StepOutcome:
    node_id: str
    status: NodeStatus
    output_text: str = ""
    extracted_vars: Dict[str, Any] = field(default_factory=dict)
    matched_terminal: bool = False
    signal: FlowSignal = FlowSignal.PROCEED
    target_node_id: Optional[str] = None
    error: Optional[Exception] = None
    duration_ms: float = 0.0
    # 内部控制节点的诊断文本不应覆盖后续动作可见的 Telegram 输出。
    updates_last_output: bool = True

    def to_dict(self, redact_sensitive: bool = False) -> Dict[str, Any]:
        """序列化步骤执行结果，支持敏感数据可选脱敏"""
        extracted = (
            redact_sensitive_value(self.extracted_vars)
            if redact_sensitive
            else dict(self.extracted_vars)
        )
        return {
            "node_id": self.node_id,
            "status": self.status.value,
            "output_text": self.output_text,
            "extracted_vars": extracted,
            "matched_terminal": self.matched_terminal,
            "signal": self.signal.value,
            "target_node_id": self.target_node_id,
            "error": str(self.error) if self.error else None,
            "duration_ms": self.duration_ms,
            "updates_last_output": self.updates_last_output,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> StepOutcome:
        """从字典反序列化步骤结果"""
        status_val = data.get("status", NodeStatus.SUCCESS.value)
        try:
            status = NodeStatus(status_val)
        except ValueError:
            status = NodeStatus.SUCCESS
        signal_val = data.get("signal", FlowSignal.PROCEED.value)
        try:
            sig = FlowSignal(signal_val)
        except ValueError:
            sig = FlowSignal.PROCEED
        err_str = data.get("error")
        return cls(
            node_id=data["node_id"],
            status=status,
            output_text=data.get("output_text", ""),
            extracted_vars=dict(data.get("extracted_vars", {})),
            matched_terminal=bool(data.get("matched_terminal", False)),
            signal=sig,
            target_node_id=data.get("target_node_id"),
            error=RuntimeError(err_str) if err_str else None,
            duration_ms=float(data.get("duration_ms", 0.0)),
            updates_last_output=bool(data.get("updates_last_output", True)),
        )


class RetryPolicy(BaseModel):
    max_attempts: int = 1
    backoff_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 15.0
    retry_on_exceptions: List[str] = Field(default_factory=list)


class LoopPolicy(BaseModel):
    allow_loop: bool = False
    max_visits: int = 1


class BaseFlowNode(BaseModel):
    id: str
    name: str = ""
    node_type: NodeType
    next_node_id: Optional[str] = None
    on_failure_node_id: Optional[str] = None
    terminal_policy: TerminalPolicy = TerminalPolicy.IGNORE
    terminal_branch_target: Optional[str] = None
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    loop_policy: LoopPolicy = Field(default_factory=LoopPolicy)
    timeout_seconds: float = 25.0
    run_if: Optional[str] = None
    skip_if: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ActionNode(BaseFlowNode):
    node_type: NodeType = NodeType.ACTION
    action_type: str = "SEND_TEXT"
    params: Dict[str, Any] = Field(default_factory=dict)


class WaitEventNode(BaseFlowNode):
    node_type: NodeType = NodeType.WAIT_EVENT
    event_type: str = "NEW_MESSAGE"
    filter_patterns: List[str] = Field(default_factory=list)


class ConditionNode(BaseFlowNode):
    node_type: NodeType = NodeType.CONDITION
    cases: List[Dict[str, str]] = Field(default_factory=list)
    default_target_id: Optional[str] = None


class ExtractorNode(BaseFlowNode):
    node_type: NodeType = NodeType.EXTRACTOR
    source_field: str = "prev.output"
    regex: str = ""
    export_vars: Dict[str, str] = Field(default_factory=dict)


class DelayNode(BaseFlowNode):
    node_type: NodeType = NodeType.DELAY
    seconds: float = 1.0


class SubflowNode(BaseFlowNode):
    node_type: NodeType = NodeType.SUBFLOW
    subflow_graph: Optional[ExecutionGraph] = None
    subflow_id: Optional[str] = None
    input_vars: Dict[str, str] = Field(default_factory=dict)
    output_vars: Dict[str, str] = Field(default_factory=dict)
    export_vars: List[str] = Field(default_factory=list)


class ParallelNode(BaseFlowNode):
    node_type: NodeType = NodeType.PARALLEL
    branches: List[ExecutionGraph] = Field(default_factory=list)
    mode: ParallelMode = ParallelMode.ALL
    max_concurrency: Optional[int] = None
    join_strategy: str = "merge"


NODE_TYPE_MAP: Dict[NodeType, type[BaseFlowNode]] = {
    NodeType.ACTION: ActionNode,
    NodeType.WAIT_EVENT: WaitEventNode,
    NodeType.CONDITION: ConditionNode,
    NodeType.EXTRACTOR: ExtractorNode,
    NodeType.DELAY: DelayNode,
    NodeType.SUBFLOW: SubflowNode,
    NodeType.PARALLEL: ParallelNode,
}


class ExecutionGraph(BaseModel):
    entry_node_id: str
    nodes: Dict[str, BaseFlowNode]
    max_total_steps: int = 30
    error_handler_node_id: Optional[str] = None
    resume_from_node_id: Optional[str] = None
    consecutive_failure_limit: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExecutionGraph:
        """从字典反序列化图，自动将节点字典转换为对应的多态子类实例。"""
        raw_nodes = data.get("nodes", {})
        parsed_nodes: Dict[str, BaseFlowNode] = {}
        for nid, n_data in raw_nodes.items():
            if isinstance(n_data, BaseFlowNode):
                parsed_nodes[nid] = n_data
                continue
            if isinstance(n_data, dict):
                node_kwargs = dict(n_data)
                node_kwargs.setdefault("id", nid)
                ntype_str = node_kwargs.get("node_type", NodeType.ACTION.value)
                try:
                    ntype = NodeType(ntype_str)
                except ValueError:
                    ntype = NodeType.ACTION
                target_cls = NODE_TYPE_MAP.get(ntype, ActionNode)
                if (
                    target_cls is SubflowNode
                    and "subflow_graph" in node_kwargs
                    and isinstance(node_kwargs["subflow_graph"], dict)
                ):
                    node_kwargs["subflow_graph"] = cls.from_dict(
                        node_kwargs["subflow_graph"]
                    )
                    parsed_nodes[nid] = SubflowNode(**node_kwargs)
                elif (
                    target_cls is ParallelNode
                    and "branches" in node_kwargs
                    and isinstance(node_kwargs["branches"], list)
                ):
                    node_kwargs["branches"] = [
                        cls.from_dict(b) if isinstance(b, dict) else b
                        for b in node_kwargs["branches"]
                    ]
                    parsed_nodes[nid] = ParallelNode(**node_kwargs)
                else:
                    parsed_nodes[nid] = target_cls(**node_kwargs)
            else:
                parsed_nodes[nid] = n_data
        return cls(
            entry_node_id=data.get("entry_node_id", ""),
            nodes=parsed_nodes,
            max_total_steps=data.get("max_total_steps", 30),
            error_handler_node_id=data.get("error_handler_node_id"),
            resume_from_node_id=data.get("resume_from_node_id"),
            consecutive_failure_limit=data.get("consecutive_failure_limit"),
        )


SubflowNode.update_forward_refs(ExecutionGraph=ExecutionGraph)
ParallelNode.update_forward_refs(ExecutionGraph=ExecutionGraph)

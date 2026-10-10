# tg_signer/core/flow_models.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

TERMINAL_COMPLETE_ID = "_TERMINAL_COMPLETE"
TERMINAL_FAIL_ID = "_TERMINAL_FAIL"


class NodeType(str, Enum):
    ACTION = "action"
    WAIT_EVENT = "wait_event"
    CONDITION = "condition"
    EXTRACTOR = "extractor"
    DELAY = "delay"
    SUBFLOW = "subflow"


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


class ExecutionGraph(BaseModel):
    entry_node_id: str
    nodes: Dict[str, BaseFlowNode]
    max_total_steps: int = 30

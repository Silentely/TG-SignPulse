# 控制节点配置化 (Control Nodes Configuration) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通任务配置到控制流节点的接线，支持在任务配置中声明条件分支、事件等待、延时、提取器、子流程与并发分支节点，并提供 Mermaid 流程图预览闭环。

**Architecture:** 采用双轨配置模式（多态步骤列表 `FlowStepConfig` 与原生 IR 直通 `flow_graph`），在 `GraphNormalizer` 中实现全节点类型转换与递归拓扑校验；后端服务保留扩展配置并提供流程图预览 API，前端提供数据序列化与拓扑预览组件。

**Tech Stack:** Python 3.10+, Pydantic, Pytest, FastAPI, TypeScript, Vue 3, Mermaid.js

**Spec:** `docs/superpowers/specs/2026-10-11-control-nodes-configuration-design.md`

## Global Constraints
- 完全向后兼容：历史任务中的 `actions` 线性列表与现有 `WorkflowStepConfig` 步骤配置行为不可变更。
- 零悬空边与死循环防护：所有控制节点必须通过 `GraphNormalizer.validate_graph` 静态校验。
- 强类型与无破坏性回退：当 `node_type` 缺省时默认回退为 `ActionNode`。

---

### Task 1: 多态步骤配置与图直通数据模型 (`FlowStepConfig` & `SignChatV3.flow_graph`)

**Files:**
- Modify: `tg_signer/config.py:320-460`
- Create: `tests/test_flow_step_config.py`

**Interfaces:**
- Produces: `FlowNodeType`, `FlowStepConfig`, `SignChatV3.flow_graph`
- Consumes: `SupportAction`, `BaseModel`, `Field`

- [ ] **Step 1: 编写多态步骤模型失败测试**

```python
# tests/test_flow_step_config.py
import pytest
from tg_signer.config import FlowNodeType, FlowStepConfig, SignChatV3, SupportAction


def test_legacy_step_backward_compatibility():
    # 模拟旧版仅有 action_type 的步骤字典
    data = {
        "step_id": "step_1",
        "action_type": SupportAction.SEND_TEXT,
        "config": {"text": "/checkin"},
        "next_step_id": "COMPLETE",
    }
    step = FlowStepConfig(**data)
    assert step.step_id == "step_1"
    assert step.node_type == FlowNodeType.ACTION
    assert step.action_type == SupportAction.SEND_TEXT
    assert step.config["text"] == "/checkin"


def test_polymorphic_condition_step():
    data = {
        "step_id": "cond_1",
        "node_type": "condition",
        "cases": [
            {"condition": "res.status == 200", "target_id": "step_success"},
            {"condition": "res.status != 200", "target_id": "step_retry"},
        ],
        "default_target_id": "FAIL",
    }
    step = FlowStepConfig(**data)
    assert step.node_type == FlowNodeType.CONDITION
    assert len(step.cases) == 2
    assert step.default_target_id == "FAIL"


def test_chat_v3_supports_flow_graph():
    chat_data = {
        "chat_id": 123456,
        "flow_graph": {
            "entry_node_id": "node_1",
            "nodes": {
                "node_1": {
                    "node_type": "action",
                    "action_type": "SEND_TEXT",
                    "params": {"text": "hello"},
                    "next_node_id": "_TERMINAL_COMPLETE",
                }
            },
        },
    }
    chat = SignChatV3(**chat_data)
    assert chat.flow_graph is not None
    assert chat.flow_graph["entry_node_id"] == "node_1"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_flow_step_config.py -v`
Expected: FAIL with `ImportError: cannot import name 'FlowNodeType'`

- [ ] **Step 3: 在 `tg_signer/config.py` 中实现 `FlowNodeType` 与 `FlowStepConfig`，扩展 `SignChatV3`**

```python
# 在 tg_signer/config.py 中
from enum import Enum

class FlowNodeType(str, Enum):
    ACTION = "action"
    CONDITION = "condition"
    WAIT_EVENT = "wait_event"
    DELAY = "delay"
    EXTRACTOR = "extractor"
    SUBFLOW = "subflow"
    PARALLEL = "parallel"


class FlowStepConfig(BaseModel):
    step_id: str
    node_type: FlowNodeType = FlowNodeType.ACTION
    name: Optional[str] = None
    next_step_id: Optional[str] = None
    on_failure_step_id: Optional[str] = None
    terminal_policy: Optional[str] = "ignore"
    run_if: Optional[str] = None
    skip_if: Optional[str] = None
    allow_loop: bool = False
    max_retries: Optional[int] = None
    timeout_seconds: Optional[float] = 25.0

    # Action 专用
    action_type: Optional[SupportAction] = None
    config: Dict[str, Any] = Field(default_factory=dict)

    # Condition 专用
    cases: List[Dict[str, str]] = Field(default_factory=list)
    default_target_id: Optional[str] = None

    # WaitEvent 专用
    event_type: str = "NEW_MESSAGE"
    filter_patterns: List[str] = Field(default_factory=list)

    # Delay 专用
    delay_seconds: float = 1.0

    # Extractor 专用
    source_field: str = "prev.output"
    regex: str = ""
    export_vars: Dict[str, str] = Field(default_factory=dict)

    # Subflow 专用
    subflow_graph: Optional[Dict[str, Any]] = None
    subflow_id: Optional[str] = None
    input_vars: Dict[str, str] = Field(default_factory=dict)
    output_vars: Dict[str, str] = Field(default_factory=dict)

    # Parallel 专用
    branches: List[Dict[str, Any]] = Field(default_factory=list)
    parallel_mode: str = "all"
    max_concurrency: Optional[int] = None

    @validator("node_type", pre=True)
    def _parse_node_type(cls, v):
        if not v:
            return FlowNodeType.ACTION
        if isinstance(v, FlowNodeType):
            return v
        return FlowNodeType(str(v).lower())
```
并将 `WorkflowStepConfig` 别名化或继承自 `FlowStepConfig`，且在 `SignChatV3` 中增加：
```python
flow_graph: Optional[Dict[str, Any]] = None
steps: Optional[List[FlowStepConfig]] = None
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_flow_step_config.py -v`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add tg_signer/config.py tests/test_flow_step_config.py
git commit -m "feat(flow): add FlowStepConfig polymorphic model and flow_graph field"
```

---

### Task 2: 升级 `GraphNormalizer` 支持双轨模式与全节点转换

**Files:**
- Modify: `tg_signer/core/flow_normalizer.py:35-150`
- Create: `tests/test_flow_normalizer_polymorphic.py`

**Interfaces:**
- Consumes: `SignChatV3`, `FlowStepConfig`, `ExecutionGraph.from_dict`
- Produces: `GraphNormalizer.from_chat` 返回包含各类控制节点的 `ExecutionGraph`

- [ ] **Step 1: 编写 GraphNormalizer 多态节点映射与直通测试**

```python
# tests/test_flow_normalizer_polymorphic.py
from tg_signer.config import FlowNodeType, FlowStepConfig, SignChatV3
from tg_signer.core.flow_models import (
    ConditionNode,
    DelayNode,
    ExtractorNode,
    WaitEventNode,
)
from tg_signer.core.flow_normalizer import GraphNormalizer


def test_normalizer_from_polymorphic_steps():
    chat = SignChatV3(
        chat_id=123,
        steps=[
            FlowStepConfig(
                step_id="step_delay",
                node_type=FlowNodeType.DELAY,
                delay_seconds=2.5,
                next_step_id="step_cond",
            ),
            FlowStepConfig(
                step_id="step_cond",
                node_type=FlowNodeType.CONDITION,
                cases=[{"condition": "vars.ok == true", "target_id": "step_extract"}],
                default_target_id="COMPLETE",
            ),
            FlowStepConfig(
                step_id="step_extract",
                node_type=FlowNodeType.EXTRACTOR,
                regex=r"code=(\d+)",
                next_step_id="COMPLETE",
            ),
        ],
    )
    graph = GraphNormalizer.from_chat(chat)
    assert "step_delay" in graph.nodes
    assert isinstance(graph.nodes["step_delay"], DelayNode)
    assert graph.nodes["step_delay"].seconds == 2.5

    assert isinstance(graph.nodes["step_cond"], ConditionNode)
    assert len(graph.nodes["step_cond"].cases) == 1

    assert isinstance(graph.nodes["step_extract"], ExtractorNode)


def test_normalizer_from_flow_graph():
    chat = SignChatV3(
        chat_id=456,
        flow_graph={
            "entry_node_id": "wait_msg",
            "nodes": {
                "wait_msg": {
                    "node_type": "wait_event",
                    "event_type": "NEW_MESSAGE",
                    "filter_patterns": ["signed"],
                    "next_node_id": "_TERMINAL_COMPLETE",
                }
            },
        },
    )
    graph = GraphNormalizer.from_chat(chat)
    assert "wait_msg" in graph.nodes
    assert isinstance(graph.nodes["wait_msg"], WaitEventNode)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_flow_normalizer_polymorphic.py -v`
Expected: FAIL with `AttributeError` or nodes mapped to `ActionNode`

- [ ] **Step 3: 在 `GraphNormalizer` 中实现多态分支转换与 `flow_graph` 直通**

在 `flow_normalizer.py` 中更新 `from_chat`：
```python
@classmethod
def from_chat(cls, chat: SignChatV3) -> ExecutionGraph:
    if getattr(chat, "flow_graph", None):
        return cls._from_flow_graph(chat.flow_graph)
    if getattr(chat, "steps", None) and len(chat.steps) > 0:
        return cls._from_workflow_steps(chat)
    return cls._from_linear_actions(chat)
```
并实现 `_from_flow_graph` 与扩展 `_from_workflow_steps`：
根据 `step.node_type`：
- `FlowNodeType.ACTION` -> `ActionNode`
- `FlowNodeType.CONDITION` -> `ConditionNode(id=step.step_id, cases=step.cases, default_target_id=cls._resolve_sentinel_id(step.default_target_id), ...)`
- `FlowNodeType.WAIT_EVENT` -> `WaitEventNode(id=step.step_id, event_type=step.event_type, filter_patterns=step.filter_patterns, ...)`
- `FlowNodeType.DELAY` -> `DelayNode(id=step.step_id, seconds=step.delay_seconds, ...)`
- `FlowNodeType.EXTRACTOR` -> `ExtractorNode(id=step.step_id, source_field=step.source_field, regex=step.regex, export_vars=step.export_vars, ...)`
- `FlowNodeType.SUBFLOW` -> `SubflowNode(...)`
- `FlowNodeType.PARALLEL` -> `ParallelNode(...)`

- [ ] **Step 4: 运行现有与新增测试验证全部通过**

Run: `pytest tests/test_flow_normalizer_polymorphic.py tests/test_flow_normalizer.py -v`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add tg_signer/core/flow_normalizer.py tests/test_flow_normalizer_polymorphic.py
git commit -m "feat(flow): support polymorphic steps and native flow_graph in GraphNormalizer"
```

---

### Task 3: 后端服务层保存校验与流程预览 API

**Files:**
- Modify: `backend/services/sign_task_config_build.py:100-140`
- Modify: `backend/services/sign_task_config_inspect.py:30-60`
- Modify: `backend/api/routes/sign_tasks_v2.py`
- Create: `tests/test_sign_task_config_flow.py`

**Interfaces:**
- Consumes: `GraphNormalizer.to_mermaid`, `GraphNormalizer.validate_graph`
- Produces: `POST /api/v2/sign-tasks/preview-flow`

- [ ] **Step 1: 编写配置保存透传与预览端点测试**

```python
# tests/test_sign_task_config_flow.py
from backend.services.sign_task_config_build import build_sign_task_config
from backend.services.sign_task_config_inspect import task_requires_updates


def test_build_config_preserves_flow_graph_and_polymorphic_steps():
    chats = [
        {
            "chat_id": 1234,
            "steps": [
                {
                    "step_id": "step_1",
                    "node_type": "delay",
                    "delay_seconds": 3.0,
                    "next_step_id": "COMPLETE",
                }
            ],
            "flow_graph": {"entry_node_id": "s1", "nodes": {}},
        }
    ]
    cfg = build_sign_task_config(account_name="acc1", account_names=["acc1"], chats=chats)
    assert cfg["chats"][0]["steps"][0]["node_type"] == "delay"
    assert cfg["chats"][0]["flow_graph"]["entry_node_id"] == "s1"


def test_task_requires_updates_detects_wait_event():
    cfg = {
        "chats": [
            {
                "chat_id": 1234,
                "steps": [{"step_id": "w1", "node_type": "wait_event"}],
            }
        ]
    }
    assert task_requires_updates(cfg) is True
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_sign_task_config_flow.py -v`
Expected: FAIL

- [ ] **Step 3: 更新服务层构建器与检查器，并在 API 路由中添加 `preview-flow`**

在 `backend/api/routes/sign_tasks_v2.py` 中增加：
```python
@router.post("/preview-flow")
async def preview_flow_graph(chat_payload: Dict[str, Any], current_user=Depends(get_current_user)):
    from tg_signer.config import SignChatV3
    from tg_signer.core.flow_normalizer import GraphNormalizer
    try:
        chat = SignChatV3(**chat_payload)
        graph = GraphNormalizer.from_chat(chat)
        mermaid_code = GraphNormalizer.to_mermaid(graph)
        return {
            "success": True,
            "node_count": len(graph.nodes),
            "entry_node_id": graph.entry_node_id,
            "mermaid": mermaid_code,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "mermaid": ""}
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_sign_task_config_flow.py -v`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add backend/services/sign_task_config_build.py backend/services/sign_task_config_inspect.py backend/api/routes/sign_tasks_v2.py tests/test_sign_task_config_flow.py
git commit -m "feat(api): preserve flow fields and add preview-flow endpoint"
```

---

### Task 4: 前端类型支持与 Mermaid 流程图预览组件

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/task-form-payload.ts`
- Create: `frontend/src/components/tasks/FlowMermaidPreviewModal.vue`
- Create: `frontend/src/test/flow-payload.spec.ts`

**Interfaces:**
- Consumes: `/sign-tasks/preview-flow` API
- Produces: `FlowMermaidPreviewModal.vue` 实时展示流程图拓扑

- [ ] **Step 1: 编写前端 payload 序列化测试**

```typescript
// frontend/src/test/flow-payload.spec.ts
import { describe, it, expect } from 'vitest'
import { buildTaskPayload } from '@/lib/task-form-payload'

describe('flow payload serializer', () => {
  it('preserves steps and flow_graph on chats if present', () => {
    const input: any = {
      accountName: 'test_acc',
      targetChats: [
        {
          chatId: 12345,
          chatName: 'Test Chat',
          steps: [
            { step_id: 's1', node_type: 'delay', delay_seconds: 5, next_step_id: 'COMPLETE' }
          ]
        }
      ],
      actions: []
    }
    const payload = buildTaskPayload(input)
    expect(payload.chats[0].steps).toBeDefined()
    expect(payload.chats[0].steps[0].node_type).toBe('delay')
  })
})
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pnpm test frontend/src/test/flow-payload.spec.ts`
Expected: FAIL

- [ ] **Step 3: 更新前端模型与组件实现**

1. 在 `frontend/src/lib/types.ts` 中加入 `FlowStepConfig` 与 `SignTaskChat.flow_graph`、`SignTaskChat.steps`。
2. 在 `frontend/src/lib/task-form-payload.ts` 中透传 `steps` 与 `flow_graph`。
3. 创建 `frontend/src/components/tasks/FlowMermaidPreviewModal.vue`：
   接收 `chat` 对象，向 `/api/v2/sign-tasks/preview-flow` 发送请求，获取并使用 `mermaid.render` 动态渲染流程图。

- [ ] **Step 4: 运行前端单元测试**

Run: `pnpm test frontend/src/test/flow-payload.spec.ts`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add frontend/src/lib/types.ts frontend/src/lib/task-form-payload.ts frontend/src/components/tasks/FlowMermaidPreviewModal.vue frontend/src/test/flow-payload.spec.ts
git commit -m "feat(frontend): add flow step types, payload serializer and Mermaid preview modal"
```

---

### Task 5: 全流程集成回归与运行时验证

**Files:**
- Create: `tests/test_flow_full_lifecycle.py`

**Interfaces:**
- Consumes: 全流程链路 (`SignChatV3` -> `GraphNormalizer` -> `PulseFlowEngine` -> `TelegramNodeExecutor`)
- Produces: 验证真实任务配置下条件跳转、延迟与事件等待的端到端执行一致性

- [ ] **Step 1: 编写全链路端到端生命周期执行测试**

```python
# tests/test_flow_full_lifecycle.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from tg_signer.config import FlowNodeType, FlowStepConfig, SignChatV3
from tg_signer.core.flow_engine import PulseFlowEngine
from tg_signer.core.flow_normalizer import GraphNormalizer
from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_models import NodeStatus, StepOutcome


@pytest.mark.asyncio
async def test_full_flow_condition_branching_execution():
    # 模拟由配置驱动的条件分支流
    chat = SignChatV3(
        chat_id=888,
        steps=[
            FlowStepConfig(
                step_id="step_action",
                node_type=FlowNodeType.ACTION,
                config={"action": 1, "text": "/status"},
                next_step_id="step_check",
            ),
            FlowStepConfig(
                step_id="step_check",
                node_type=FlowNodeType.CONDITION,
                cases=[{"condition": "'VIP' in prev.output", "target_id": "step_vip"}],
                default_target_id="step_regular",
            ),
            FlowStepConfig(
                step_id="step_vip",
                node_type=FlowNodeType.ACTION,
                config={"action": 1, "text": "/vip_sign"},
                next_step_id="COMPLETE",
            ),
            FlowStepConfig(
                step_id="step_regular",
                node_type=FlowNodeType.ACTION,
                config={"action": 1, "text": "/normal_sign"},
                next_step_id="COMPLETE",
            ),
        ],
    )

    graph = GraphNormalizer.from_chat(chat)
    engine = PulseFlowEngine()
    ctx = ScopedFlowContext()

    executed_nodes = []

    async def mock_executor(node, context):
        executed_nodes.append(node.id)
        if node.id == "step_action":
            return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS, output_text="User is VIP level 3")
        return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS, output_text="OK")

    res = await engine.run(graph, ctx, mock_executor)
    assert res["status"] == "success"
    # 条件应当命中 VIP 分支，跳过 regular 分支
    assert executed_nodes == ["step_action", "step_vip"]
```

- [ ] **Step 2: 运行端到端集成测试**

Run: `pytest tests/test_flow_full_lifecycle.py -v`
Expected: PASS

- [ ] **Step 3: 运行全量测试套件确保无任何回归**

Run: `pytest tests/ -v`
Expected: PASS

- [ ] **Step 4: 提交更改**

```bash
git add tests/test_flow_full_lifecycle.py
git commit -m "test(flow): add end-to-end lifecycle integration test for polymorphic flow configuration"
```

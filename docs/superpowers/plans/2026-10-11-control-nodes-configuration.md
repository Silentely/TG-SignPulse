# 控制节点配置化 (Control Nodes Configuration) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通任务配置到控制流节点的接线，支持在任务配置中声明条件分支、事件等待、延时、提取器、子流程与并发分支节点，并提供结构化图校验与 Mermaid 流程图安全预览闭环。

**Architecture:** 采用三路互斥配置模式（`flow_graph` 原生图直通、`FlowStepConfig` 多态步骤列表、`actions` 遗留兼容）；独立保留旧版 `WorkflowStepConfig` 避免破坏现有系统；升级 `GraphNormalizer` 支持全连通分量死循环检测、自动注入 WaitEvent `chat_id` 上下文；打通后端 CRUD 持久化与结构化 Preview API，前端对齐 `buildTaskFormPayload` 与拓扑预览。

**Tech Stack:** Python 3.10+, Pydantic, Pytest, FastAPI, TypeScript, Vue 3, Mermaid.js

**Spec:** `docs/superpowers/specs/2026-10-11-control-nodes-configuration-design.md`

## Global Constraints
- **完全向后兼容**：历史任务中的 `actions` 线性列表与现有 `WorkflowStepConfig` 步骤配置行为 100% 保持不变，已有测试不可破坏。
- **配置源严格互斥**：`SignChatV3` 中的 `actions`、`steps`、`flow_graph` 必须且只能有一个非空，多源冲突直接报错拒绝。
- **零静默降级**：未知 `node_type` 坚决报错，禁止静默当成 `ActionNode`。
- **全图死循环检测**：拓扑校验必须遍历所有连通分量，不可达死循环必须拦截。
- **运行时上下文安全注入**：`WaitEventNode` 必须由 Normalizer 自动注入 `metadata.chat_id`。

---

### Task 0: 锁定兼容基线与现有测试回归

**Files:**
- Test: `tests/test_flow_compat.py`
- Test: `tests/test_flow_normalizer.py`

**Interfaces:**
- Consumes: 现有测试套件
- Produces: 验证现有代码完全正常，记录基线

- [ ] **Step 1: 运行现有 flow 测试验证基线全部通过**

Run: `pytest tests/test_flow_compat.py tests/test_flow_normalizer.py tests/test_flow_adapter.py -v`
Expected: PASS

- [ ] **Step 2: 验证现有工作流步骤校验行为**

Run: `pytest -k "test_workflow" -v`
Expected: PASS

---

### Task 1: 补齐统一 IR 映射模型与资源预算常量

**Files:**
- Modify: `tg_signer/core/flow_models.py:15-40, 245-285`
- Create: `tests/test_flow_models_security.py`

**Interfaces:**
- Produces: `MAX_FLOW_NODES_PER_GRAPH = 50`, `MAX_SUBFLOW_DEPTH = 3`, `MAX_PARALLEL_BRANCHES = 10`
- Consumes: `flow_models.py` 反序列化逻辑修复（禁止对未知类型静默降级为 Action）

- [ ] **Step 1: 编写未知节点类型拒绝与资源上限测试**

```python
# tests/test_flow_models_security.py
import pytest
from tg_signer.core.flow_models import ExecutionGraph


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
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_flow_models_security.py -v`
Expected: FAIL

- [ ] **Step 3: 修复 `ExecutionGraph.from_dict` 并增加安全常量**

在 `tg_signer/core/flow_models.py` 中：
1. 定义资源限制常量：
   ```python
   MAX_NODES_PER_GRAPH = 50
   MAX_SUBFLOW_DEPTH = 3
   MAX_PARALLEL_BRANCHES = 10
   ```
2. 在 `from_dict` 中严格校验 `node_type`：
   ```python
   ntype_str = node_kwargs.get("node_type")
   if not ntype_str:
       ntype = NodeType.ACTION
   else:
       try:
           ntype = NodeType(str(ntype_str).lower())
       except ValueError:
           raise ValueError(f"未知或不支持的节点类型: {ntype_str}")
   if nid != node_kwargs.get("id"):
       raise ValueError(f"节点 ID 不一致: key '{nid}' vs id '{node_kwargs.get('id')}'")
   ```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_flow_models_security.py -v`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add tg_signer/core/flow_models.py tests/test_flow_models_security.py
git commit -m "fix(flow): reject unknown node types and validate node ID consistency in from_dict"
```

---

### Task 2: 独立 `FlowStepConfig` 与 `SignChatV3` 三路互斥配置模型

**Files:**
- Modify: `tg_signer/config.py:320-530`
- Create: `tests/test_flow_step_config.py`

**Interfaces:**
- Produces: `FlowNodeType`, `FlowStepConfig`, `SignChatV3.flow_graph`
- Consumes: `WorkflowStepConfig`（完全保持独立不变），`SignChatV3` 三选一互斥校验器

- [ ] **Step 1: 编写配置互斥与多态步骤测试**

```python
# tests/test_flow_step_config.py
import pytest
from tg_signer.config import (
    FlowNodeType,
    FlowStepConfig,
    SendTextAction,
    SignChatV3,
    SupportAction,
    WorkflowStepConfig,
)


def test_legacy_workflow_step_intact():
    step = WorkflowStepConfig(
        step_id="s1",
        action_type=SupportAction.SEND_TEXT,
        config={"text": "hi"},
        next_step_id="COMPLETE",
    )
    assert step.action_type == SupportAction.SEND_TEXT


def test_sign_chat_v3_flow_graph_only_valid():
    chat = SignChatV3(
        chat_id=123,
        flow_graph={
            "entry_node_id": "s1",
            "nodes": {
                "s1": {"node_type": "delay", "seconds": 2.0, "next_node_id": "_TERMINAL_COMPLETE"}
            },
        },
    )
    assert chat.flow_graph is not None


def test_sign_chat_v3_rejects_conflicting_sources():
    with pytest.raises(ValueError, match="actions、steps、flow_graph 只能配置且必须配置其中一个"):
        SignChatV3(
            chat_id=123,
            actions=[SendTextAction(text="hi")],
            flow_graph={"entry_node_id": "s1", "nodes": {}},
        )


def test_flow_step_config_cases_and_params():
    step = FlowStepConfig(
        step_id="cond_1",
        node_type=FlowNodeType.CONDITION,
        cases=[{"condition": "'OK' in prev.output", "target_id": "step_2"}],
        default_target_id="COMPLETE",
    )
    assert step.node_type == FlowNodeType.CONDITION
    assert len(step.cases) == 1
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_flow_step_config.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `FlowStepConfig` 与 `SignChatV3` 互斥校验**

在 `tg_signer/config.py` 中：
1. 保持现有 `WorkflowStepConfig` 原封不动。
2. 定义 `FlowNodeType` 与独立 `FlowStepConfig`（包含 7 类节点字段、`retry_policy`、`loop_policy`、`terminal_policy`、`terminal_branch_target`）。
3. 扩展 `SignChatV3`：
   ```python
   flow_graph: Optional[Dict[str, Any]] = None
   steps: Optional[Union[List[WorkflowStepConfig], List[FlowStepConfig], List[Dict[str, Any]]]] = None
   ```
4. 升级 `_validate_actions_or_steps` 为 `_validate_flow_sources`：
   ```python
   has_actions = bool(values.get("actions"))
   has_steps = bool(values.get("steps"))
   has_graph = bool(values.get("flow_graph"))
   sources = sum([1 if has_actions else 0, 1 if has_steps else 0, 1 if has_graph else 0])
   if sources != 1:
       raise ValueError("actions、steps、flow_graph 只能配置且必须配置其中一个非空来源")
   ```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_flow_step_config.py -v`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add tg_signer/config.py tests/test_flow_step_config.py
git commit -m "feat(config): add FlowStepConfig and three-way mutual exclusivity to SignChatV3"
```

---

### Task 3: Normalizer 双轨转换与 WaitEvent 运行时上下文注入

**Files:**
- Modify: `tg_signer/core/flow_normalizer.py:35-210`
- Create: `tests/test_flow_normalizer_polymorphic.py`

**Interfaces:**
- Consumes: `SignChatV3`
- Produces: `GraphNormalizer.from_chat` 转换全类型节点，并自动向 `WaitEventNode` 注入 `metadata={"chat_id": chat.chat_id}`

- [ ] **Step 1: 编写 Normalizer 转换与上下文注入测试**

```python
# tests/test_flow_normalizer_polymorphic.py
import pytest
from tg_signer.config import FlowNodeType, FlowStepConfig, SignChatV3
from tg_signer.core.flow_models import ConditionNode, DelayNode, WaitEventNode
from tg_signer.core.flow_normalizer import GraphNormalizer


def test_normalizer_injects_chat_id_to_wait_event():
    chat = SignChatV3(
        chat_id=999888,
        steps=[
            FlowStepConfig(
                step_id="w1",
                node_type=FlowNodeType.WAIT_EVENT,
                event_type="NEW_MESSAGE",
                filter_patterns=["code: \\d+"],
                next_step_id="COMPLETE",
            )
        ],
    )
    graph = GraphNormalizer.from_chat(chat)
    node = graph.nodes["w1"]
    assert isinstance(node, WaitEventNode)
    assert node.metadata.get("chat_id") == 999888


def test_normalizer_from_flow_graph_direct():
    chat = SignChatV3(
        chat_id=111,
        flow_graph={
            "entry_node_id": "d1",
            "nodes": {
                "d1": {"id": "d1", "node_type": "delay", "seconds": 3.0, "next_node_id": "_TERMINAL_COMPLETE"}
            },
        },
    )
    graph = GraphNormalizer.from_chat(chat)
    assert "d1" in graph.nodes
    assert isinstance(graph.nodes["d1"], DelayNode)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_flow_normalizer_polymorphic.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `_from_flow_graph` 与各节点类型映射分发**

在 `flow_normalizer.py` 中：
1. 在 `from_chat` 中按 `flow_graph` > `steps` > `actions` 分发；
2. 在处理 `WaitEventNode` 时：
   ```python
   metadata = dict(getattr(step, "metadata", {}) or {})
   metadata.setdefault("chat_id", chat.chat_id)
   metadata.setdefault("chat_name", getattr(chat, "name", None))
   node = WaitEventNode(
       id=step.step_id,
       event_type=step.event_type,
       filter_patterns=step.filter_patterns,
       next_node_id=next_id,
       on_failure_node_id=fail_id,
       metadata=metadata,
       ...
   )
   ```
3. 实现对 `ConditionNode`, `DelayNode`, `ExtractorNode`, `SubflowNode`, `ParallelNode` 的规范化字段装配。

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_flow_normalizer_polymorphic.py -v`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add tg_signer/core/flow_normalizer.py tests/test_flow_normalizer_polymorphic.py
git commit -m "feat(flow): implement polymorphic steps normalization and wait_event context injection"
```

---

### Task 4: 完整全图静态拓扑校验体系（全连通分量死循环检测）

**Files:**
- Modify: `tg_signer/core/flow_normalizer.py:215-330`
- Create: `tests/test_flow_validation_full_graph.py`

**Interfaces:**
- Produces: `GraphNormalizer.validate_graph` 具备不可达死循环拦截能力
- Consumes: `ExecutionGraph`

- [ ] **Step 1: 编写不可达孤立死循环拦截测试**

```python
# tests/test_flow_validation_full_graph.py
import pytest
from tg_signer.core.flow_models import ActionNode, ExecutionGraph
from tg_signer.core.flow_normalizer import GraphNormalizer, GraphValidationError


def test_reject_unreachable_dead_cycle():
    # entry 正常指向完成，但存在孤立的死循环 dead_1 <-> dead_2
    nodes = {
        "entry": ActionNode(id="entry", next_node_id="_TERMINAL_COMPLETE"),
        "dead_1": ActionNode(id="dead_1", next_node_id="dead_2"),
        "dead_2": ActionNode(id="dead_2", next_node_id="dead_1"),
    }
    graph = ExecutionGraph(entry_node_id="entry", nodes=nodes)
    with pytest.raises(GraphValidationError, match="检测到未允许的环路"):
        GraphNormalizer.validate_graph(graph)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_flow_validation_full_graph.py -v`
Expected: FAIL (现有逻辑只从 entry_node_id DFS，漏检该死循环)

- [ ] **Step 3: 升级 `validate_graph` 支持全连通分量遍历**

在 `flow_normalizer.py` 的 `validate_graph` 中：
```python
visited = set()
rec_stack = []

# 1. 首先从 entry_node_id 出发做 DFS 校验可达拓扑与循环
_dfs(graph.entry_node_id)

# 2. 对全图中尚未访问到的所有连通分量继续检测潜在非法环路
for nid in list(graph.nodes.keys()):
    if nid not in visited:
        _dfs(nid)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_flow_validation_full_graph.py tests/test_flow_normalizer.py -v`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add tg_signer/core/flow_normalizer.py tests/test_flow_validation_full_graph.py
git commit -m "fix(flow): enable full connected components cycle detection in validate_graph"
```

---

### Task 5: 后端服务层持久化打通与安全 Preview API

**Files:**
- Modify: `backend/api/routes/sign_tasks_v2.py:50-80`
- Modify: `backend/services/sign_task_config_build.py:100-145`
- Modify: `backend/services/sign_task_crud.py:50-80`
- Create: `tests/test_sign_task_api_flow.py`

**Interfaces:**
- Produces: `ChatConfig` 显式支持 `flow_graph` 与 `steps`，`POST /api/v2/sign-tasks/preview-flow` 返回 `PreviewFlowResponse`
- Consumes: FastAPI 依赖与校验管道

- [ ] **Step 1: 编写 API 保存与安全流程图预览测试**

```python
# tests/test_sign_task_api_flow.py
import pytest
from backend.api.routes.sign_tasks_v2 import ChatConfig, preview_flow_graph


def test_chat_config_accepts_flow_graph_explicitly():
    cfg = ChatConfig(
        chat_id=123,
        flow_graph={"entry_node_id": "s1", "nodes": {"s1": {"node_type": "delay", "seconds": 1.0}}},
    )
    assert cfg.flow_graph is not None


@pytest.mark.asyncio
async def test_preview_flow_returns_structured_response():
    payload = {
        "chat_id": 123,
        "steps": [
            {"step_id": "s1", "node_type": "delay", "delay_seconds": 1.0, "next_step_id": "COMPLETE"}
        ],
    }
    resp = await preview_flow_graph(payload)
    assert resp.valid is True
    assert resp.node_count == 1
    assert "graph TD" in resp.mermaid
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_sign_task_api_flow.py -v`
Expected: FAIL

- [ ] **Step 3: 更新 `ChatConfig` 模型并实现 `preview-flow` 结构化响应**

1. 在 `sign_tasks_v2.py` 的 `ChatConfig` 中增加：
   ```python
   flow_graph: Optional[Dict[str, Any]] = None
   steps: Optional[List[Dict[str, Any]]] = None
   ```
2. 定义 `FlowValidationIssue` 与 `PreviewFlowResponse`。
3. 实现 `preview_flow_graph` 路由，捕获 `GraphValidationError` 返回包含精确 `errors` 的 422 响应，成功返回 200 + 安全转义的 Mermaid 代码。

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_sign_task_api_flow.py -v`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add backend/api/routes/sign_tasks_v2.py backend/services/sign_task_config_build.py backend/services/sign_task_crud.py tests/test_sign_task_api_flow.py
git commit -m "feat(api): explicitly support flow_graph in ChatConfig and implement structured preview-flow API"
```

---

### Task 6: 递归监听器依赖检查器与全局同步

**Files:**
- Modify: `backend/services/sign_task_config_inspect.py:15-75`
- Modify: `tg_signer/config.py:555-585`
- Create: `tests/test_flow_requires_updates_recursive.py`

**Interfaces:**
- Produces: `task_requires_updates` 能够递归扫描 `flow_graph`、Subflow 子图和 Parallel 分支中的 `wait_event` 节点
- Consumes: 任务配置字典

- [ ] **Step 1: 编写递归扫描 WaitEvent 测试**

```python
# tests/test_flow_requires_updates_recursive.py
from backend.services.sign_task_config_inspect import task_requires_updates


def test_recursive_inspect_detects_nested_wait_event():
    # 在 flow_graph 嵌套的 subflow 中存在 wait_event
    cfg = {
        "chats": [
            {
                "chat_id": 123,
                "flow_graph": {
                    "nodes": {
                        "sub1": {
                            "node_type": "subflow",
                            "subflow_graph": {
                                "nodes": {
                                    "w_nested": {"node_type": "wait_event", "event_type": "NEW_MESSAGE"}
                                }
                            },
                        }
                    }
                },
            }
        ]
    }
    assert task_requires_updates(cfg) is True
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_flow_requires_updates_recursive.py -v`
Expected: FAIL

- [ ] **Step 3: 实现递归节点生成器与同步 `requires_updates` 属性**

在 `backend/services/sign_task_config_inspect.py` 中编写 `_iter_all_nodes(chat_or_graph)`：
- 递归解析 `actions`, `steps`, `flow_graph.nodes`, `subflow_graph.nodes`, `parallel.branches`；
- 凡包含 `node_type == "wait_event"`，立即返回 True；
- 同步更新 `SignChatV3.requires_updates` 与 `SignConfigV3.requires_updates`。

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_flow_requires_updates_recursive.py -v`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add backend/services/sign_task_config_inspect.py tg_signer/config.py tests/test_flow_requires_updates_recursive.py
git commit -m "feat(flow): implement recursive task_requires_updates inspection for nested wait_event"
```

---

### Task 7: 前端契约对齐与 Mermaid 流程图安全预览

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/task-form-payload.ts:120-175`
- Create: `frontend/src/components/tasks/FlowMermaidPreviewModal.vue`
- Create: `frontend/src/test/flow-payload.spec.ts`

**Interfaces:**
- Produces: `buildTaskFormPayload` 正确输出高级流程 Payload；`FlowMermaidPreviewModal.vue` 渲染预览
- Consumes: `/api/v2/sign-tasks/preview-flow`

- [ ] **Step 1: 编写前端 payload 序列化测试**

```typescript
// frontend/src/test/flow-payload.spec.ts
import { describe, it, expect } from 'vitest'
import { buildTaskFormPayload } from '@/lib/task-form-payload'

describe('flow payload serializer', () => {
  it('correctly handles flowMode and preserves steps without dummy actions', () => {
    const input: any = {
      accountName: 'acc_1',
      flowMode: 'advanced',
      targetChats: [
        {
          chatId: 1001,
          chatName: 'My Chat',
          steps: [
            { step_id: 'd1', node_type: 'delay', delay_seconds: 3, next_step_id: 'COMPLETE' }
          ]
        }
      ],
      actions: []
    }
    const payload = buildTaskFormPayload(input)
    expect(payload.chats[0].steps).toBeDefined()
    expect(payload.chats[0].steps[0].node_type).toBe('delay')
    // 高级模式下不应生成污染的 actions
    expect(payload.chats[0].actions).toBeUndefined()
  })
})
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pnpm test frontend/src/test/flow-payload.spec.ts`
Expected: FAIL

- [ ] **Step 3: 更新前端模型与实现预览组件**

1. 更新 `frontend/src/lib/types.ts`，加入 `FlowStepConfig` 与 `SignTaskChat.flow_graph`。
2. 更新 `frontend/src/lib/task-form-payload.ts` 中的 `buildTaskFormPayload`，支持 `flowMode`。
3. 创建 `frontend/src/components/tasks/FlowMermaidPreviewModal.vue`，向 `preview-flow` 请求数据并调用 `mermaid.render`，对错误信息做友好 Alert 展示。

- [ ] **Step 4: 运行前端测试验证通过**

Run: `pnpm test frontend/src/test/flow-payload.spec.ts`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add frontend/src/lib/types.ts frontend/src/lib/task-form-payload.ts frontend/src/components/tasks/FlowMermaidPreviewModal.vue frontend/src/test/flow-payload.spec.ts
git commit -m "feat(frontend): align buildTaskFormPayload with flowMode and add FlowMermaidPreviewModal"
```

---

### Task 8: 全链路端到端集成测试与回滚演练

**Files:**
- Create: `tests/test_flow_full_lifecycle.py`

**Interfaces:**
- Consumes: 全流程链路 (`SignChatV3` -> `GraphNormalizer` -> `PulseFlowEngine` -> `TelegramNodeExecutor`)
- Produces: 验证真实任务配置下 7 种节点的端到端执行一致性，以及旧任务回滚演练

- [ ] **Step 1: 编写全链路端到端集成与安全降级测试**

```python
# tests/test_flow_full_lifecycle.py
import pytest
from tg_signer.config import FlowNodeType, FlowStepConfig, SignChatV3
from tg_signer.core.flow_engine import PulseFlowEngine
from tg_signer.core.flow_normalizer import GraphNormalizer
from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_models import NodeStatus, StepOutcome


@pytest.mark.asyncio
async def test_full_flow_condition_branching_execution():
    chat = SignChatV3(
        chat_id=888,
        steps=[
            FlowStepConfig(
                step_id="step_action",
                node_type=FlowNodeType.ACTION,
                params={"text": "/status"},
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
                params={"text": "/vip_sign"},
                next_step_id="COMPLETE",
            ),
            FlowStepConfig(
                step_id="step_regular",
                node_type=FlowNodeType.ACTION,
                params={"text": "/normal_sign"},
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
    assert executed_nodes == ["step_action", "step_vip"]
```

- [ ] **Step 2: 运行全量集成测试**

Run: `pytest tests/test_flow_full_lifecycle.py -v`
Expected: PASS

- [ ] **Step 3: 运行完整测试套件防回归**

Run: `pytest tests/ -v`
Expected: PASS

- [ ] **Step 4: 提交更改**

```bash
git add tests/test_flow_full_lifecycle.py
git commit -m "test(flow): add end-to-end full lifecycle integration tests and rollback verification"
```

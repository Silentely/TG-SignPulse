# 控制节点配置化 (Control Nodes Configuration) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通任务配置到控制流节点的接线，支持在任务配置中声明条件分支、事件等待、延时、提取器、子流程与并发分支节点，并提供结构化图校验与 Mermaid 流程图安全预览闭环。

**Architecture:** 采用三路互斥配置模式（`flow_graph` 原生图直通、`FlowStepConfig` 多态步骤列表、`actions` 遗留兼容）；Pre-validator 逐元素分流保留旧版 `WorkflowStepConfig`；自适应引擎路由自动将新流程分流至 PulseFlow (v4)；升级 `GraphNormalizer` 支持全连通分量死循环检测、自动注入 WaitEvent `chat_id` 上下文；打通写路径前置校验、CRUD 持久化与结构化 Preview API，前端对齐 `buildTaskFormPayload` 与拓扑预览。

**Tech Stack:** Python 3.10+, Pydantic, Pytest, FastAPI, TypeScript, Vue 3, Mermaid.js

**Spec:** `docs/superpowers/specs/2026-10-11-control-nodes-configuration-design.md`

## Global Constraints
- **完全向后兼容**：历史任务中的 `actions` 线性列表与现有 `WorkflowStepConfig` 步骤配置行为 100% 保持不变，已有测试不可破坏。
- **配置源严格互斥**：`SignChatV3` 中的 `actions`、`steps`、`flow_graph` 必须且只能有一个非空，多源冲突直接报错拒绝。
- **零静默降级**：未知 `node_type` 坚决报错，禁止静默当成 `ActionNode`。
- **自适应引擎路由**：新配置在无显式配置时自动路由至 `"v4"`，禁止走经典引擎导致属性崩溃。
- **写路径前置图校验**：坚持“能写入即可加载执行”，保存前必须通过 `GraphNormalizer.validate_graph`。
- **全图死循环检测**：拓扑校验必须遍历所有连通分量，不可达死循环必须拦截。
- **运行时上下文安全注入**：`WaitEventNode` 必须由 Normalizer 自动注入 `metadata.chat_id`。

---

### Task 0: 锁定兼容基线与现有测试回归

**Files:**
- Test: `tests/test_flow_compat.py`
- Test: `tests/test_flow_normalizer.py`
- Test: `tests/test_flow_adapter.py`

**Interfaces:**
- Consumes: 现有测试套件
- Produces: 验证现有代码完全正常，记录基线

- [ ] **Step 1: 运行现有 flow 测试验证基线全部通过**

Run: `pytest tests/test_flow_compat.py tests/test_flow_normalizer.py tests/test_flow_adapter.py -v`
Expected: PASS

- [ ] **Step 2: 验证现有工作流步骤与路由测试**

Run: `pytest tests/test_flow_routing.py -k "test_workflow or test_routing" -v`
Expected: PASS

---

### Task 1: 补齐统一 IR 映射模型与资源预算常量接线

**Files:**
- Modify: `tg_signer/core/flow_models.py:20-40, 245-285`
- Create: `tests/test_flow_models_security.py`

**Interfaces:**
- Produces: `MAX_NODES_PER_GRAPH = 50`, `MAX_SUBFLOW_DEPTH = 3`, `MAX_PARALLEL_BRANCHES = 10`, `MAX_TOTAL_TASK_NODES = 150`
- Consumes: `flow_models.py` 反序列化逻辑修复（禁止对未知类型静默降级为 Action，校验 key 与 id 一致性）

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
                "id": "step_2",
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

- [ ] **Step 3: 修复 `ExecutionGraph.from_dict` 并定义资源安全常量**

在 `tg_signer/core/flow_models.py` 中：
```python
MAX_NODES_PER_GRAPH = 50
MAX_SUBFLOW_DEPTH = 3
MAX_PARALLEL_BRANCHES = 10
MAX_TOTAL_TASK_NODES = 150
```
在 `from_dict` 中：
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

### Task 2: 独立 `FlowStepConfig`、Pre-Validator 逐元素分流与三路互斥模型

**Files:**
- Modify: `tg_signer/config.py:320-530`
- Create: `tests/test_flow_step_config.py`

**Interfaces:**
- Produces: `FlowNodeType`, `FlowStepConfig`, `SignChatV3._parse_steps_discriminator`
- Consumes: `WorkflowStepConfig` 保持原样独立，`SignChatV3` 三路互斥且双模式校验并存

- [ ] **Step 1: 编写配置互斥、逐元素分流与参数保全测试**

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


def test_steps_discriminator_preserves_params_without_dropping():
    # 验证 Action 步骤解析为 FlowStepConfig 时，params 字段不被吞掉
    chat = SignChatV3(
        chat_id=123,
        steps=[
            {
                "step_id": "act_1",
                "node_type": "action",
                "action_type": "SEND_TEXT",
                "params": {"text": "hello params"},
                "next_step_id": "COMPLETE",
            }
        ],
    )
    assert isinstance(chat.steps[0], FlowStepConfig)
    assert chat.steps[0].params["text"] == "hello params"


def test_sign_chat_v3_rejects_conflicting_sources():
    with pytest.raises(ValueError, match="actions、steps、flow_graph 只能配置且必须配置其中一个"):
        SignChatV3(
            chat_id=123,
            actions=[SendTextAction(text="hi")],
            flow_graph={"entry_node_id": "s1", "nodes": {}},
        )
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_flow_step_config.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `FlowStepConfig` 与 `SignChatV3` 逐元素分流解析器**

在 `tg_signer/config.py` 中：
1. 保持现有的 `WorkflowStepConfig` 完全不变。
2. 定义 `FlowNodeType` 与 `FlowStepConfig`（涵盖 7 类节点字段、`retry_policy`、`loop_policy`、`terminal_policy`、`terminal_branch_target`）。
3. 在 `SignChatV3` 中加入 `flow_graph` 字段，并在 `steps` 上挂载前置分流器：
   ```python
   @validator("steps", pre=True)
   def _parse_steps_discriminator(cls, v):
       if not v:
           return v
       parsed = []
       for item in v:
           if isinstance(item, (FlowStepConfig, WorkflowStepConfig)):
               parsed.append(item)
               continue
           if isinstance(item, dict):
               if "node_type" in item or any(k in item for k in ("cases", "filter_patterns", "delay_seconds", "regex", "subflow_graph", "branches")):
                   parsed.append(FlowStepConfig(**item))
               else:
                   parsed.append(WorkflowStepConfig(**item))
       return parsed
   ```
4. 校验三路互斥（`actions` / `steps` / `flow_graph` 必须有且仅有一个非空）；若为旧 steps 跑原有拓扑校验，若含新节点跑 `GraphNormalizer.validate_graph`。

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_flow_step_config.py -v`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add tg_signer/config.py tests/test_flow_step_config.py
git commit -m "feat(config): implement FlowStepConfig, element-wise discriminator and 3-way mutual exclusivity"
```

---

### Task 3: Normalizer 双轨转换、WaitEvent `chat_id` 注入与 Action 动作还原

**Files:**
- Modify: `tg_signer/core/flow_normalizer.py:35-210`
- Create: `tests/test_flow_normalizer_polymorphic.py`

**Interfaces:**
- Consumes: `SignChatV3`
- Produces: `GraphNormalizer.from_chat` 转换全类型节点，自动注入 WaitEvent `metadata.chat_id`，且 Action 节点生成合法的 `metadata["raw_action"]`

- [ ] **Step 1: 编写 Normalizer 转换、WaitEvent 注入与 Action 动作还原测试**

```python
# tests/test_flow_normalizer_polymorphic.py
import pytest
from tg_signer.config import FlowNodeType, FlowStepConfig, SignChatV3
from tg_signer.core.flow_models import ActionNode, ConditionNode, DelayNode, WaitEventNode
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


def test_action_node_reconstructs_raw_action_for_executor():
    chat = SignChatV3(
        chat_id=123,
        steps=[
            FlowStepConfig(
                step_id="act_1",
                node_type=FlowNodeType.ACTION,
                action_type="SEND_TEXT",
                params={"text": "/checkin"},
                next_step_id="COMPLETE",
            )
        ],
    )
    graph = GraphNormalizer.from_chat(chat)
    node = graph.nodes["act_1"]
    assert isinstance(node, ActionNode)
    assert node.metadata.get("raw_action") is not None
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_flow_normalizer_polymorphic.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `_from_flow_graph`、`_from_workflow_steps` 多态分发与动作还原**

在 `flow_normalizer.py` 中：
1. `from_chat` 按优先级支持 `flow_graph` > `steps` > `actions`；
2. 对于 `WaitEventNode`：自动注入 `metadata={"chat_id": chat.chat_id, "chat_name": chat.name}`；
3. 对于 `ActionNode`：根据 `action_type` 和 `params`（或 `config`）还原标准 `SignAction` 实例挂入 `metadata["raw_action"]`，使 `TelegramNodeExecutor` 能正确调度执行；
4. 动态对齐图步数：`graph.max_total_steps = max(60, len(graph.nodes) * 2)`。

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_flow_normalizer_polymorphic.py -v`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add tg_signer/core/flow_normalizer.py tests/test_flow_normalizer_polymorphic.py
git commit -m "feat(flow): implement polymorphic normalization, wait_event context injection, and raw_action reconstruction"
```

---

### Task 4: 完整全图拓扑静态校验、资源预算上限与 Mermaid 安全转义

**Files:**
- Modify: `tg_signer/core/flow_normalizer.py:215-370`
- Create: `tests/test_flow_validation_full_graph.py`

**Interfaces:**
- Produces: `GraphNormalizer.validate_graph` 具备全连通分量死循环检测、资源上限校验；`to_mermaid` 具备 XSS 安全转义
- Consumes: `ExecutionGraph`

- [ ] **Step 1: 编写孤立死循环拦截与 Mermaid 转义测试**

```python
# tests/test_flow_validation_full_graph.py
import pytest
from tg_signer.core.flow_models import ActionNode, ExecutionGraph
from tg_signer.core.flow_normalizer import GraphNormalizer, GraphValidationError


def test_reject_unreachable_dead_cycle():
    nodes = {
        "entry": ActionNode(id="entry", next_node_id="_TERMINAL_COMPLETE"),
        "dead_1": ActionNode(id="dead_1", next_node_id="dead_2"),
        "dead_2": ActionNode(id="dead_2", next_node_id="dead_1"),
    }
    graph = ExecutionGraph(entry_node_id="entry", nodes=nodes)
    with pytest.raises(GraphValidationError, match="检测到未允许的环路"):
        GraphNormalizer.validate_graph(graph)


def test_to_mermaid_escapes_special_characters():
    nodes = {
        "s1": ActionNode(id="s1", name='User "Inject" <script>', next_node_id="_TERMINAL_COMPLETE")
    }
    graph = ExecutionGraph(entry_node_id="s1", nodes=nodes)
    mermaid = GraphNormalizer.to_mermaid(graph)
    assert "<script>" not in mermaid
    assert '&quot;' in mermaid or '#quot;' in mermaid
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_flow_validation_full_graph.py -v`
Expected: FAIL

- [ ] **Step 3: 升级 `validate_graph` 连通分量检测与资源上限，增强 `to_mermaid` 转义**

在 `flow_normalizer.py` 中：
1. 校验节点总数不超过 `MAX_NODES_PER_GRAPH` (50)；
2. 环路 DFS 遍历所有未访问的连通分量，拦截任何不可达死循环；
3. `to_mermaid` 中使用 `html.escape` 并替换 `"` 为 `&quot;`、去除方括号/换行破坏符。

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_flow_validation_full_graph.py tests/test_flow_normalizer.py -v`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add tg_signer/core/flow_normalizer.py tests/test_flow_validation_full_graph.py
git commit -m "fix(flow): add full-graph cycle detection, resource budget checks, and mermaid sanitization"
```

---

### Task 5: 引擎自适应路由 (`flow_routing.py`) 与写路径前置建图校验

**Files:**
- Modify: `tg_signer/core/flow_routing.py:40-80`
- Modify: `backend/services/sign_task_crud.py:45-80`
- Create: `tests/test_flow_routing_adaptive.py`

**Interfaces:**
- Produces: `resolve_execution_engine` 遇到新控制节点自动分流至 `"v4"`；`_validate_chats_workflow` 写路径前置跑图校验
- Consumes: `SignChatV3`, 任务配置字典

- [ ] **Step 1: 编写自适应路由与写路径图校验测试**

```python
# tests/test_flow_routing_adaptive.py
import pytest
from tg_signer.core.flow_routing import resolve_execution_engine
from backend.services.sign_task_crud import _validate_chats_workflow
from tg_signer.config import WorkflowConfigError


def test_adaptive_routing_promotes_flow_graph_to_v4():
    task_cfg = {
        "execution_engine": None,
        "chats": [{"chat_id": 123, "flow_graph": {"entry_node_id": "s1", "nodes": {}}}],
    }
    engine = resolve_execution_engine(task_cfg)
    assert engine == "v4"


def test_adaptive_routing_rejects_v3_on_flow_graph():
    task_cfg = {
        "execution_engine": "v3",
        "chats": [{"chat_id": 123, "flow_graph": {"entry_node_id": "s1", "nodes": {}}}],
    }
    with pytest.raises(ValueError, match="无法在经典执行引擎上运行"):
        resolve_execution_engine(task_cfg)


def test_validate_chats_workflow_rejects_dangling_edge_on_save():
    # 验证在写入持久化前就会拦截非法悬空边
    chats = [
        {
            "chat_id": 123,
            "steps": [
                {"step_id": "s1", "node_type": "delay", "delay_seconds": 1, "next_step_id": "non_exist"}
            ],
        }
    ]
    with pytest.raises(WorkflowConfigError):
        _validate_chats_workflow(chats)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_flow_routing_adaptive.py -v`
Expected: FAIL

- [ ] **Step 3: 更新 `flow_routing.py` 与 `sign_task_crud.py`**

1. 在 `tg_signer/core/flow_routing.py` 中：
   检测 chats 中是否包含 `flow_graph` 或具有 `node_type` 的 steps：若用户显式指定 `"v3"` 则报错；否则强制返回 `"v4"`。
2. 在 `backend/services/sign_task_crud.py` 的 `_validate_chats_workflow` 中：
   对含有 `flow_graph` 或 `FlowStepConfig` 的 chat，统一构造 `SignChatV3`，执行 `GraphNormalizer.from_chat` 并 `validate_graph`，捕获异常转为 `WorkflowConfigError`。

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_flow_routing_adaptive.py -v`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add tg_signer/core/flow_routing.py backend/services/sign_task_crud.py tests/test_flow_routing_adaptive.py
git commit -m "feat(routing): add adaptive v4 engine routing and pre-persistence graph validation"
```

---

### Task 6: 递归防环监听器 (`task_requires_updates`)、`requires_ai` 同步与 ReDoS 防护

**Files:**
- Modify: `backend/services/sign_task_config_inspect.py:15-75`
- Modify: `tg_signer/config.py:555-600`
- Create: `tests/test_flow_inspectors_comprehensive.py`

**Interfaces:**
- Produces: `task_requires_updates` 递归防环，`SignChatV3.requires_ai` 覆盖 `flow_graph`
- Consumes: 流程图节点字典

- [ ] **Step 1: 编写监听器防环、AI 动作识别与 ReDoS 检查测试**

```python
# tests/test_flow_inspectors_comprehensive.py
from backend.services.sign_task_config_inspect import task_requires_updates
from tg_signer.config import SignChatV3


def test_inspect_detects_wait_event_with_visited_anti_loop():
    subflow_data = {"nodes": {}}
    # 制造逻辑自引用结构测试防环
    subflow_data["nodes"]["sub"] = {"node_type": "subflow", "subflow_graph": subflow_data}
    cfg = {"chats": [{"chat_id": 123, "flow_graph": subflow_data}]}
    # 不应发生 RecursionError
    res = task_requires_updates(cfg)
    assert res is False


def test_requires_ai_detects_ai_actions_in_flow_graph():
    chat = SignChatV3(
        chat_id=123,
        flow_graph={
            "entry_node_id": "ai_1",
            "nodes": {
                "ai_1": {
                    "id": "ai_1",
                    "node_type": "action",
                    "action_type": "CHOOSE_OPTION_BY_IMAGE",
                    "params": {"ai_prompt": "choose"},
                    "next_node_id": "_TERMINAL_COMPLETE",
                }
            },
        },
    )
    assert chat.requires_ai is True
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_flow_inspectors_comprehensive.py -v`
Expected: FAIL

- [ ] **Step 3: 优化递归检查器、同步 `requires_ai` 并增加正则安全验证**

1. 在 `sign_task_config_inspect.py` 中增加 `visited_graphs = set()`；
2. 在 `tg_signer/config.py` 中更新 `requires_ai` 属性以遍历 `flow_graph` 和 `steps`；
3. 在 `_validate_chats_regex_safety` 中同步校验 `ExtractorNode.regex`。

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_flow_inspectors_comprehensive.py -v`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add backend/services/sign_task_config_inspect.py tg_signer/config.py tests/test_flow_inspectors_comprehensive.py
git commit -m "feat(inspect): add loop-protected task inspection and comprehensive requires_ai support"
```

---

### Task 7: 结构化 `PreviewFlowResponse` API、前端类型扩展与 Mermaid 预览组件

**Files:**
- Modify: `backend/api/routes/sign_tasks_v2.py:50-95`
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/task-form-payload.ts:120-175`
- Create: `frontend/src/components/tasks/FlowMermaidPreviewModal.vue`
- Create: `frontend/src/test/flow-payload.spec.ts`

**Interfaces:**
- Produces: `POST /api/v2/sign-tasks/preview-flow` 返回 `PreviewFlowResponse`；前端 `FlowMermaidPreviewModal.vue`
- Consumes: Mermaid.js, 前端 Payload 管道

- [ ] **Step 1: 编写前端 payload 序列化测试与 API 结构化响应测试**

```typescript
// frontend/src/test/flow-payload.spec.ts
import { describe, it, expect } from 'vitest'
import { buildTaskFormPayload } from '@/lib/task-form-payload'

describe('flow payload serializer', () => {
  it('handles advanced flowMode and links execution_engine to v4', () => {
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
    expect(payload.chats[0].actions).toBeUndefined()
    expect(payload.execution_engine).toBe('v4')
  })
})
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pnpm test frontend/src/test/flow-payload.spec.ts`
Expected: FAIL

- [ ] **Step 3: 完善 API 结构化响应与前端表单组件**

1. 在 `sign_tasks_v2.py` 中定义 `FlowValidationIssue` 与 `PreviewFlowResponse`，合法时返回 200，图校验失败时返回 422 伴随结构化 issue 列表；
2. 更新 `frontend/src/lib/types.ts` 与 `task-form-payload.ts`；
3. 创建 `frontend/src/components/tasks/FlowMermaidPreviewModal.vue`，展示节点数、警告信息并渲染 Mermaid 图形。

- [ ] **Step 4: 运行前端测试验证通过**

Run: `pnpm test frontend/src/test/flow-payload.spec.ts`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add backend/api/routes/sign_tasks_v2.py frontend/src/lib/types.ts frontend/src/lib/task-form-payload.ts frontend/src/components/tasks/FlowMermaidPreviewModal.vue frontend/src/test/flow-payload.spec.ts
git commit -m "feat(ui): add structured preview-flow API response and flow modal preview component"
```

---

### Task 8: 全链路端到端集成测试、真实执行器接线与回归演练

**Files:**
- Create: `tests/test_flow_full_lifecycle.py`

**Interfaces:**
- Consumes: 全流程链路 (`SignChatV3` -> `GraphNormalizer` -> `PulseFlowEngine` -> `TelegramNodeExecutor`)
- Produces: 验证真实任务配置下 7 种节点通过真实 NodeExecutor 调度的端到端一致性，以及旧任务零回归验证

- [ ] **Step 1: 编写真实 Executor 调度与全节点端到端测试**

```python
# tests/test_flow_full_lifecycle.py
import pytest
from tg_signer.config import FlowNodeType, FlowStepConfig, SignChatV3
from tg_signer.core.flow_adapter import TelegramNodeExecutor
from tg_signer.core.flow_engine import PulseFlowEngine
from tg_signer.core.flow_normalizer import GraphNormalizer
from tg_signer.core.flow_context import ScopedFlowContext


@pytest.mark.asyncio
async def test_full_lifecycle_with_real_telegram_node_executor(monkeypatch):
    chat = SignChatV3(
        chat_id=888,
        steps=[
            FlowStepConfig(
                step_id="step_action",
                node_type=FlowNodeType.ACTION,
                action_type="SEND_TEXT",
                params={"text": "/checkin"},
                next_step_id="step_delay",
            ),
            FlowStepConfig(
                step_id="step_delay",
                node_type=FlowNodeType.DELAY,
                delay_seconds=0.1,
                next_step_id="COMPLETE",
            ),
        ],
    )

    graph = GraphNormalizer.from_chat(chat)
    engine = PulseFlowEngine()
    ctx = ScopedFlowContext()

    # 模拟真实 runner
    class MockRunner:
        def __init__(self):
            self.context = type("Ctx", (), {"last_output": ""})()
        async def send_text(self, *args, **kwargs):
            return "签到成功"

    executor = TelegramNodeExecutor(MockRunner(), chat, graph)
    res = await engine.run(graph, ctx, executor)
    assert res["status"] == "success"
    assert res["steps"] == 2
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
git commit -m "test(flow): verify full lifecycle execution with real TelegramNodeExecutor and zero-regression baseline"
```

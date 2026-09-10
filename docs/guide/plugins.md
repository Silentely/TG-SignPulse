# 自定义 Action 插件扩展机制

TG-SignPulse 提供了轻量、低侵入、零破坏兼容的自定义 Action 插件扩展机制（对应动作 ID `99`：`CUSTOM_PLUGIN`）。

## 背景与设计理念

在自动化签到与消息编排场景中，除官方内置的 1～9 号通用动作外，常会遇到特定且确定性的验证场景：
- **纯文本算式秒答**：某些签到 Bot 会发送如“`请在 30 秒内输入 2*31 的答案`”的纯文本数学算式。此类问题通过本地简单正则与分支运算即可在几毫秒内精确解答，**无需调用大语言模型（LLM），从而避免不必要的 AI 成本、Token 消耗以及网络延迟**。
- **特定协议或签名验证**：某些私有 Bot 需要特定 Hash 响应或动态 Token 计算。
- **外部系统联动**：触发签到时调用自建 Webhook 或读取外部本地缓存。

通过自定义 Action 插件机制，你可以编写纯 Python 函数扩展动作行为，既可在宿主机直接热挂载，也可在 Docker 容器环境下免重新构建镜像运行。

---

## 核心设计与保障

1. **动作编号规范**：自定义插件固定分配动作 ID `99`（`SupportAction.CUSTOM_PLUGIN`），预留 `10～98` 给未来官方内置通用动作。
2. **向后 100% 兼容**：现有 1～9 号动作逻辑、历史配置文件格式完全不受影响。
3. **主服务防雪崩与进程树隔离**：每个插件独立捕获加载异常，单个插件发生语法错误或缺少三方包不会导致主服务或定时调度器崩溃。同步插件默认调度至独立 Worker 进程树执行，与主服务完全物理隔离。
4. **防死锁与进程组 SIGKILL 硬终止熔断**：插件执行具备默认与显式配置的超时熔断（`timeout`）。当插件执行超时（如进入同步死循环），宿主会立即向子进程所在进程组广播 `SIGKILL` 强杀整棵进程树，彻底回收孤儿进程并避免主事件循环与线程池卡死。
5. **容器热挂载（零构建）**：预设目录扫描映射至 `/data/plugins`，与官方 Docker Compose `./data:/data` 挂载点原生契合。

---

## 进程树级硬终止沙箱与 IPC 代理架构

为了彻底解决自定义插件可能包含同步死循环（例如 `while True: pass`、C 扩展锁死）、恶意阻塞或资源泄露而导致宿主服务卡死的问题，TG-SignPulse 采用了**基于独立子进程 Worker + 双向 JSON-RPC 管道代理 + 跨平台进程树硬终止（Process Group SIGKILL）**的沙箱架构。

```text
┌─────────────────────────────────────────────────────────────┐
│                      宿主进程 (Host Process)                 │
│  - Pyrogram Telegram Client / 会话网络连接                  │
│  - 定时调度器 (Signer Loop) / Web API 服务                  │
│                                                             │
│         │  stdin (JSON-RPC)          ▲ stdout (JSON-RPC)     │
│         │  (初始化上下文 / RPC 响应)  │ (RPC 调用 / 日志回传) │
│         ▼                            │                      │
│  ┌───────────────────────────────────────────────────────┐  │
│  │     子进程组 (New Session / PGID / Process Group)     │  │
│  │                                                       │  │
│  │   Worker 子进程 (python -m tg_signer.core.plugin_worker) │
│  │   - 独立 Python 运行时环境与沙箱上下文                 │  │
│  │   - 动态加载并执行插件代码 (ctx.reply / click / log)   │  │
│  │   - 派生的孙子进程 (如有)                             │  │
│  └───────────────────────────────────────────────────────┘  │
│         │                                                   │
│         └────── [超时触发] ───► os.killpg(SIGKILL) ─────────┘
│                                 (毫秒级彻底销毁整个进程树)
└─────────────────────────────────────────────────────────────┘
```

### 1. 架构工作机制

1. **子进程组隔离创建**：
   - 宿主进程通过 `asyncio.create_subprocess_exec` 启动轻量级 Worker 进程（`python -m tg_signer.core.plugin_worker`）；
   - 在类 Unix（Linux / macOS）系统下，使用 `start_new_session=True` 为 Worker 创建全新的独立会话与独立进程组（Process Group ID）；在 Windows 环境下同样记录 PID 并由进程树杀手进行递归管理。
2. **轻量双向 JSON-RPC 管道通信**：
   - **上下文初始化**：宿主将插件名称、源码路径、当前 Telegram 消息摘要（`message`）、会话 ID（`chat_id`）及自定义参数（`params`）通过子进程 `stdin` 发送；
   - **双向透明代理**：
     - **日志实时透传 (`type: "log"`)**：Worker 内通过 `ctx.log()` 输出的各级别日志实时回传至宿主，并无缝归档到账号运行日志与前端 SSE 流；子进程内代码的普通 `print` 输出会被捕获为调试日志，不会破坏 IPC 管道数据；
     - **RPC 逆向调用 (`type: "call"`)**：当插件调用 `await ctx.reply()`、`await ctx.send_message()` 或 `await ctx.click()` 时，Worker 发送 RPC 请求至宿主，宿主在真实的 Pyrogram 客户端会话上下文中执行真正的 Telegram 网络请求，并将消息模型序列化后响应给 Worker；
     - **执行结果交付 (`type: "return"`)**：插件函数执行完成并返回布尔值结果，宿主接收后完成本次动作调度。
3. **超时硬终止（Hard Kill）与彻底回收**：
   - 传统方案痛点：在单一进程线程池模型下，`asyncio.wait_for` 超时只能放弃等待协程，底层运行在线程中的同步死循环（如 `while True: pass`）依然占用 CPU 与 Python GIL，无法强制中断，最终拖垮整个主服务。
   - 硬终止保障：当 Worker 执行超过任务设置的超时时间（任务配置的 `timeout` 或测试接口默认 `5.0s`）时，宿主端 `PluginProcessHost` 会立即向 Worker 所在进程组发送 `SIGKILL` 信号（类 Unix 环境通过 `os.killpg(pgid, signal.SIGKILL)`，Windows 环境通过 `taskkill /F /T` 强杀整棵进程树）。无论插件内部是否包含死循环或派生了子进程，操作系统内核都会在毫秒级强制释放所有内存、文件句柄和进程资源，彻底杜绝孤儿进程与主进程阻塞。

### 2. 隔离引擎配置 (`PLUGIN_ISOLATION_ENGINE`)

系统支持通过环境变量 `PLUGIN_ISOLATION_ENGINE` 动态调整插件执行策略，满足不同性能与安全诉求：

| 取值 | 模式名称 | 执行逻辑 | 适用场景 |
| :--- | :--- | :--- | :--- |
| **`auto`**<br>*(默认值)* | **智能混合模式** | - **异步插件 (`async def`)**：直接在宿主事件循环中调度执行，零进程开销，性能极高。<br>- **同步插件 (`def`)**：自动调度到独立子进程 Worker 沙箱中执行，享受进程组超时 `SIGKILL` 强杀保护。 | **生产推荐**。兼顾极高执行效率与防死循环安全。 |
| **`process`** | **全原子进程隔离** | 无论插件定义为同步（`def`）还是异步（`async def`），一律在独立子进程 Worker 中执行。主进程与插件完全隔离。 | 对插件脚本可信度要求极高，或多租户/需要绝对安全屏障的环境。 |
| **`in_process`** | **宿主内嵌执行** | 所有插件均在宿主进程内执行。同步插件通过 `asyncio.to_thread` 在宿主线程池中运行。 | 内存资源极其受限的微型设备；或所有插件已严格通过人工静态审计，确认不存在死循环风险。 |

#### 调试演练场超时配置 (`PLUGIN_TEST_TIMEOUT`)

在 Web 管理面板的「系统设置」->「插件演练场 (Playground)」中进行在线单次测试时：
- 默认沙箱测试超时时间为 **`5.0`** 秒；
- 可通过设置环境变量 `PLUGIN_TEST_TIMEOUT`（如 `PLUGIN_TEST_TIMEOUT=10.0`）自定义演练场超时阈值；
- 若测试超时，演练场将安全触发硬终止，并在测试结果弹窗中展示 `killed: true` 标识与 `[error] 插件执行超时（沙箱限制 X 秒）` 警告，同时标识当前使用的隔离引擎类型（`subprocess` 或 `in_process`）。

---

## 插件加载与目录规范

系统启动时会扫描并加载以下目录下的插件（按优先级生效）：

1. **环境变量指定目录**：`PLUGINS_DIR` 或 `TG_SIGNER_PLUGINS_DIR`
2. **数据持久化目录**：`APP_DATA_DIR/plugins`（Docker 容器内默认为 `/data/plugins`，对应宿主机 `./data/plugins`）
3. **本地工作目录**：`./plugins`

### 目录结构

系统同时支持**单文件插件**与**多文件目录型插件**：

```text
plugins/
├── math_solver/              # 目录型插件（推荐）
│   ├── main.py               # 插件入口文件（或 __init__.py）
│   └── helper.py             # 内部辅助模块（支持相对导入）
└── my_single_plugin.py       # 单文件插件
```

> **Docker 挂载提示**：
> 在 `docker-compose.yml` 默认挂载 `./data:/data` 的情况下，只需在宿主机项目根目录创建 `./data/plugins/你的插件/main.py`，重启容器即可自动识别，**无需构建任何新镜像**！

---

## 插件开发指南

### 1. 注册装饰器与执行模式

使用 `@PluginRegistry.register` 装饰器注册插件处理函数：

```python
from tg_signer.core.plugins import PluginContext, PluginRegistry

@PluginRegistry.register(
    name="my_plugin",         # 插件唯一标识名（与任务配置中的 plugin_name 一致）
    mode="reactive",          # 执行模式："reactive"（监听响应）或 "active"（主动执行）
    description="我的自定义插件说明",
)
async def my_handler(ctx: PluginContext) -> bool:
    # 返回 True 表示处理成功并结束当前动作；返回 False 表示未命中，继续监听后续消息
    ...
```

### 2. 执行模式详解

| 模式 | 适用场景 | 触发时机 | 返回值约定 |
| :--- | :--- | :--- | :--- |
| **`reactive`（监听响应）** | 验证码秒答、Bot 挑战问题应答 | 收到目标会话推送的新消息时触发；若未及时收到，超时前会自动从最近历史消息中回退重试 | 返回 `True` 表示命中并应答完毕，流程推进到下一步；返回 `False` 表示非目标消息，继续等待下条消息 |
| **`active`（主动执行）** | 主动发起请求、调用外部 API、本地预处理 | 任务执行到该动作时立即调用一次 | 返回 `True` / 非 False 表示执行成功；返回 `False` 表示执行失败 |

### 3. `PluginContext` 运行时 API

插件函数的唯一入参为 `ctx: PluginContext`，提供以下能力：

- `ctx.message`：当前收到的 Telegram 消息对象（`pyrogram.types.Message`）。包含 `text`、`photo`、`id` 等。
- `ctx.chat_id`：当前会话 ID（`int`）。
- `ctx.params`：任务配置中透传的自定义参数字典（`dict`）。
- `await ctx.reply(text: str, **kwargs)`：快捷引用当前消息进行回复，自动继承会话重试与 FloodWait 退避。
- `await ctx.send_message(text: str, **kwargs)`：向当前会话发送消息。
- `await ctx.click(text_or_index: str | int, **kwargs)`：点击当前消息上的内联按钮。
- `ctx.log(msg: str, level="INFO")`：记录日志，自动打通至账户运行日志与前端 Web 面板 SSE 实时流。

---

## 官方范例：纯文本算式秒答插件 (`math_solver`)

针对 Issue #10 提到的场景（`请在 30 秒内输入 2*31 的答案`），TG-SignPulse 内置提供了官方标准范例 `plugins/math_solver/main.py`：

```python
"""TG-SignPulse 官方范例插件：纯文本计算题秒答 (math_solver)。"""
import re
from typing import Optional
from tg_signer.core.plugins import PluginContext, PluginRegistry

# 匹配算式，前后通过 (?<![\d\-]) 与 (?![\d\-]) 隔离，避免误匹配 2026-09-08 这类 ISO 日期串
_MATH_PATTERN = re.compile(r"(?<![\d\-])(\d+)\s*([\+\-\*\/\×\÷])\s*(\d+)(?![\d\-])")

def _evaluate_expression(text: str) -> Optional[int]:
    match = _MATH_PATTERN.search(text)
    if not match:
        return None
    left = int(match.group(1))
    op = match.group(2)
    right = int(match.group(3))

    if op == "+":
        return left + right
    elif op == "-":
        return left - right
    elif op in ("*", "×"):
        return left * right
    elif op in ("/", "÷"):
        return left // right if right != 0 else None
    return None

@PluginRegistry.register(
    name="math_solver",
    mode="reactive",
    description="纯文本计算题秒答插件（免 AI 本地秒答）",
)
async def solve_math_challenge(ctx: PluginContext) -> bool:
    """监听新到达的消息，提取算式并自动回复答案。"""
    msg = ctx.message
    if not msg or not getattr(msg, "text", None):
        return False

    ans = _evaluate_expression(msg.text)
    if ans is None:
        return False

    ctx.log(f"[math_solver] 成功匹配计算题：{msg.text!r}，计算答案：{ans}")
    await ctx.reply(str(ans))
    return True
```

### 官方预置实用插件

TG-SignPulse 官方开箱预置了 4 个经过严格单测的生产级标准插件（位于 `plugins/` 目录）：

1. **`math_solver`**（纯文本计算题秒答插件）：
   - **运行模式**：`reactive`
   - **适用场景**：识别消息中的四则运算算式（加减乘除，如 `2*31`、`15+27` 等），自动计算并回复答案。
   - **参数配置**：支持 `reply_prefix`（自定义回复前缀）。

2. **`regex_reply`**（通用正则匹配提取与回复插件）：
   - **运行模式**：`reactive`
   - **适用场景**：从 Bot 消息中提取纯文本验证码、动态 Token、口令等内容并自动回复。
   - **参数配置**：
     - `pattern`：正则表达式（如 `验证码[：:\s]+([a-zA-Z0-9]+)` 或 `\b\d{4,6}\b`）；
     - `template`：回复模板（默认为 `{1}` 对应第 1 捕获组，无捕获组时为全文）；
     - `reply_to`：是否引用原消息回复（布尔值，默认 `true`）。

3. **`keyword_reactor`**（关键词表情表态与快捷回复插件）：
   - **运行模式**：`reactive`
   - **适用场景**：监听新接收到的消息，满足关键词匹配时自动为消息添加表情表态（Reaction 如 👍/🎉）并可同时发送附加回复。
   - **参数配置**：
     - `keyword`：匹配关键词或正则；
     - `emoji`：表情符号（默认 `👍`）；
     - `match_mode`：匹配模式（`contains` / `exact` / `regex`）；
     - `reply_text`：可选附加回复文本。

4. **`daily_checkin_helper`**（日常签到辅助与打卡统计插件）：
   - **运行模式**：`reactive`
   - **适用场景**：配合前置发送签到指令的动作，匹配签到回复中的内联签到/领取按钮，并通过持久化存储累计签到次数。
   - **参数配置**：
     - `command`：签到指令（默认 `/checkin`）；
     - `button_keywords`：内联按钮模糊匹配词（逗号分隔）；
     - `track_stats`：是否记录签到统计（默认 `true`）。
---

### 在 Web 任务编排与系统设置中配置使用

1. **动态候选与可视化参数配置**：
   - 打开 Web 管理面板，进入 **任务管理** -> **编辑任务** 或 **新建任务**；
   - 在动作下拉菜单中选择 **自定义插件 (99)**；
   - 在右侧插件标识输入框中，系统会自动联想下拉候选（列出已加载的插件名及其运行模式）；
   - **Schema 动态表单**：选中支持参数配置的插件后，系统会自动展开对应的参数输入项（如正则 pattern、前缀 prefix、开关等），直接在界面上调整即可随任务一并安全持久化！

2. **系统设置中的插件概览、重新加载与调试演练场 (Playground)**：
   - 进入 **系统设置** 页面，在左侧找到 **扩展插件** 卡片；
   - 卡片中列出当前所有已挂载插件的名称、运行模式、描述及插件相对路径；
   - **调试演练场 (Playground)**：点击插件右侧的 **「演练」** 按钮，可弹出测试窗口。直接输入一段模拟的 Bot 消息文本（如 `请在 30 秒内输入 2*31 的答案` 或 `验证码为：9527`），点击 **「执行测试」** 即可实时看到插件的匹配结果、提取回复内容、详细日志流与执行耗时（毫秒级），无需等待实际打卡或触发账号签到。演练场执行与正式任务一致受隔离引擎调度保护；在 `auto` 或 `process` 模式下遇到同步死循环超时会自动触发子进程树 `SIGKILL` 强杀回收，前端界面会高亮提示硬终止状态；
   - **重新加载**：放入新的插件文件或修改现有代码后，可点击右上角 **「重新加载」** 按钮重新扫描配置目录。已运行的任务可能仍持有旧处理函数，依赖模块的缓存也可能需要重启服务才能完全刷新。

### 插件管理 API

| 接口 | 方法 | 说明 |
| :--- | :--- | :--- |
| `/api/plugins` | `GET` | 获取当前所有已加载插件的元数据列表（名称、模式、描述、源码路径、参数 Schema）。 |
| `/api/plugins/reload` | `POST` | 清空当前加载缓存并重新全量扫描加载所有配置目录下的插件，返回最新状态。 |
| `/api/plugins/{name}/test` | `POST` | Web 调试接口：模拟传入消息文本和参数，在沙箱隔离环境中执行测试，返回匹配结果、回复内容、日志、耗时以及子进程硬终止状态（killed）。 |

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
6. **元数据管理与智能回退**：原生支持插件版本（`version`）、更新日期（`updated_at`）与作者（`author`）信息展示，未显式声明时版本默认 `1.0.0`，更新日期自动回退为文件的最后物理修改时间（`mtime`）。

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

#### 调试台超时配置 (`PLUGIN_TEST_TIMEOUT`)

在 Web 管理面板侧边栏「扩展插件」菜单中进行在线单次「调试」时：
- 默认沙箱测试超时时间为 **`5.0`** 秒；
- 可通过设置环境变量 `PLUGIN_TEST_TIMEOUT`（如 `PLUGIN_TEST_TIMEOUT=10.0`）自定义测试超时阈值；
- 也可在调试台单次请求中通过 `timeout` 参数指定超时（契约范围 `(0, 300]` 秒，超出将被拒绝）；
- 若测试超时，系统将安全触发硬终止，并在测试结果弹窗中展示 `killed: true` 标识与 `[error] 插件执行超时（沙箱限制 X 秒）` 警告，同时标识当前使用的隔离引擎类型（`subprocess` 或 `in_process`）。

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
> 在 `docker-compose.yml` 默认挂载 `./data:/data` 的情况下，只需在宿主机项目根目录创建 `./data/plugins/你的插件/main.py`，重启容器即可自动识别，**无需构建任何新镜像**！也可在 Web 界面直接点击「新建插件」自动生成模板代码。

---

## 插件开发指南

### 1. 注册装饰器与元数据声明

使用 `@PluginRegistry.register` 装饰器注册插件处理函数：

```python
from tg_signer.core.plugins import PluginContext, PluginRegistry

VERSION = "1.0.0"
UPDATED_AT = "2026-09-11"
AUTHOR = "Developer"

@PluginRegistry.register(
    name="my_plugin",         # 插件唯一标识名（与任务配置中的 plugin_name 一致）
    mode="reactive",          # 执行模式："reactive"（监听响应）或 "active"（主动执行）
    description="我的自定义插件说明",
    version=VERSION,          # 版本号（默认 1.0.0）
    updated_at=UPDATED_AT,    # 更新日期（未填自动读取文件修改日期 mtime）
    author=AUTHOR,            # 开发者署名
    params_schema=[...],      # 可选：前端动态参数表单 Schema
)
async def my_handler(ctx: PluginContext) -> bool:
    # reactive 模式返回 True 表示处理成功并结束当前动作；返回 False 表示未命中，继续监听
    ...
```

### 2. 执行模式详解

| 模式 | 适用场景 | 触发时机 | 返回值约定 |
| :--- | :--- | :--- | :--- |
| **`reactive`（监听响应）** | 验证码秒答、Bot 挑战问题应答、表情表态 | 收到目标会话推送的新消息时触发；若未及时收到，超时前会自动从最近历史消息中回退重试 | 返回 `True` 表示命中并应答完毕，流程推进到下一步；返回 `False` 表示非目标消息，继续等待下条消息 |
| **`active`（主动执行）** | 主动发起请求、调用外部 API / Webhook、本地状态统计 | 任务流水线调度到该动作时立即调用一次 | 返回 `True` / 非 False 表示执行成功；返回 `False` 表示执行失败 |

### 3. `PluginContext` 运行时 API

插件函数的唯一入参为 `ctx: PluginContext`，提供以下完整上下文能力：

| 属性 / 方法 | 说明 |
| :--- | :--- |
| `ctx.message` | 当前收到的 Telegram 消息对象（`pyrogram.types.Message`）。包含 `text`、`photo`、`id` 等。 |
| `ctx.chat_id` | 当前会话 ID（`int`）。 |
| `ctx.params` | 任务配置中透传的自定义参数字典（`dict`）。 |
| `await ctx.reply(text: str, **kwargs)` | 快捷引用当前消息进行回复，自动继承会话重试与 FloodWait 退避。 |
| `await ctx.send_message(text: str, **kwargs)` | 向当前会话主动发送新文本消息。 |
| `await ctx.click(text_or_index: str \| int, **kwargs)` | 点击当前消息上的内联按钮。 |
| `await ctx.react(emoji: str)` | 为当前消息打上 Telegram Emoji 表态（如 👍/🎉）。 |
| `ctx.storage` | 针对当前插件隔离的键值存储引擎（`get` / `set` / `increment`）。 |
| `ctx.log(msg: str, level="INFO")` | 记录日志，自动打通至账户运行日志、Web 调试窗口及前端 SSE 实时流。 |

---

## 官方开箱预置插件库

TG-SignPulse 官方预置了 5 个经过严格单测与实战验证的生产级标准插件（位于 `plugins/` 目录）：

1. **`math_solver`**（纯文本计算题秒答插件）：
   - **运行模式**：`reactive`
   - **适用场景**：识别消息中的四则运算算式（加减乘除，如 `2*31`、`15+27` 等），自动计算并回复答案。
   - **参数配置**：`reply_prefix`（可选，回复前缀如“答案是：”）。

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
   - **适用场景**：配合前置发送签到指令的动作，匹配签到回复中的内联签到/领取按钮，成功点击后通过持久化存储累计签到次数与最后签到时间。
   - **参数配置**：
     - `button_keywords`：内联按钮模糊匹配词（逗号分隔）；
     - `track_stats`：是否记录签到统计（默认 `true`，仅在成功点击按钮时累计）。

5. **`webhook_pusher`**（主动型 HTTP Webhook 通知推送插件）：
   - **运行模式**：`active`
   - **适用场景**：任务调度执行时，主动将打卡事件、会话信息与时间戳通过 JSON 格式 POST 到外部 Webhook（支持自建 API、Discord、企业微信、飞书等）。
   - **参数配置**：
     - `webhook_url`：目标 Webhook 地址（必填，HTTP/HTTPS）；
     - `auth_token`：可选，HTTP Bearer 鉴权 Token；
     - `custom_message`：可选，附加自定义推送说明文本。

---

## Web 界面全生命周期管理

进入 Web 管理面板侧边栏 **「扩展插件」**，即可体验完整的插件开发与维护中心：

1. **元数据与状态可视化**：
   - 直观展示每个插件的运行模式（`reactive` / `active`）、版本徽章（`v1.0.0`）、更新日期、开发者署名及启停状态。
2. **在线「新建插件」**：
   - 点击右上角 **「新建插件」**，选择基础模板（响应式监听、主动执行型、状态计数型），一键在 `/data/plugins` 生成插件脚手架代码。
3. **安全「查看源码」**：
   - 点击任意插件卡片上的 **「查看源码」**，即可以高亮只读模式查看当前代码，并支持一键复制到剪贴板。
4. **安全「删除」**：
   - 自定义插件卡片提供 **「删除」** 按钮，二次确认后安全物理删除对应目录或文件；官方内置插件受内核保护，禁止删除。
5. **免打卡「调试」**：
   - 点击插件右侧的 **「调试」** 按钮，免打卡即时输入模拟文本，观察匹配结果、回复内容、Reaction 表态以及运行日志，秒级验证业务逻辑。
   - 调试执行的持久化存储与重置均作用于独立的测试命名空间（`__test__:{chat_id}:{插件名}`），与生产持久化数据（`{chat_id}:{插件名}`）完全隔离，调试不会污染线上状态。
   - 单次调试超时可通过 `timeout` 参数自定义，契约上限为 300 秒。
6. **开发者指南**：
   - 点击右上角 **「开发参考」**，随时调阅 `PluginContext` API 与核心规范。
7. **运行指标与执行历史**：
   - 面板展示每个插件的调用次数、成功率、平均耗时与最近执行结果脉冲；执行历史保留最近 30 条。
   - 指标按触发来源区分：`manual_test`（调试台模拟）、`reactive`（消息监听任务）、`active`（主动定时任务）。
   - 注意：指标与执行历史目前仅存于后端进程内存，进程重启后清零；多进程部署时各进程指标相互独立。

---

## 插件管理 API

| 接口 | 方法 | 说明 |
| :--- | :--- | :--- |
| `/api/plugins` | `GET` | 获取当前所有已加载插件的元数据列表（含名称、模式、描述、版本、更新时间、作者、源码路径、参数 Schema）。 |
| `/api/plugins/reload` | `POST` | 清空当前加载缓存并重新全量扫描加载所有配置目录下的插件，返回最新状态。 |
| `/api/plugins/{name}/source` | `GET` | 安全只读获取指定插件的 Python 源代码（含路径遍历防范与 2MB 限制）。 |
| `/api/plugins/create` | `POST` | 根据选定脚手架模板（reactive / active / storage）在线创建新插件并自动热加载。 |
| `/api/plugins/{name}` | `DELETE` | 安全删除指定自定义插件文件/目录并热重载（官方内置插件禁止删除，返回 403）。 |
| `/api/plugins/{name}/test` | `POST` | Web 调试接口：模拟传入消息文本和参数，在沙箱隔离环境中执行测试，返回匹配结果、回复内容、日志、耗时以及子进程硬终止状态（killed）。 |

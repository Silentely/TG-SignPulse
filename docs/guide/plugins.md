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
3. **主服务防雪崩隔离**：每个插件独立捕获加载异常，单个插件发生语法错误或缺少三方包不会导致主服务或定时调度器崩溃。插件代码仍在宿主进程内执行，请只加载可信插件。
4. **防死锁与超时熔断**：插件执行默认及显式配置超时熔断（`timeout`），超时即结束当前等待并释放异步任务路径；同步插件已转入线程执行，超时后底层线程可能仍需自行结束，请避免在同步插件中长期阻塞。
5. **容器热挂载（零构建）**：预设目录扫描映射至 `/data/plugins`，与官方 Docker Compose `./data:/data` 挂载点原生契合。

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

### 3. `PluginContext` 运行上下文 API

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

### 在 Web 任务编排界面中配置使用

1. 打开 Web 管理面板，进入 **任务管理** -> **编辑任务** 或 **新建任务**。
2. 在目标会话的动作序列中，点击 **添加动作**。
3. 在下拉菜单中选择 **自定义插件 (99)**。
4. 在 **插件名称** 文本框中输入 `math_solver`。
5. 保存任务配置。当签到任务发送 `/checkin` 并收到 Bot 发出的算式验证码时，系统将触发 `math_solver` 本地秒答并自动回复计算结果！

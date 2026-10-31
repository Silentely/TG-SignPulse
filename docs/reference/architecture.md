# 系统架构

## 总览

TG-SignPulse 由四个核心层组成：

1. Vue 3 前端面板
2. FastAPI 后端 API
3. 调度与任务服务
4. `tg_signer` Telegram 执行引擎

## 前端

前端负责：

- 登录与鉴权
- 账号管理
- 任务创建与编辑
- AI 配置
- 全局设置
- 运行日志展示

开发模式默认运行在：

```text
http://localhost:5173
```

## 后端 API

主要路由包括：

- `/api/auth` — 认证与登录
- `/api/user` — 用户管理
- `/api/accounts` — 账号管理
- `/api/sign-tasks` — 签到任务配置（**主路径**，文件存储）
- `/api/batch/sign-tasks` — 签到任务批量操作（enable/disable/delete/run）
- `/api/ops` — 运维：调度预览、备份状态/导出、内存统计
- `/api/logs` — 执行日志
- `/api/config` — 系统配置
- `/api/events` — 签到历史 SSE 事件流与单次票据签发
- `/api/plugins` — 自定义 Action 插件管理、诊断、测试与市场
- `/api/keyword-hits` — 关键词命中记录查询与导出
- `/api/tasks` — **已移除**（请用 `/api/sign-tasks`）
- `/api/batch/tasks` — **已移除**（请用 `/api/batch/sign-tasks`）

后端负责：

- JWT 鉴权
- 数据库存储
- 账号登录流程
- 任务增删改查
- 调度同步
- 关键词监听生命周期管理

## 调度层

调度层基于 APScheduler。

主要职责：

- 读取已启用任务
- 为 `fixed` 与 `range` 任务生成调度
- 在任务变更后同步调度项
- `listen` 模式则交给关键词监听服务，而不是普通 Cron

## 任务服务

`SignTaskService` 负责：

- 任务创建、更新、删除
- 共享任务的账号聚合
- 手动执行任务
- 历史记录和流程日志
- 失败通知

执行细节由 `sign_task_runner.execute_sign_task` 分阶段完成（账号锁、冷却、重试、超时、落历史）；取消（`CancelledError`）不写失败历史、不发失败通知。开发者地图见仓库 [`backend/CLAUDE.md`](../../backend/CLAUDE.md)。

历史列表依赖 `history/_recent_index.jsonl` 轻量索引（供 SSE / 最近日志），详情仍读各任务 history JSON。

## 关键词监听服务

`KeywordMonitorService` 负责：

- 从任务配置中提取监听规则
- 挂载 Telegram message handler
- 匹配关键词、正则和话题
- 触发通知、转发或继续动作
- 在任务变化后重建监听器
- 按 (账号, 会话) 持久化已处理消息水位（`seen.json`），避免重连补投重复命中
- 命中后的 continue 动作（发文本/骰子/点键盘/AI/Bot 命令等）在 `continue_actions` 模块执行

分片与 allowlist 见环境变量 `APP_MONITOR_SHARD`、`APP_MONITOR_ACCOUNT_ALLOWLIST`。

## 执行引擎

`tg_signer` 负责真正和 Telegram 交互：

- 发送文本
- 发送骰子
- 点击按钮
- 等待消息变化
- 调用 AI 识图 / OCR / 计算
- 自定义 Action 插件执行（动作类型 `99`）：独立 Worker 子进程沙箱与双向 JSON-RPC IPC 通信
- 处理 FloodWait、重试和部分异常恢复

### AI 调用与故障转移

AI 请求汇聚在 `tg_signer/ai_tools.py` 的 `_create_visual_completion`：

- 主节点使用 `AsyncOpenAI`，走完整的参数兼容降级阶梯（`reasoning_effort` / `response_format` /
  `temperature` 等逐步裁剪），并带视觉重试。
- 主节点彻底失败后转「备用节点」，复用核心包 `tg_signer/core/ai_failover.py` 的
  `AIProviderManager`：以 OpenAI 兼容 HTTP 直连，携带全局预算与单节点隔离
  （`abort_on_config_error=False`，单个节点配置错误不中断其余节点）。
- 备用节点来源：`.openai_config.json` 的 `fallback_providers` 字段，或环境变量
  `OPENAI_FALLBACK_PROVIDERS`（JSON 数组）。备用节点密钥以 Fernet 密文落盘，
  读取时逐个解密；前端「留空」表示沿用已保存密钥。
- `AIProviderManager` 同时被后端复用（经 `backend/services/ai_provider_manager.py`
  兼容再导出），保证 CLI 与后端共用同一套故障转移逻辑。

### PulseFlow (v4) 与核心可靠性架构

执行体系已全面切流至 **PulseFlow (v4)** 引擎单轨运行，具备以下核心架构契约：

- **单轨执行与拓扑编译**：签到任务与工作流统一通过 `ExecutionGraph.compile()` 编译为确定性 DAG 拓扑并由 `PulseFlowEngine` 执行。配置支持保留紧急回滚闸门 `PULSEFLOW_ENGINE_OVERRIDE=classic`，可在特殊运维场景下一键回滚经典分支并记录 Critical 级别告警（注：若任务配置为 `flow_graph` 图结构，经典引擎因不支持图结构将显式抛出异常拒绝，指引移除回滚开关以恢复 PulseFlow 执行）。
- **FlowResult 唯一契约与结构化捕获**：`PulseFlowEngine.run()` 返回统一的 `FlowResult`（继承自 `MutableMapping`，100% 字典兼容器），严格承载执行轨迹与四字段提取结果。Telegram 进站事件统一采集为 `TargetMessage` 结构化对象（支持多目标、频道话题 thread_id、媒体类型及采集来源），彻底解耦自由格式字典。
- **日志多任务隔离与无归属拦截**：内部日志流基于 `(account, task, run_id)` 三元组结合 `ContextVar` 实现多线程与异步任务间严格隔离；对外 REST 与 WebSocket 接口维持 `(account, task)` 二元组平滑向下兼容。未关联特定执行上下文的底层系统日志（无归属日志）被确定性拦截丢弃，杜绝跨任务串台污染。
- **插件全领域解耦**：`backend/api/routes/plugins.py` 完成全面轻量化，所有 37 个 API 领域操作下沉至 `backend/services/plugins.py` 中的 `PluginService`，实现进程生命周期、热重载原子文件锁、市场下载与动态沙箱调用的领域驱动设计。

## 数据流

### 定时任务

```text
Scheduler
  -> SignTaskService
  -> tg_signer core
  -> Telegram
  -> Log / History / Notification
```

### 监听任务

```text
Telegram Update
  -> KeywordMonitorService
  -> Keyword Match
  -> Push / Forward / Continue Actions
  -> Log / History
```

## 存储层

主要存储分为四部分：

- `db.sqlite`：面板数据库
- `sessions/`：Telegram 会话
- `plugins/`：自定义 Action 插件源码与配置
- `.signer/`：任务配置与运行相关数据

AI、全局设置和 Telegram API 配置则单独保存在数据目录根部的 JSON 文件中。

## 设计特点

- 前后端可一体容器化部署
- 任务与账号关系支持从单账号扩展到多账号共享
- 监听任务与定时任务共用动作模型
- AI 提示词支持逐动作覆盖
- 数据目录与运行目录分离，便于迁移与备份

## 扩展约束

当前部署模型以**单写主实例**为主：APScheduler、Telegram 客户端会话和关键词监听器默认在持有调度锁的进程内协调。

- **数据库**：**默认仍是 SQLite（WAL）**，并未取消或强制迁走。可通过 `APP_DATABASE_URL` / `DATABASE_URL` **可选**切换到 PostgreSQL 等（SQLAlchemy URL，需对应驱动）。面板元数据可外置，但 **Telegram session 仍不宜多进程共享同一账号文件**。
- **调度锁**：启动时尝试获取 `data/.scheduler.lock`（`APP_SCHEDULER_LOCK=0` 可关闭）。仅锁持有者注册 `sign-` 业务 job（旧 ORM `db-` job 已随旧任务体系移除），降低多副本重复签到风险。
- **文件配置并发（进程内锁限制）**：任务配置与状态回写（`config.json` 等）依赖 `path_write_lock` 进行“读-改-写”互斥。该锁为**进程内锁（threading.RLock）**，仅保证单 Python 进程内各线程与协程的读写串行化，**不支持多个 API 副本同时挂载共享文件目录进行跨进程并发写入**。若有多副本诉求，需保持单主写入或待后续架构演进（迁移至数据库事务或跨进程分布式锁）。
- **监听分片**：`APP_MONITOR_SHARD=i/n` + 可选 `APP_MONITOR_ACCOUNT_ALLOWLIST`，按账号拆分关键词监听；**同一账号的 session 仍只能由一个进程持有**。
- **旧任务 API**：`/api/tasks` 已移除，统一 `/api/sign-tasks`。
- **任务队列**：完整队列化（Celery/RQ 等）尚未内置；当前以进程内 APScheduler + 文件锁 + 监听分片为过渡方案。
- 数据库锁定的排查步骤见 [运维手册 - 场景 2：数据库锁定](ops.md#场景-2数据库锁定)。
- 反向代理可以扩展入口流量，但不等同于后端多副本扩展。
# Reliability contracts

Task runs expose execution status separately from business status. A Telegram
message event includes chat/topic scope and a revision; an event delivery gap
must be reported as `unknown`. Plugin v2 identity and grants constrain host RPC
operations, while trusted v1 workers remain process-isolated rather than fully
sandboxed. Run artifacts and replay fixtures are redacted and never contact
Telegram or external providers.

[根目录](../CLAUDE.md) > **backend**

# Backend 模块

> FastAPI + SQLAlchemy + APScheduler 构建的 TG-SignPulse 后端服务。

## 变更记录 (Changelog)

> 完整变更记录已拆分至 [`CHANGELOG.md`](./CHANGELOG.md)，避免 CLAUDE.md 过长影响上下文。

## 模块职责

提供 TG-SignPulse 的全部后端能力：

- REST API（认证、账号、签到任务、日志、配置、运维、关键词命中）
- JWT 认证与 TOTP 二步验证
- APScheduler 定时任务调度（含多副本实例锁）
- Telegram 账号管理与 session 维护
- 签到任务执行、历史与日志收集
- 关键词监控服务（分片 / 重启去重 / continue 动作）
- 推送通知（Telegram Bot / Bark / Server酱 / 自定义 URL / 转发）
- 静态前端托管（SPA fallback）+ 健康/就绪探针

## 入口与启动

| 文件 | 职责 |
|------|------|
| `main.py` | FastAPI 应用入口，`lifespan` 管理启动/关闭（约 488 行） |
| `core/config.py` | Settings 配置模型，环境变量读取 |
| `core/database.py` | SQLAlchemy 引擎初始化，Session 管理 |
| `core/auth.py` | JWT 创建/验证，用户认证依赖 |
| `core/security.py` | bcrypt 密码哈希 |
| `core/rate_limit.py` | 内存速率限制器（含过期桶清扫） |
| `core/pydantic_compat.py` | Pydantic v1/v2 兼容薄封装 |

### 启动命令

```bash
# 开发模式（常用 8080，与前端 Vite 代理一致）
uvicorn backend.main:app --host 127.0.0.1 --port 8080

# Docker：entrypoint.sh 适配权限后启动 uvicorn
```

### 启动流程（`main.py` → `on_startup`）

1. 配置后端日志等级
2. 确保数据目录存在
3. 面板全局设置回灌环境变量（`apply_global_settings_to_env`，如 `AI_VISION_TIMEOUT`）
4. 初始化 SQLAlchemy 引擎 + 建表
5. 创建默认管理员（仅首次）
6. 启动 APScheduler（`sync_on_startup=False`）
7. 预导出 session string（避免任务期 SQLite 锁）
8. 延迟任务：`sync_jobs` + 重启关键词监控 → 标记 `app.state.ready`
9. 后台内存监控循环

关闭时：停调度器、释放 scheduler 实例锁、清理监控等。

### 探针

- `GET /health`、`GET /healthz` — 存活
- `GET /ready` — 就绪（含 `scheduler_lock_held` / `scheduler_role`）

## 对外接口

### API 路由（`backend/api/routes/__init__.py`，挂载前缀 `/api`）

| 前缀 | 模块 | 端点数（约） | 职责 |
|------|------|-------------|------|
| `/api/auth` | `auth.py` | 3 | 登录、当前用户、重置 TOTP |
| `/api/user` | `user.py` | 9 | 密码/用户名/TOTP 等用户设置 |
| `/api/accounts` | `accounts.py` | 24 | 账号 CRUD、登录、状态 Job、设备、官方消息、头像、日志 |
| `/api/sign-tasks` | `sign_tasks_v2.py` | 16 + 1 WS | 签到任务主路径（CRUD/执行/日志/对话） |
| `/api/ops` | `ops.py` | 10 | 调度预览、备份/WebDAV、内存、运行时、版本 |
| `/api/logs` | `logs.py` | 7 | 登录审计、任务历史日志 |
| `/api/config` | `config.py` | 17 | 全局设置、AI、Telegram API、导入导出 |
| `/api/events` | `events.py` | 1 | SSE 签到历史事件流 |
| `/api/batch` | `batch.py` | 1 | `POST /sign-tasks` 批量 enable/disable/delete/run |
| `/api/keyword-hits` | `keyword_hits.py` | 4 | 关键词命中记录查询 |

> 旧版 ORM 任务体系（`tasks.py` / `/api/tasks` / `POST /batch/tasks`）已**完全移除**，
> 统一走 `/api/sign-tasks` + `POST /api/batch/sign-tasks`。

### 认证机制

- **JWT (HS256)**：有效期默认 12 小时（`APP_ACCESS_TOKEN_EXPIRE_HOURS`）
- **TOTP**：可选二步验证（`pyotp`）
- **速率限制**：登录等端点限次；超限封锁（实现见 `core/rate_limit.py`）

### 路由详情摘要

#### `accounts.py` — 24 端点（`/api/accounts`）

| 类别 | 说明 |
|------|------|
| 登录 | 手机验证码请求/提交、QR 启动/状态/密码/取消 |
| 账号 | 列表、详情、更新、删除、存在性、设备、官方消息、头像 |
| 状态 | 批量状态检查 + Job 增删查消 |
| 日志 | 最近日志、账号历史、清理、导出 |

#### `sign_tasks_v2.py` — 主路径

| 类别 | 路径要点 |
|------|----------|
| CRUD | `GET/POST ""`、`GET/PUT/DELETE /{task_name}`、`PATCH .../toggle-enabled`、克隆 |
| 执行 | `/run/start`、`/run/status`、`/run/cancel`；`GET /runs/active` |
| 日志 | `/logs`、`/history`；`WS /ws/{task_name}` |
| 对话 | `/chats/{account}`、search、avatar |

支持 `account_names` 与通配符 `*` 聚合模式。

#### `config.py` — 17 端点

全局设置 / 设备保活手动执行 / Bot 测试；Telegram API 读写重置；AI 读写测试删除；单任务与全量导入导出及预览。

#### `ops.py` — 10 端点

`/scheduled-jobs`、`/backup/status|export`、WebDAV test/list/download、`/memory`、`/runtime-status`、`/version`、`/version/check`。

### SSE

- `GET /api/events/sign-history` — 签到历史变更（进程内总线 + 30s 索引兜底），`token` 查询参数鉴权

## 关键依赖与配置

### 核心依赖（见根 `pyproject.toml`）

fastapi、uvicorn、sqlalchemy、apscheduler、pyjwt、bcrypt/passlib、pyotp、httpx、pydantic v1（版本上界 <2）、kurigram、croniter、psutil、filelock、aiofiles 等。

### 配置模型（`core/config.py`）

`Settings.from_environment()` 主要字段：

- `APP_HOST` / `APP_PORT` — 监听
- `APP_DATA_DIR` — 数据根
- `APP_SECRET_KEY` — JWT 密钥（可自动生成持久化）
- `APP_ACCESS_TOKEN_EXPIRE_HOURS`
- `APP_DB_PATH` / `APP_DATABASE_URL` — 库路径或完整 URL
- `APP_SIGNER_WORKDIR` / `APP_SESSION_DIR` / `APP_LOGS_DIR`
- `LOG_LEVEL`、`TZ`/`APP_TIMEZONE`

### 数据库

- 默认 SQLite（WAL，`busy_timeout` 等在 database 层配置）
- 可选非 SQLite URL（`APP_DATABASE_URL`）
- ORM：`declarative_base`；`get_db()` 依赖注入 Session

## 数据模型

### ORM（`backend/models/`）

| 模型 | 表 | 用途 |
|------|-----|------|
| `User` | users | 管理员账号、TOTP |
| `Account` | accounts | 面板侧账号元数据（与 JSON session 存储协同） |
| `LoginLog` | login_logs | 登录审计 |

> 旧 `Task` / `TaskLog` ORM 已移除；签到任务与历史为 JSON 文件。

### Pydantic Schemas（`backend/schemas/`）

- `auth.py` — LoginRequest、TokenResponse、UserOut 等
- `account.py` — AccountCreate/Update/Out
- `sign_batch.py` — 签到任务批量请求/响应

路由内还有大量内联 BaseModel（尤其 `sign_tasks_v2`、`config`、`ops`）。

## 服务层（`backend/services/`）

| 服务 / 包 | 职责 |
|-----------|------|
| `sign_tasks.py` | 签到门面：CRUD、执行编排、活跃日志（组合 Mixin） |
| `sign_task_runner.py` | 单任务流水线（锁/冷却/重试/补抓），约 717 行 |
| `sign_task_history_*.py` | 历史 format/io/index/query/ops |
| `sign_task_crud.py` | `SignTaskCrudMixin`：create/clone/update/rename/delete |
| `sign_task_config_build.py` | 纯函数：config.json 构造、调度计划、改名、写响应 |
| `sign_task_group.py` | 纯函数：多账号聚合、`task_group_id` 键、关联筛选 |
| `sign_task_chats.py` | 对话列表缓存 `chats_cache.json`、搜索、刷新 |
| `sign_task_config_inspect.py` | `task_requires_updates` / `task_has_keyword_monitor` |
| `sign_task_failure.py` / `notify.py` / `run_status.py` | 失败分类、通知、运行状态 |
| `sign_task_backend.py` | `BackendUserSigner` + `TaskLogHandler` |
| `keyword_monitor/` | `runtime` + `rules` + `continue_actions` + `hits` + `sharding` |
| `telegram/` | `accounts` / `login_phone` / `login_qr` / `sessions` / `devices` / `credentials` / `runtime` |
| `push_notifications.py` | 多通道推送 |
| `config.py` + `config_mixins.py` | 配置门面与领域 Mixin |
| `device_keepalive.py` | 会话保活 |
| `runtime_settings.py` | 面板设置优先、环境变量兜底 |
| `sign_history_events.py` | SSE 总线 |
| `backup_archive.py` / `webdav_client.py` | 备份打包与 WebDAV |
| `account_status_jobs.py` / `background_job.py` / `avatar_cache.py` / `users.py` | 状态 Job、通用后台、头像缓存、管理员初始化 |

### 签到执行流水线（`sign_task_runner.py`）

入口：`execute_sign_task(svc, account_name, task_name, run_id?)`。共享 `state` 字典贯穿各 phase helper；`SignTaskService` 只做委托。

| 阶段 | Helper | 要点 |
|------|--------|------|
| 1 | `_runner_load_config` | 读任务配置；`requires_updates` / `has_keyword_monitor` / 通知开关 |
| 2 | `_runner_check_account` | `check_account_before_task` 预检；失效则写日志并跳过执行 |
| 2.5 | `_runner_refresh_keyword_monitor` | 有监听动作时 `restart_from_tasks()`（best-effort） |
| 3 | `_runner_acquire_lock` | 账号锁；冷却 `PHASE_COOLDOWN`；锁内跑 4–8 |
| 4 | `_runner_setup_logging` | `TaskLogHandler` 注入 `tg-signer` → `_active_logs` |
| 5 | `_runner_resolve_credentials` | API 凭据 / session 模式 / 代理；string 模式强制内存 session |
| 6 | `_runner_instantiate_signer` | 构造 `BackendUserSigner` |
| 7 | `_runner_prepare_execution` | 超时 + 有效重试次数；`PHASE_RUNNING` |
| 8 | `_runner_execute_with_retry` | 全局信号量 + `signer.run_once`；DB lock 最多 5 次退避；超时 → `timed_out` |
| 收尾 | `_runner_parse_reply` → `_runner_fetch_target_message` → `_runner_save_run_info` → `_runner_send_notifications` → `_runner_schedule_cleanup` | 解析回复、补抓目标消息、落历史、通知、延迟清 active |
| 错误 | `_runner_handle_error` / `finally _runner_finalize` | 分类失败；**`CancelledError` 不写失败历史、不发失败通知** |

并发边界：账号级 `get_account_lock` + 全局 `get_global_semaphore`；同账号任务串行，跨账号可并行。

### 历史栈（`sign_task_history_*.py`）

| 模块 | 职责 |
|------|------|
| `history_ops.SignTaskHistoryMixin` | 对外：列表/筛选/详情/删除/清理；对内 `_save_run_info` |
| `history_io` | 路径、JSON 读写、过期文件清理、`last_run` 缓存补丁 |
| `history_format` | 条目构造、flow_logs 截断规范化、列表项投影 |
| `history_query` | 格式化收集、按时间倒序、按 `created_at` 定位 |
| `history_index` | `history/_recent_index.jsonl` + 进程内最近 200 条；SSE/最近日志 O(尾读) |

落盘路径（`_save_run_info`）：

1. 规范化 flow_logs → `classify_failure` → `build_history_run_entry`（UTC `utc_now_iso`）
2. 原子写 `run_history_dir` 下按账号/任务分文件的 history JSON（prepend + max_entries）
3. 回写任务 `config.json` 的 `last_run` + 内存 `_tasks_cache`
4. `append_index_entry` → 轻量索引；详情仍读原 history 文件

列表查询：优先 `ensure_index` + `list_recent_from_index`；失败或需完整 flow 时回退扫盘。

### CRUD / 聚合 / 对话缓存

#### `SignTaskCrudMixin`（`sign_task_crud.py`）

| 方法 | 行为要点 |
|------|----------|
| `create_task` | 规范化/展开 `account_names`（含 `*`）；`build_sign_task_config` + `create_task_group_id`；每账号写 `signs_dir/<acc>/<task>/config.json`；fixed/range 注册调度，listen 不调度 |
| `clone_task` | 读源配置 → 新名/新账号集 → 再走创建路径 |
| `update_task` | `resolve_update_field_values` 合并；账号增减用 `removed_accounts_diff` 删目录；刷新调度 |
| `rename_account_references` | 扫任务目录，`apply_account_rename_to_config` 改写引用 |
| `delete_task` | 删任务目录 + 历史；可 `rebuild_index_from_history_files` |

存储约定：`account_names` 可含 `*`（配置层）；实际建目录与调度前 `_expand_account_names` 展开为真实账号。

#### `sign_task_config_build.py`（纯函数）

- `build_sign_task_config`：标准 config 字段（`_version` 默认 4、`execution_mode`、通知、`retry_count` 等）
- `resolve_schedule_plan`：`listen` → 不调度；`range` 用 `range_start`；否则 `sign_at`
- `create_task_group_id` / `next_task_group_id`：多账号 UUID group，单账号空
- `pick_task_write_response`：写后聚合返回前端列表项

#### `sign_task_group.py`（纯函数）

- `task_group_key`：`group:<task_group_id>` 或 `single:<account>:<name>`
- `aggregate_tasks`：合并 `account_names`、取最新 `last_run`、`first_real_account` 跳过 `*`
- `filter_related_task_infos`：同名关联条目（克隆/更新用）

#### `sign_task_chats.py`

| 能力 | 路径 / 行为 |
|------|-------------|
| 缓存文件 | `signs_dir/<account>/chats_cache.json` |
| `get_account_chats_cached` | 命中缓存则返回；`force_refresh` 调 `refresh_fn` |
| `search_account_chats_cached` | **只读缓存**分页搜索，不触发 `get_dialogs` |
| `refresh_account_chats` | 账号锁 + 全局信号量 + `get_client` → 映射对话 → 原子写缓存 |
| `cleanup_invalid_session_and_chat_cache` | 无效 session 时删账号并清缓存 |

### Telegram 登录设计（`services/telegram/`）

1. 手机：`request_code` → `verify_login`（可进 2FA）
2. QR：`start_qr_login` → 状态轮询 → `submit_qr_password`（如需）
3. 并发：账号级锁 + 全局信号量；阶段间 session 字典传 client
4. DC 迁移：检测并有限次重试

## 工具层（`backend/utils/`）

共 13 个业务模块（另 `__init__.py`）：`time`、`time_window`、`atomic_io`、`tg_session`、`task_logs`、`storage`、`cache`、`memory_monitor`、`account_locks`、`names`、`proxy`、`paths`、`version_info`。

## 任务调度（`backend/scheduler/`）

- APScheduler `AsyncIOScheduler`，cron 与 `HH:MM`/`HH:MM:SS` 简写
- 签到模式：`fixed` / `range` / `listen`
- 维护任务（如清理旧日志）
- `instance_lock.py`：仅锁持有者注册业务 job（多副本 primary/replica）

## 关键词监控（`services/keyword_monitor/`）

| 文件 | 职责 |
|------|------|
| `runtime.py` | `KeywordMonitorService`：规则装载、handler 挂载、`_on_message`、`restart_from_tasks`、seen 水位 |
| `rules.py` | `KeywordMonitorRule`、关键词/话题/发送者/时段过滤、模板渲染、`TerminalAIActionError` |
| `continue_actions.py` | 命中后继续动作执行族（约 1234 行） |
| `hits.py` | 命中落盘/列表/分组/CSV 导出 |
| `sharding.py` | `APP_MONITOR_SHARD` / allowlist 账号范围 |

### 消息路径（`_on_message`）

1. 无文本 / 无 chat_id → 丢弃  
2. **seen 水位**（账号+会话+message_id）→ 跳过重连补投旧消息  
3. 同账号同 chat 规则 → 话题 / 发送者 / ignore_self / 活跃时段过滤  
4. `_match_all_keyword_values`（contains / exact / regex；可多捕获）  
5. 命中后：日志 + 推送/转发 + `execute_continue_actions` + `record_keyword_hit`  
6. 更新 seen；`seen.json` 约 30s 节流原子写盘

### 继续动作（`continue_actions`）

- 配置字段：`continue_actions[]`；支持 **action_id ∈ {1,2,3,4,5,6,7,9}**
- 目标：`continue_chat_id` / `continue_message_thread_id`，缺省回落源消息 chat/话题
- **1** 发文本、**2** 发骰子、**3** 按文本点键盘、**4–7** AI 相关（识图/计算/点选项等）、**9** Bot 深链/命令
- 轮询类动作：默认超时 `KEYWORD_MONITOR_CONTINUE_ACTION_TIMEOUT`（默认 25s）、历史窗口 `…_HISTORY_LIMIT`（默认 10）
- Bot 命令：`DEFAULT_BOT_CMD_INTERVAL=2s` 等待而非跳过；`DEFAULT_BOT_CMD_MAX_BATCH=5`（调高有风控风险）
- 任一步失败中止；`TerminalAIActionError` 视为 AI 不可恢复终态

### 生命周期

- `restart_from_tasks`：规则 key 未变且 handler 仍活跃则只补日志；否则 `stop` → 重载规则 → `_load_seen_state` → 按账号建 client 挂 handler
- 分片：`account_in_monitor_scope`；与调度锁配合，同账号 session 仍单进程持有

## 测试与质量

- 根目录 `pytest`；覆盖门槛 40%；近期全量约 60% 行覆盖
- 主要覆盖：routes、sign_task_*、keyword_monitor、telegram/sessions、utils、ops、SSE 等
- 本地验证：改动后跑相关 `tests/test_*.py`，必要时 `pytest --cov`

## 常见问题 (FAQ)

**Q: 后端如何与 tg_signer 交互？**  
A: `BackendUserSigner`（`sign_task_backend.py`）继承 `tg_signer.core.UserSigner`，适配后端目录并禁止交互式输入。

**Q: session 管理？**  
A: file（`.session`）与 string（`.session_string`）双模式；启动预导出 string 减锁冲突。

**Q: 签到任务存在哪？**  
A: `signs_dir/<account>/<task>/config.json`，经 Config/SignTask 服务读写。

**Q: 旧 `/api/tasks`？**  
A: 已移除。残留表用 `tools/check_legacy_tasks.py` 盘点。

## 相关文件清单

- `main.py` — 应用入口
- `core/*` — 配置、库、认证、限流
- `api/routes/*` — 全部 HTTP/WS 路由
- `models/`、`schemas/` — ORM 与共享 schema
- `services/` — 业务（含 `keyword_monitor/`、`telegram/`）
- `scheduler/` — 调度与实例锁
- `utils/` — 横切工具

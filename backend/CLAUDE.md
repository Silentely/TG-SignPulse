[根目录](../../CLAUDE.md) > **backend**

# Backend 模块

> FastAPI + SQLAlchemy + APScheduler 构建的 TG-SignPulse 后端服务。

## 变更记录 (Changelog)

| 日期 | 变更内容 |
|------|----------|
| 2026-08-05 | 文档同步：重写对外接口章节（路由清单、端点计数、批量/SSE 现状）、ORM/服务/工具层清单，删除已移除的旧版 ORM 任务体系描述 |
| 2026-06-30 | 初始化 backend 模块 CLAUDE.md |
| 2026-06-30 | 补扫：TelegramService 登录流程、4 个路由文件端点详情 |

## 模块职责

提供 TG-SignPulse 的全部后端能力：
- REST API（认证、账号、任务、签到、日志、配置）
- JWT 认证与 TOTP 二步验证
- APScheduler 定时任务调度
- Telegram 账号管理与 session 维护
- 签到任务执行与日志收集
- 关键词监控服务
- 推送通知（Telegram Bot / Bark / 自定义 URL）
- 静态前端托管（SPA fallback）

## 入口与启动

| 文件 | 职责 |
|------|------|
| `main.py` | FastAPI 应用入口， lifespan 管理启动/关闭流程 |
| `core/config.py` | Settings 配置模型，环境变量读取 |
| `core/database.py` | SQLAlchemy 引擎初始化，Session 管理 |
| `core/auth.py` | JWT 创建/验证，用户认证依赖 |
| `core/security.py` | bcrypt 密码哈希 |
| `core/rate_limit.py` | 内存速率限制器 |

### 启动命令

```bash
# 开发模式
uvicorn backend.main:app --host 127.0.0.1 --port 8080

# Docker 模式
# entrypoint.sh 自动适配权限后启动 uvicorn
```

### 启动流程 (`main.py` lifespan)

1. 配置日志等级
2. 确保数据目录存在
3. 面板全局设置回灌环境变量（AI_VISION_TIMEOUT 等，重启后不丢失）
4. 初始化 SQLAlchemy 引擎 + 建表
5. 创建默认管理员（仅首次）
6. 启动 APScheduler
7. 预导出 session string（避免 SQLite 锁）
8. 延迟同步任务 + 重启关键词监控

## 对外接口

### API 路由 (`backend/api/routes/__init__.py`)

| 前缀 | 模块 | 职责 |
|------|------|------|
| `/api/auth` | `auth.py` | 登录、获取当前用户、重置 TOTP |
| `/api/user` | `user.py` | 密码修改、用户名修改、TOTP 设置 |
| `/api/accounts` | `accounts.py` | 账号 CRUD、登录流程、状态检查 |
| `/api/sign-tasks` | `sign_tasks_v2.py` | 签到任务管理、执行、历史（主路径） |
| `/api/ops` | `ops.py` | 调度预览、备份导出、内存统计、设备保活 |
| `/api/logs` | `logs.py` | 登录日志、任务历史日志 |
| `/api/config` | `config.py` | 全局设置、AI 配置、Telegram 配置、导入导出 |
| `/api/events` | `events.py` | SSE 签到历史事件流 |
| `/api/batch` | `batch.py` | 签到任务批量操作 |
| `/api/keyword-hits` | `keyword_hits.py` | 关键词命中记录查询 |

> 旧版 ORM 任务体系（`tasks.py` / `/api/tasks` / `POST /batch/tasks`）已**完全移除**，
> 统一走 `/api/sign-tasks` + `POST /batch/sign-tasks`。

### 认证机制

- **JWT (HS256)**: token 有效期 12 小时（可配置）
- **TOTP**: 可选二步验证，基于 `pyotp`
- **速率限制**: 登录 5 次/5 分钟，超限封锁 15 分钟

### 路由详情

#### `accounts.py` — 24 个端点（前缀 `/api/accounts`）

| 类别 | 端点数 | 说明 |
|------|--------|------|
| 登录流程 | 6 | 手机验证码请求/提交、QR 扫码启动/状态/密码/取消 |
| 账号管理 | 8 | 列表、详情、更新（重命名/备注/代理）、删除、存在性、设备管理、官方消息、头像 |
| 状态检查 | 4 | 批量状态检查 + Job 增删查消 |
| 日志 | 5 | 最近日志、账号历史日志、清理（双路径）、导出 |
| 其他 | 1 | 头像背景色 |

- 速率限制：登录端点 5-8 次/10 分钟，超限封锁 15 分钟

#### `sign_tasks_v2.py` — 17 个端点 + 1 WebSocket（前缀 `/api/sign-tasks`）

| 类别 | 端点数 | 说明 |
|------|--------|------|
| 任务 CRUD | 7 | 创建、查询列表/单条、更新、删除、切换启用、克隆 |
| 执行 | 3 | 异步启动、状态轮询、取消（`/run/start` `/run/status` `/run/cancel`） |
| 日志 | 3 | 活跃日志、历史记录、WebSocket 实时推送 |
| 对话 | 3 | 对话列表、搜索、头像 |
| 其他 | 1 + WS | 运行中任务列表 + `/ws/{task_name}` 实时日志流 |

- 支持 `account_names` 列表 + 通配符 `*` 聚合模式

#### `config.py` — 17 个端点（前缀 `/api/config`）

| 类别 | 端点数 | 说明 |
|------|--------|------|
| 全局设置 | 4 | 获取/保存、设备保活手动执行、Bot 通知测试 |
| Telegram API | 3 | 获取/保存/重置自定义 api_id/api_hash |
| AI 配置 | 4 | 获取/保存/脱敏显示/连接测试 |
| 任务导入导出 | 3 | 单任务导出/导入、删除 |
| 全部配置导入导出 | 3 | 全量导出/导入/导入预览 |

#### `batch.py` — 1 个端点（前缀 `/api/batch`）

- `POST /sign-tasks`：文件存储签到任务批量 enable/disable/delete/run（旧版 `POST /tasks` 已移除）

### SSE 事件流

- `GET /api/events/sign-history` — 签到历史变更实时推送（进程内总线 + 30s 索引兜底），
  `token` 查询参数鉴权；旧 `GET /api/events/logs` 已移除

## 关键依赖与配置

### 核心依赖

| 依赖 | 用途 |
|------|------|
| fastapi | Web 框架 |
| sqlalchemy | ORM |
| apscheduler | 定时任务调度 |
| pyjwt | JWT 认证 |
| bcrypt | 密码哈希 |
| pyotp | TOTP 二步验证 |
| httpx | HTTP 客户端（推送通知） |
| pydantic | 数据验证 |

### 配置模型 (`core/config.py`)

`Settings` 类通过环境变量读取配置：
- `APP_HOST`, `APP_PORT` — 监听地址端口
- `APP_DATA_DIR` — 数据目录
- `APP_SECRET_KEY` — JWT 密钥（自动生成持久化）
- `APP_ACCESS_TOKEN_EXPIRE_HOURS` — token 有效期
- `APP_DB_PATH`, `APP_SIGNER_WORKDIR`, `APP_SESSION_DIR`, `APP_LOGS_DIR` — 路径配置

### 数据库

- **引擎**: SQLite (WAL 模式, busy_timeout=30000)
- **ORM**: SQLAlchemy declarative_base
- **Session**: 依赖注入 `get_db()` yield 生成器

## 数据模型

### ORM 模型 (`backend/models/`)

| 模型 | 表名 | 关键字段 |
|------|------|----------|
| `User` | users | id, username, password_hash, totp_secret |
| `Account` | accounts | id, account_name, api_id, api_hash, proxy, status |
| `LoginLog` | login_logs | id, username, ip_address, user_agent, detail, success |

> 旧版 `Task` / `TaskLog` ORM 模型已随 `/api/tasks` 体系一并移除，
> 签到任务与历史改存 JSON 文件（见 `services/sign_tasks.py`）。

### Pydantic Schemas (`backend/schemas/`)

- `auth.py`: LoginRequest, TokenResponse, UserOut
- `account.py`: AccountCreate, AccountUpdate, AccountOut
- `sign_batch.py`: 签到任务批量操作请求/响应

## 服务层 (`backend/services/`)

| 服务 | 职责 |
|------|------|
| `sign_tasks.py` | 签到任务门面：CRUD、执行编排、日志收集、历史查询（组合下方多个 Mixin 模块） |
| `sign_task_runner.py` | 单任务执行流水线（登录/锁/冷却/重试/补抓） |
| `sign_task_history_*.py` | 历史条目格式化、文件 IO、索引、查询、运维清理 |
| `sign_task_crud.py` / `sign_task_chats.py` / `sign_task_group.py` 等 | 任务 CRUD、会话缓存、任务聚合 |
| `keyword_monitor/` | 关键词监听服务包（`runtime.py` 主循环 + `continue_actions.py` 继续动作 + `rules.py` 匹配 + `hits.py` 命中记录 + `sharding.py` 分片） |
| `telegram/` | Telegram 账号管理包（`accounts.py` 登录流程、`login_qr.py` QR 登录状态机） |
| `push_notifications.py` | 推送通知（Telegram Bot / Bark / Server酱 / 自定义 URL） |
| `users.py` | 管理员账号初始化与用户管理 |
| `config.py` + `config_mixins.py` | 配置门面 + 领域 Mixin（全局设置/签到任务/AI/Telegram 凭据/导入导出） |
| `device_keepalive.py` | 账号会话保活 |
| `runtime_settings.py` | 运行时可改设置解析（面板全局设置优先，环境变量兜底） |
| `webdav_client.py` | WebDAV 备份上传 |

### TelegramService 核心设计 (`services/telegram/`)

**登录流程**（两阶段 + 四阶段）：
1. `request_code` → 发送验证码到手机
2. `verify_login` → 提交验证码完成登录（或触发 QR / 2FA 分支）
3. `start_qr_login` → 生成 QR 码并监听扫码状态
4. `submit_qr_password` → 提交 2FA 密码完成扫码登录

**并发控制**：
- 账号级异步锁（`asyncio.Lock` per account_name）
- 全局信号量限制同时登录数
- `_login_sessions` / `_qr_login_sessions` 全局字典在阶段间传递 client

**DC 迁移**：自动检测并重试（最多 2 次循环）

## 工具层 (`backend/utils/`)

共 14 个文件，按职责分组：

| 模块 | 职责 |
|------|------|
| `time.py` | UTC 时间工具（utc_now, utc_now_iso, utc_now_iso_z_seconds 等） |
| `time_window.py` | HH:MM 时间窗解析与跨午夜判断（静默时段/随机窗口共用） |
| `atomic_io.py` | JSON 原子读写（进程内锁 + fsync + rename，全项目统一入口） |
| `tg_session.py` | TG 会话持久化（accounts.json）、并发信号量、session/代理统一解析 |
| `task_logs.py` | 流程日志解析（时间戳去除、最后目标消息提取） |
| `storage.py` | 数据目录发现/覆盖/回退机制 |
| `cache.py` | 线程安全 LRU+TTL 内存缓存（签到任务列表） |
| `memory_monitor.py` | 进程内存监控 + RSS 告警 + 自动 GC |
| `account_locks.py` / `names.py` / `proxy.py` / `paths.py` | 账号锁、存储名校验、代理标准化、目录准备 |
| `version_info.py` | 版本解析与远程更新检查 |

> 历史最近列表：`sign_task_history_index` 维护 `history/_recent_index.jsonl`，SSE/Dashboard 优先读索引。

## 任务调度 (`backend/scheduler/`)

- **APScheduler** (AsyncIOScheduler) 基于 cron 表达式调度
- 支持 5/6 位 cron 和 `HH:MM` / `HH:MM:SS` 简写
- 每日凌晨 3 点执行维护任务（清理旧日志）
- 签到任务支持 `fixed`/`range`/`listen` 三种执行模式
- `range` 模式在时间范围内随机延迟执行
- 实例锁（`instance_lock.py`）：仅锁持有者注册业务 job，支持多副本部署

## 关键词监控 (`backend/services/keyword_monitor/`)

- 基于 Pyrogram MessageHandler 实时监听消息
- 支持 `contains`/`exact`/`regex` 匹配模式
- 推送渠道：Telegram Bot / Bark / 自定义 URL / 消息转发 / Server酱
- 支持 `continue` 模式：命中关键词后继续执行后续动作
- 支持 Bot 命令触发（可自定义命令前缀）
- 重启去重：按 (账号, 会话) 持久化已处理消息水位（`keyword_monitor/seen.json`）

## 测试与质量

- **框架**: pytest + pytest-asyncio
- **运行**: `pytest`（根目录）
- **覆盖**: pytest-cov 最低 40%（当前实测 ~45%）
- **测试目录**: `tests/`，含 factories、fixtures、mocks 三层辅助结构
- **主要测试**: API 层、服务层、核心模块、配置、缓存、异步 IO、内存监控、批量 API、任务运行器、关键词监控、日志优化、AI 工具

## 常见问题 (FAQ)

**Q: 后端如何与 tg_signer 交互？**
A: `backend/services/sign_tasks.py` 中的 `BackendUserSigner` 继承 `tg_signer.core.UserSigner`，适配后端目录结构并禁止交互式输入。

**Q: session 管理方式？**
A: 支持 file 模式 (`.session` 文件) 和 string 模式 (`.session_string` 文件)。启动时自动预导出 string 以避免 SQLite 锁。

**Q: 签到任务如何存储？**
A: 签到任务以 JSON 文件形式存储在 `signs_dir/account_name/task_name/config.json`，由 `ConfigService` 管理读写。

**Q: 旧版任务体系（tasks.py / ORM Task）现状？**
A: 已**完全移除**：`/api/tasks` 路由、ORM `Task`/`TaskLog` 模型与批量旧接口均不存在，
统一使用 `/api/sign-tasks` + `POST /batch/sign-tasks`（文件存储）。残留旧表可用 `tools/check_legacy_tasks.py` 盘点。

## 相关文件清单

- `main.py` — FastAPI 应用入口
- `core/config.py` — 配置模型
- `core/database.py` — 数据库引擎
- `core/auth.py` — JWT 认证
- `core/security.py` — 密码哈希
- `core/rate_limit.py` — 速率限制
- `api/routes/__init__.py` — 路由注册
- `api/routes/auth.py` — 认证路由
- `api/routes/user.py` — 用户路由
- `api/routes/accounts.py` — 账号路由
- `api/routes/sign_tasks_v2.py` — 签到任务路由
- `api/routes/logs.py` — 日志路由
- `api/routes/config.py` — 配置路由
- `api/routes/events.py` — SSE 事件路由
- `api/routes/batch.py` — 批量操作路由
- `api/routes/ops.py` — 运维路由
- `api/routes/keyword_hits.py` — 关键词命中路由
- `models/` — ORM 模型
- `schemas/` — Pydantic 模型
- `services/` — 服务层（含 keyword_monitor/ 与 telegram/ 包）
- `scheduler/__init__.py` — 任务调度
- `utils/` — 工具函数

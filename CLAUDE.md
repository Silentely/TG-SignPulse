# TG-SignPulse

> Telegram 消息监测系统 — 自动化 Telegram 签到、消息发送、关键词监控、AI 回复等任务的统一管理面板。

## 变更记录 (Changelog)

| 日期 | 变更内容 |
|------|----------|
| 2026-06-30 | 初始化根级 CLAUDE.md，含架构总览、模块索引、Mermaid 结构图 |
| 2026-06-30 | 补扫：TelegramService 登录流程、4 个后端路由、3 个前端 Views、tg_signer 核心类 |
| 2026-06-30 | 补扫：backend/utils/ 13 个工具模块、tools/ 迁移脚本、前端剩余 3 个 Views |
| 2026-06-30 | 补扫：前端 Composables、tg_signer/config.py 配置模型；验证 5 项关键发现 |
| 2026-06-30 | 补扫：tg_signer/core.py 前半段（Client 生命周期）、前端 13 个 Components；规划 token/any 修复方案 |
| 2026-07-01 | 新增账号设备管理、设备保活、官方消息查看、批量状态检查功能 |
| 2026-07-30 | 删除 pyotp 根 shim 与四处死代码；收敛凭据解析/JWT/前端通知/账号状态公共入口；批量写延迟缓存刷新；覆盖率门槛升至 40% |
| 2026-07-31 | print_exc 收敛为结构化日志并清理注释死代码；历史清理/回复解析/空备份清理等 6 处静默异常补诊断日志；修复历史运维模块乱码 docstring；print_to_user 编码兜底改为 ascii 使回退真正生效；tg_signer/utils 覆盖率 35%→100%（新增 14 条测试） |
| 2026-07-31 | 静默 except 收尾 11 处（通配任务配置写入失败升 warning，其余按级别补诊断日志，过期历史清理收窄为 OSError）；tg_signer/security 覆盖率 56%→100%（新增 18 条测试）；前端 typecheck/vitest 287 条/生产构建全绿 |
| 2026-07-31 | 集中补测长尾模块——telegram/sessions 23%→96%（登录会话释放与过期/超量清理）、tg_signer/pydantic_compat 57%→97%（鸭子类型命中 v2 分支与 dump_json）、backend/utils/task_logs 71%→98%（日志提取器全分支）；新增 23 条测试 |
| 2026-07-31 | 攻克 sign_task_runner 覆盖率 1%→93%——FakeSvc/FakeSigner 替身穿透成功/失败/超时/重试/冷却/强失败翻转/session 双模式/补抓超时分支，新增 24 条测试，总覆盖率 46%→48% |
| 2026-07-31 | 文档一致性：tg_signer/core.py 单文件行号锚点重锚为 client.py/runtime.py 拆分后真实结构（README 中英文同步）；删除 pyproject 中已不存在 shim 文件的 per-file-ignores 死配置 |
| 2026-07-31 | 修正 tasks 指南中旧 `/api/tasks` "默认只读"过时表述（实际已完全移除，改链 FAQ）；sign_task_backend 覆盖率 54%→100%（TaskLogHandler 规范化/回退/溢出/容错与 task_dir 三级解析/交互禁令，新增 10 条测试）；前端 bundle 分析确认分包健康无需干预 |
| 2026-07-31 | 通知链路补测——sign_task_notify 10%→100%（门控/静默时段/话题 ID 解析/失败与成功推送容错/mark_account_invalid 幂等通知/check_account_before_task 预检全分支含 fail-open）、server_chan 12%→100%（标准与 sctp 双 URL、参数合并、非法 sendkey 报错）；新增 36 条测试 |
| 2026-07-31 | 提交信息规范化：未推送历史中的过程性字眼改写为描述式表述，变更记录同步去除编号前缀 |
| 2026-07-31 | 功能修复四处：设备保活间隔配置非数字值不再导致整轮 500（容错解析并夹取 1~170 天），运行中响应的 enabled 改为如实读取而非硬编码 True；账号日志 task_name 为空串时统一回落默认名并删除第二兜底；logs 路由校验式日期调用补意图注释。device_keepalive 覆盖 16%→84%（新增 13 条用例含间隔夹取/启停门控/忙响应/状态持久化），总测试 1047 条 |
| 2026-07-31 | 路由层补测——routes/accounts 33%→96%（登录/QR 全流程错误映射、批量状态 Job 增删查消、最近/账号日志映射与限长夹取、导出内容断言、设备/官方消息、头像缓存三级回退、改名更新路径）、routes/events 36%→91%（SSE 字节编码/去重键/令牌校验、事件流种子去重/兜底扫描与容错/心跳）；新增 69 条测试，总覆盖 48.86%→50.48% |

## 项目愿景

TG-SignPulse 是一个基于 Node.js (Vue 3) + Python (FastAPI) 的 Telegram 自动化任务管理平台，提供 Web 面板统一管理多个 Telegram 账号的定时签到、消息交互、关键词监控和 AI 辅助回复。

## 架构总览

```mermaid
graph TD
    A["(根) TG-SignPulse"] --> B["frontend/"];
    A --> C["backend/"];
    A --> D["tg_signer/"];
    A --> E["docs/"];
    A --> F["tests/"];
    A --> G["tools/"];
    B --> B1["Vue 3 + Vite + Pinia"];
    C --> C2["FastAPI + SQLAlchemy + APScheduler"];
    D --> D3["Pyrogram/kurigram + Click CLI"];
    E --> E4["VitePress 文档站"];
    F --> F1["pytest 测试套件"];
    G --> G2["迁移工具"];

    click B "./frontend/CLAUDE.md" "查看 frontend 模块文档"
    click C "./backend/CLAUDE.md" "查看 backend 模块文档"
```

### 技术栈

| 层级 | 技术选型 |
|------|----------|
| 前端 | Vue 3 + TypeScript + Vite + Pinia + Tailwind CSS + vue-i18n |
| 后端 API | FastAPI + SQLAlchemy + APScheduler + Pydantic v1 |
| Telegram 引擎 | Pyrogram / kurigram (tg_signer 子包) |
| 数据库 | SQLite (WAL 模式) |
| 认证 | JWT (HS256) + bcrypt + TOTP (pyotp) |
| 部署 | Docker 多阶段构建 + GHCR + docker-compose |
| 文档 | VitePress |
| 测试 | pytest + pytest-asyncio + pytest-cov |

## 模块索引

| 模块 | 路径 | 语言 | 职责 |
|------|------|------|------|
| 前端面板 | `frontend/` | TypeScript/Vue | Web 管理界面，Dashboard/Accounts/Tasks/Logs/Settings |
| 后端 API | `backend/` | Python | FastAPI REST 接口、任务调度、账号管理、签到执行 |
| Telegram 引擎 | `tg_signer/` | Python | Pyrogram 封装、签到/监控 CLI、配置模型 |
| 文档站 | `docs/` | Markdown/VitePress | 用户指南、部署文档、架构参考 |
| 测试 | `tests/` | Python | pytest 单元/集成测试 |
| 工具 | `tools/` | Python | 迁移脚本（session 导出、Bot 监听测试） |

## 运行与开发

### 前置要求

- Python 3.10-3.13
- Node.js 22.23.1（以 `.nvmrc` 为准；CI 与 Docker 使用同一版本）

### 本地开发

```bash
# 后端 (端口 8080)
pip install -e ".[dev]"
uvicorn backend.main:app --host 127.0.0.1 --port 8080

# 前端 (端口 3000，代理 /api 到 8080)
cd frontend
npm install
npm run dev

# 文档站 (端口 5173)
npm run docs:dev
```

### Docker 部署

```bash
# 构建并运行
docker-compose -f docker-compose.panel.yml up -d

# 或使用 GHCR 镜像
docker run -d -p 3000:3000 -v ./data:/data ghcr.io/<owner>/tg-signpulse:latest
```

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `APP_HOST` | `127.0.0.1` | 后端监听地址 |
| `APP_PORT` | `3000` | 后端监听端口 |
| `APP_DATA_DIR` | 自动检测 | 数据目录路径 |
| `APP_SECRET_KEY` | 自动生成 | JWT 签名密钥 |
| `ADMIN_PASSWORD` | 随机生成 | 初始管理员密码 |
| `LOG_LEVEL` | `INFO` | 日志等级 |
| `TZ` | `Asia/Hong_Kong` | 时区 |

## 测试策略

- **框架**: pytest + pytest-asyncio
- **覆盖**: `pytest-cov` 最低 40% 门槛（当前实测 ~45%）
- **运行**: `pytest` (根目录)
- **测试目录**: `tests/`，含 factories、fixtures、mocks 三层结构
- **主要测试文件**: `test_api.py`, `test_core.py`, `test_services.py`, `test_signer_isolation.py`, `test_config.py`, `test_utils.py`, `test_cache.py`, `test_sign_task_history_index.py`, `test_memory_monitor.py`, `test_batch_api.py`, `test_task_runner.py`, `test_keyword_monitor.py`, `test_log_optimization.py`, `test_ai_tools.py`

## 编码规范

- **Python**: 遵循 PEP 8，使用 ruff 做静态检查 (line-length=88)
- **TypeScript**: vue-tsc 严格模式 + Vite 构建
- **注释**: 中文注释，描述意图与使用方式
- **提交语言**: 中文 Commit 信息

## 关键架构洞察（补扫 2026-06-30）

### tg_signer/core/ 包（已拆分：client.py 502 行 + runtime.py 3036 行 + __init__.py 76 行）

`__init__.py` 透传全部公共符号并承担副作用导入（触发 `_patched_invoke` 等 monkey-patch 装配），外部仍按 `from tg_signer.core import UserSigner` 使用。

| 类 | 位置 | 职责 |
|----|----------|------|
| `UserSigner` | runtime.py 600-2751 | 自动签到执行器，继承 `BaseUserWorker[SignConfigV3]`，含 cron 调度、会话预热（5 级回退）、6 种动作类型、流程级重试 |
| `UserMonitor` | runtime.py 2752-3022 | 消息监控器，继承 `BaseUserWorker[MonitorConfig]`，规则匹配 → 外部转发（UDP/HTTP）→ AI 回复 → Server酱推送 |

**AI 交互场景**（5 种）：计算题、图片 OCR、图片选按钮、计算后点击、监控回复

### backend/utils/ 工具层

| 热模块 | 职责 |
|--------|------|
| `time.py` | 统一 UTC 时间（9 处引用，全模块最热） |
| `tg_session.py` | 会话持久化 + 并发信号量（352 行，最大文件） |
| `task_logs.py` | 流程日志解析（时间戳去除、目标消息提取） |
| `storage.py` | 数据目录发现/覆盖/回退 |
| `proxy.py` | 代理 URL 标准化 |
| `account_locks.py` | 账号级异步锁 |

> 工具层：`cache.TTLCache` 已接入签到任务列表缓存；`memory_monitor` 在 main 启动；历史列表走 `sign_task_history_index`；SSE 走 `sign_history_events` 进程内总线（30s 索引兜底）

### tg_signer/config.py 配置模型（563 行）

**版本迁移链**：`SignConfigV1` → `SignConfigV2` → `SignConfigV3`（当前）

| 模型 | 用途 |
|------|------|
| `SignConfigV3` | 当前签到配置（chats + sign_at + random_seconds） |
| `SignChatV3` | 单 chat 配置（actions 列表 + message_thread_id） |
| `SignAction` + 8 子类 | 动作多态（discriminated by `action` 字段） |
| `MonitorConfig` | 关键词监控配置（match_cfgs 列表） |
| `MatchConfig` | 消息匹配规则（chat + user + text + 转发/推送） |

**8 种动作类型**：发送文本、发送骰子、按文本点击键盘、按图片选选项、计算题回复、图片识别回复、计算后点击按钮、关键词监听通知

**设计特点**：
- `BaseJSONConfig.load()` 自动尝试旧版本迁移
- Pydantic v1/v2 兼容
- `MatchConfig` 封装消息匹配逻辑（exact/contains/regex/all）

### tg_signer/core/ 基座符号（拆分后重锚）

| 类/函数 | 位置 | 职责 |
|---------|------|------|
| `Client(BaseClient)` | client.py 216-343 | Pyrogram 客户端封装，引用计数共享访问，自动重连 |
| `get_client()` | client.py 377-428 | 客户端工厂，全局 `_CLIENT_INSTANCES` 缓存 |
| `close_client_by_name()` | client.py 429-473 | 强制关闭客户端，5s 锁超时 |
| `BaseUserWorker(Generic[ConfigT])` | runtime.py 117-548 | 任务/监控基类，含配置加载、登录、消息发送、AI 工具获取 |
| `Waiter` | runtime.py 549-577 | 异步事件集合（add/discard/sub/clear） |
| `UserSignerWorkerContext` | runtime.py 578-599 | 签到上下文（消息缓存、回调答案、停止标志） |

**Client 生命周期**：
- 连接：`__aenter__` → 引用计数 +1 → 首次连接重试 5 次（SQLite 锁等待 2+attempt*3 秒）
- 断开：`__aexit__` → 引用计数 -1 → 归零时 stop + 清理全局字典
- 调用：`_patched_invoke` 信号量限流 50 + FloodWait 指数退避

### 前端 Components（13 个）

| 类别 | 组件 | 复杂度 |
|------|------|--------|
| 基础 UI | Modal, CustomSelect, MultiSelect, DatePicker, GlobalToast, LanguageSwitch | 低-中 |
| 账号 | AddAccountModal（3 种登录流程）, EditAccountModal | 中-高 |
| 任务 | AddTaskModal, EditTaskModal, TaskForm（17 ref 自动 buildPayload）, TaskLogsModal（WS+HTTP 降级） | 中-高 |
| 设置 | UserProfileModal（用户名/密码/TOTP 三 Tab） | 高 |

### 前端 Composables

| 文件 | 引用数 | 状态 |
|------|--------|------|
| `useI18n.ts` | 17 | 核心依赖 |
| `useTheme.ts` | 2 | 正常 |
| `useToast.ts` | 1 | show 方法未被调用 |


### 双任务体系

| 体系 | 路由 | 存储 | 服务 | 状态 |
|------|------|------|------|------|
| 旧版 | `tasks.py` + `POST /batch/tasks` | SQLAlchemy ORM | `services/tasks.py` | **已弃用** |
| 新版 | `sign_tasks_v2.py` + `POST /batch/sign-tasks` | JSON 文件 | `services/sign_tasks.py` | **主路径** |

失败分类：`backend/services/sign_task_failure.py`（写入历史 `failure_category`）。  
运维：`/api/ops/scheduled-jobs`、`/backup/status`、`/backup/export`、`/memory`。  
旧任务：`/api/tasks` 路由与 ORM Task/TaskLog 模型已移除；请使用 sign-tasks。残留表可用 `tools/check_legacy_tasks.py` 盘点。  
监听分片：`APP_MONITOR_SHARD=i/n`、`APP_MONITOR_ACCOUNT_ALLOWLIST`。

## AI 使用指引

- 修改代码前必须先研读对应模块的 CLAUDE.md
- 跨模块改动需理解 `tg_signer/core/client.py` 的 Client 生命周期和 `backend/services/` 的调用链
- 配置模型定义在 `tg_signer/config.py`，后端适配在 `backend/services/sign_tasks.py`
- 前端 API 调用集中在 `frontend/src/lib/api.ts`，类型定义在 `frontend/src/lib/types.ts`
- 登录流程改动需同时理解 `telegram.py` 的两阶段/四阶段设计和全局 session 字典

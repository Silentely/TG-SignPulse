# 配置参考

## 核心环境变量

| 变量 | 默认值 | 必须 | 说明 |
|------|--------|------|------|
| `APP_SECRET_KEY` | 自动生成并落盘 | ✅ 生产必设 | 面板 JWT 密钥 |
| `ADMIN_PASSWORD` | 随机生成 | ✅ 建议设置 | 首次启动时 `admin` 的初始密码 |
| `APP_CORS_ALLOW_ORIGINS` | `http://127.0.0.1:3000,http://localhost:3000` | | 允许访问后端 API 的前端来源（逗号分隔） |
| `APP_DATA_DIR` | `/data` | | 数据目录 |
| `APP_HOST` | `127.0.0.1` | | 本地直接运行时的监听地址 |
| `APP_PORT` | `3000` | | 本地直接运行时的监听端口 |
| `PORT` | `8080` | | Docker 容器内实际监听端口 |
| `TZ` | `Asia/Hong_Kong` (本地) / `Asia/Shanghai` (容器) | | 时区，影响任务调度 |
| `LOG_LEVEL` / `APP_LOG_LEVEL` | `INFO` | | 后端日志级别，可选 `DEBUG`、`INFO`、`WARNING`、`ERROR`、`CRITICAL` |
| `APP_DATABASE_URL` / `DATABASE_URL` | （空=本地 SQLite） | | SQLAlchemy URL，可切换 Postgres 等 |
| `APP_SCHEDULER_LOCK` | `1` | | 多实例调度文件锁；`0` 关闭 |
| `APP_LEGACY_TASKS_READONLY` | `1` | | 旧 `/api/tasks` 写操作禁用（410）；测试/临时兼容可设 `0` |
| `APP_MONITOR_SHARD` | （空） | | 监听分片 `i/n`，如 `0/3` |
| `APP_MONITOR_ACCOUNT_ALLOWLIST` | （空） | | 逗号分隔，仅这些账号参与关键词监听 |
| `APP_VERSION` | （空=使用包版本） | | 覆盖显示/比较用版本号；空或 `0.0.0` 占位回退包版本 |
| `GIT_SHA` | （空） | | Git commit SHA |
| `GIT_BRANCH` | （空） | | Git 分支或 tag 名 |
| `BUILD_TIME` | （空） | | UTC 构建时间 ISO 字符串 |
| `APP_UPDATE_CHECK` | `1` | | `0/false/off` 关闭服务端远程版本检查 |
| `APP_UPDATE_CHECK_URL` | GitHub Releases latest | | 远程版本 JSON 源（必须 https） |

### 时区管理

时区可通过两种方式配置：

**方式一：环境变量（部署时）**

在 Docker Compose 或启动命令中设置 `TZ` 环境变量：

```yaml
environment:
  - TZ=Asia/Shanghai
```

**方式二：Web 面板（运行时）**

进入 **Settings → 通用设置 → 时区**，选择目标时区后保存。支持 22 个常用时区：

| 区域 | 可选时区 |
|------|----------|
| 亚洲 | Shanghai、Hong Kong、Tokyo、Seoul、Singapore、Taipei、Bangkok、Dubai、Kolkata |
| 欧洲 | London、Berlin、Paris、Moscow |
| 美洲 | New York、Chicago、Denver、Los Angeles、Sao Paulo |
| 大洋洲/非洲 | Sydney、Cairo |
| 通用 | UTC |

**生效规则：**

- 面板设置优先于环境变量
- 新创建的调度任务立即使用当前时区
- 已有任务的触发器时区需要重启服务后生效（面板会输出日志提示）
- 时区值遵循 IANA 时区数据库标准
| `APP_TOTP_VALID_WINDOW` | `1` | | 面板 2FA 时间窗口容差（0=仅当前30s） |
| `APP_ACCESS_TOKEN_EXPIRE_HOURS` | `12` | | JWT Token 过期时间（小时） |

## CORS 部署拓扑

`APP_CORS_ALLOW_ORIGINS` 只影响浏览器跨域访问 API 的场景：

- 前后端同源部署：例如统一通过 `https://panel.example.com` 访问，通常不需要额外放宽 CORS。
- 前端独立域名：例如前端是 `https://app.example.com`、后端是 `https://api.example.com`，必须把前端完整 origin 写入 `APP_CORS_ALLOW_ORIGINS`。
- 本地开发：默认允许 `http://127.0.0.1:3000` 和 `http://localhost:3000`。

生产环境不要使用通配符；多 origin 用英文逗号分隔。

> 环境变量变更规范见 [开发规范 - 代码变更原则](development.md#代码变更原则)。

## Telegram 相关

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TG_API_ID` | 内置默认 | Telegram API ID（可选，从 my.telegram.org 获取自定义值） |
| `TG_API_HASH` | 内置默认 | Telegram API HASH（可选，同上） |
| `TG_SESSION_MODE` | `file` | 会话模式：`file`（本地 SQLite）/ `string`（内存+JSON） |
| `TG_SESSION_NO_UPDATES` | `0` | 是否禁止接收 updates（仅 string 模式） |
| `TG_NO_UPDATES` | `0` | `TG_SESSION_NO_UPDATES` 的兼容别名 |
| `TG_GLOBAL_CONCURRENCY` | 自动（CPU核心数，上限5） | 全局 Telegram 操作并发上限，可通过此变量覆盖自动值 |
| `TG_PROXY` | 无 | CLI / 执行层的兜底代理 |

### 获取 Telegram API 凭证

`TG_API_ID` 和 `TG_API_HASH` 是使用 Telegram API 的必要凭证，需要从 Telegram 官方申请：

1. 打开 [https://my.telegram.org](https://my.telegram.org)
2. 使用你的 Telegram 手机号登录（输入手机号后会收到验证码）
3. 登录后点击 **「API development tools」**
4. 填写应用信息（App title 和 Short name 可随意填写，其他字段可留空）
5. 点击 **「Create application」**
6. 页面会显示 `App api_id` 和 `App api_hash` — 分别对应 `TG_API_ID` 和 `TG_API_HASH`

> ⚠️ 每个 Telegram 账号只能创建一个 API 应用。请妥善保管凭证，不要提交到公开仓库。

在 Docker Compose 中配置：

```yaml
environment:
  - TG_API_ID=12345678
  - TG_API_HASH=abcdef1234567890abcdef1234567890
```

或在面板「系统设置 → Telegram API」中填写。

## 任务执行相关

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SIGN_TASK_EXECUTION_TIMEOUT` | `300` | 单次任务执行超时（秒） |
| `SIGN_TASK_ACCOUNT_COOLDOWN` | `5` | 同一账号两次执行间的冷却时间（秒） |
| `SIGN_TASK_FLOW_RETRY_ATTEMPTS` | `1` | 按钮点击失败后重试整个流程的次数（默认不重试；设为 `>1` 时启用流程级重试） |
| `SIGN_TASK_RETRY_BACKOFF_STEPS` | `0` | 流程重试时回退的步数（0 = 从失败步骤继续，不重发已完成的步骤） |
| `SIGN_TASK_HISTORY_MAX_ENTRIES` | `100` | 每个任务保留的历史记录条数 |
| `SIGN_TASK_HISTORY_MAX_FLOW_LINES` | `5000` | 历史记录中保留的最大流程日志行数 |
| `SIGN_TASK_HISTORY_MAX_LINE_CHARS` | `2000` | 单行日志最大字符数 |
| `SIGN_TASK_HISTORY_MAX_AGE_DAYS` | `3` | 启动时清理超过 N 天的 history/*.json |
| `SIGN_TASK_LIST_CACHE_TTL` | `30` | 任务列表内存缓存秒数 |
| `SIGN_TASK_ACCOUNT_COOLDOWN` | `5` | 同账号连续执行冷却秒数 |
| `SIGN_TASK_EXECUTION_TIMEOUT` | `300` | 单次签到执行超时（秒） |
| `SIGN_TASK_LAST_TARGET_HISTORY_LIMIT` | `8` | 回填 last_target 时拉取聊天历史条数 |
| `SIGN_TASK_HISTORY_LOOKBACK` | `12` | 执行中查找按钮/回退处理时拉取的最近消息条数 |
| `SIGN_TASK_POST_SEND_TERMINAL_TIMEOUT` | `3` | 发送文本/骰子后等待 bot「已签到/签到成功」的秒数；`0` 关闭 |

> 说明：已移除「签到前扫历史今日终态即跳过」。手动/定时均直接执行动作流；若 bot 在执行过程中返回「已签到 / 签到成功」等，再停止后续步骤。定时是否当日应跑仍由本地 `sign_record`（`get_now()` / `TZ`·`APP_TIMEZONE`，默认香港时区）控制。

## AI 视觉相关

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AI_VISION_TIMEOUT` | `15` | AI 视觉请求超时秒数（最小 3） |
| `AI_VISION_RETRY_ATTEMPTS` | `2` | AI 视觉请求总尝试次数（含首次请求，最小 1） |
| `AI_VISION_RETRY_DELAY` | `0.6` | 重试基础延迟秒数（线性递增：attempt × delay） |
| `AI_VISION_MAX_EDGE` | `640` | 图片预处理最大边长像素 |
| `AI_VISION_JPEG_QUALITY` | `85` | 图片预处理 JPEG 压缩质量 |
| `AI_VISION_WHITE_THRESHOLD` | `245` | 图片白色边框裁剪阈值 |

## 容器相关

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `APP_AUTO_FIX_DATA_PERMS` | `1` | 容器启动时自动修复 `/data` 权限 |
| `APP_UID` | `10001` | 容器默认运行 UID |
| `APP_GID` | `10001` | 容器默认运行 GID |

## 面板保存的配置文件

这些文件位于数据目录根部，由面板自动管理：

| 文件 | 说明 |
|------|------|
| `.app_secret_key` | JWT 密钥（自动生成） |
| `.admin_bootstrap_password` | 初始管理员密码（自动生成时写入） |
| `.global_settings.json` | 全局设置（面板「系统设置」保存） |
| `.openai_config.json` | AI 配置（面板「AI 设置」保存） |
| `.telegram_api.json` | Telegram API 配置 |

## 全局设置文件

`.global_settings.json` 常见字段：

```json
{
  "sign_interval": 1,
  "log_retention_days": 3,
  "data_dir": "/data",
  "global_proxy": "socks5://user:pass@host:port",
  "telegram_bot_notify_enabled": true,
  "telegram_bot_login_notify_enabled": true,
  "telegram_bot_task_failure_enabled": true,
  "telegram_bot_token": "123456:ABC-DEF...",
  "telegram_bot_chat_id": "123456789",
  "telegram_bot_message_thread_id": null
}
```

## AI 配置文件

`.openai_config.json`：

```json
{
  "api_key": "<Fernet加密的密文>",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o"
}
```

> ⚠️ `api_key` 字段存储的是 Fernet 加密后的密文（以 `gAAAAA` 开头），由面板自动加密/解密。从旧版本升级后首次保存会自动将明文转换为加密格式。

支持任何 OpenAI 兼容接口（如 Azure OpenAI、本地 LLM 等）。

## Telegram API 配置文件

`.telegram_api.json`：

```json
{
  "api_id": "123456",
  "api_hash": "your_hash",
  "is_custom": true
}
```

不设置时使用内置默认配置。自定义配置从 [my.telegram.org](https://my.telegram.org) 获取。

## 数据目录结构

```text
/data
├── db.sqlite                    # 主数据库（SQLite WAL）
├── .app_secret_key              # JWT 密钥
├── .admin_bootstrap_password    # 初始密码
├── .global_settings.json        # 全局设置
├── .openai_config.json          # AI 配置
├── .telegram_api.json           # Telegram API 配置
├── logs/                        # 任务执行日志文件
├── sessions/                    # Telegram 会话
│   ├── accounts.json            # 账号元数据（session string 模式）
│   └── *.session                # Session 文件（file 模式）
└── .signer/                     # 签到引擎工作目录
    ├── signs/                   # 任务配置
    │   └── <account_name>/
    │       └── <task_name>/
    │           └── config.json
    ├── history/                 # 执行历史 JSON
    ├── avatars/                 # 头像缓存
    └── users/                   # 用户信息缓存
```

## 数据目录选择逻辑

系统按以下优先级决定数据目录：

1. `APP_DATA_DIR` 环境变量
2. 数据目录覆盖文件（`.tg_signpulse_data_dir`）
3. `/data`
4. 如果 `/data` 不可写 → 降级到 `/tmp/tg-signpulse`（⚠️ 非持久化）

## 会话模式说明

| 模式 | 存储方式 | 适用场景 |
|------|----------|----------|
| `file` | 本地 `.session` SQLite 文件 | 默认，稳定，适合 amd64 |
| `string` | 内存 + `accounts.json` | arm64 推荐，避免 SQLite 兼容问题 |

切换模式：设置 `TG_SESSION_MODE=string`。

## 安全建议

| 建议 | 说明 |
|------|------|
| 固定 `APP_SECRET_KEY` | 避免容器重建后所有 Token 失效 |
| 设置 `ADMIN_PASSWORD` | 避免使用随机密码后忘记 |
| 启用 HTTPS | 通过 Nginx/Caddy 反向代理 |
| 收紧 CORS | 只允许实际前端域名 |
| 启用 2FA | 面板支持 TOTP 两步验证 |
| 定期备份 | 备份整个 `data/` 目录 |
| 不暴露测试镜像 | `test-*` 镜像仅用于测试环境 |

## 重要默认行为

- `APP_TOTP_VALID_WINDOW` 未设置时，实际默认是 `1`（允许前后各 1 个 30s 窗口）
- `ADMIN_PASSWORD` 未设置时，随机生成密码写入 `.admin_bootstrap_password`
- `APP_SECRET_KEY` 未设置时，自动生成并持久化到 `.app_secret_key`
- `TG_SESSION_MODE=string` 时，session string 存入 `sessions/accounts.json`
- 任务日志默认保留 3 天，由每日凌晨 3 点的维护任务自动清理
- `LOG_LEVEL=DEBUG` 会重新启用 uvicorn access log，但仍会过滤健康检查端点以减少噪音
- TOTP 验证具有重放保护：同一验证码在 2 分钟窗口内不可重复使用
- `TG_GLOBAL_CONCURRENCY` 未设置时，自动根据 CPU 核心数计算（上限为 5）

## 配置缓存行为

`backend.core.config.get_settings()` 使用 `functools.lru_cache()` 缓存环境变量解析结果。

- 进程启动后修改 `.env` 或环境变量不会自动生效，需要重启后端进程。
- 测试中如果临时修改环境变量，需要调用 `get_settings.cache_clear()` 后再重新导入或读取配置。


## 面板高级设置字段（`.global_settings.json`）

以下字段可在系统设置中配置；`null`/空表示回退环境变量或内置默认。

| 字段 | 说明 |
|------|------|
| `sign_interval` | 多账号签到间隔秒数 |
| `sign_task_execution_timeout` | 单次执行超时（秒） |
| `sign_task_account_cooldown` | 账号冷却（秒） |
| `sign_task_flow_retry_attempts` | 流程重试次数 |
| `sign_task_history_max_age_days` | 历史保留天数 |
| `ai_vision_timeout` / `ai_vision_retry_attempts` | AI 视觉超时与重试 |
| `telegram_bot_task_success_enabled` | 任务成功通知 |
| `telegram_bot_quiet_hours_*` | 静默时段 |
| `auto_backup_enabled` / `interval_hours` / `keep` | 自动备份（可选上传 WebDAV） |
| `webdav_url` / `webdav_username` / `webdav_password` / `webdav_remote_dir` | 完整备份 WebDAV 目标（面板「完整备份」；用法见 [WebDAV 备份与恢复](/guide/backup-webdav)） |


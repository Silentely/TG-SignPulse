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
| `APP_TOTP_VALID_WINDOW` | `1` | | 面板 2FA 时间窗口容差（0=仅当前30s） |
| `APP_ACCESS_TOKEN_EXPIRE_HOURS` | `12` | | JWT Token 过期时间（小时） |

## Telegram 相关

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TG_API_ID` | 内置默认 | 自定义 Telegram API ID（从 my.telegram.org 获取） |
| `TG_API_HASH` | 内置默认 | 自定义 Telegram API HASH |
| `TG_SESSION_MODE` | `file` | 会话模式：`file`（本地 SQLite）/ `string`（内存+JSON） |
| `TG_SESSION_NO_UPDATES` | `0` | 是否禁止接收 updates（仅 string 模式） |
| `TG_NO_UPDATES` | `0` | `TG_SESSION_NO_UPDATES` 的兼容别名 |
| `TG_GLOBAL_CONCURRENCY` | `1` | 全局 Telegram 操作并发上限 |
| `TG_PROXY` | 无 | CLI / 执行层的兜底代理 |

## 任务执行相关

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SIGN_TASK_EXECUTION_TIMEOUT` | `300` | 单次任务执行超时（秒） |
| `SIGN_TASK_ACCOUNT_COOLDOWN` | `5` | 同一账号两次执行间的冷却时间（秒） |
| `SIGN_TASK_FLOW_RETRY_ATTEMPTS` | `3` | 按钮点击失败后重试整个流程的次数 |
| `SIGN_TASK_HISTORY_MAX_ENTRIES` | `100` | 每个任务保留的历史记录条数 |
| `SIGN_TASK_HISTORY_MAX_FLOW_LINES` | `5000` | 历史记录中保留的最大流程日志行数 |
| `SIGN_TASK_HISTORY_MAX_LINE_CHARS` | `2000` | 单行日志最大字符数 |

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
  "api_key": "sk-...",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o"
}
```

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

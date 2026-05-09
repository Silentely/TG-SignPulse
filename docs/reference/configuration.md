# 配置参考

## 核心环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_SECRET_KEY` | 自动生成并落盘 | 面板 JWT 密钥，生产环境必须固定 |
| `ADMIN_PASSWORD` | 无 | 首次启动时 `admin` 的初始密码；未设置则生成随机密码 |
| `APP_CORS_ALLOW_ORIGINS` | `http://127.0.0.1:3000,http://localhost:3000` | 允许访问后端 API 的前端来源 |
| `APP_DATA_DIR` | `/data` | 数据目录 |
| `APP_HOST` | `127.0.0.1` | 本地直接运行 FastAPI 时的监听地址 |
| `APP_PORT` | `3000` | 本地直接运行 FastAPI 时的监听端口 |
| `PORT` | `8080` | Docker 容器内实际监听端口 |
| `TZ` | `Asia/Hong_Kong` 本地 / `Asia/Shanghai` 容器 | 时区 |
| `APP_TOTP_VALID_WINDOW` | `1` | 面板 2FA 时间窗口容差 |

## Telegram 相关

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `TG_API_ID` | 内置默认配置 | 自定义 Telegram API ID |
| `TG_API_HASH` | 内置默认配置 | 自定义 Telegram API HASH |
| `TG_SESSION_MODE` | `file` | 会话模式，支持 `file` / `string` |
| `TG_SESSION_NO_UPDATES` | `0` | 是否禁止 updates |
| `TG_NO_UPDATES` | `0` | `TG_SESSION_NO_UPDATES` 的兼容别名 |
| `TG_GLOBAL_CONCURRENCY` | `1` | 全局并发上限 |
| `TG_PROXY` | 无 | CLI / 执行层的兜底代理 |

## 容器相关

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_AUTO_FIX_DATA_PERMS` | `1` | 容器启动时自动修复 `/data` 权限 |
| `APP_UID` | `10001` | 容器默认运行 UID |
| `APP_GID` | `10001` | 容器默认运行 GID |

## 面板保存的配置文件

这些文件会写入数据目录根部：

- `.app_secret_key`
- `.admin_bootstrap_password`
- `.global_settings.json`
- `.openai_config.json`
- `.telegram_api.json`

## 全局设置文件

`.global_settings.json` 常见字段包括：

- `sign_interval`
- `log_retention_days`
- `data_dir`
- `global_proxy`
- `telegram_bot_notify_enabled`
- `telegram_bot_login_notify_enabled`
- `telegram_bot_task_failure_enabled`
- `telegram_bot_token`
- `telegram_bot_chat_id`
- `telegram_bot_message_thread_id`

## AI 配置文件

`.openai_config.json` 常见字段：

```json
{
  "api_key": "sk-...",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o"
}
```

## Telegram API 配置文件

`.telegram_api.json` 常见字段：

```json
{
  "api_id": "123456",
  "api_hash": "your_hash",
  "is_custom": true
}
```

## 数据目录结构

```text
/data
  |- db.sqlite
  |- .app_secret_key
  |- .admin_bootstrap_password
  |- .global_settings.json
  |- .openai_config.json
  |- .telegram_api.json
  |- logs/
  |- sessions/
  |- .signer/
       |- signs/
       |- monitors/
```

## 数据目录选择逻辑

系统按以下顺序决定数据目录：

1. `APP_DATA_DIR`
2. 数据目录覆盖文件
3. `/data`
4. 如果 `/data` 不可写，则降级到 `/tmp/tg-signpulse`

## 重要默认行为说明

- `APP_TOTP_VALID_WINDOW` 未设置时，实际默认是 `1`
- `ADMIN_PASSWORD` 未设置时，不会再使用固定弱密码，而是随机生成
- `APP_SECRET_KEY` 未设置时，系统会自动生成并落盘到数据目录
- `TG_SESSION_MODE=string` 时，账号 session string 会进入 `sessions/accounts.json`

## 安全建议

- 生产环境固定 `APP_SECRET_KEY`
- 明确设置 `ADMIN_PASSWORD`
- 把面板放到 HTTPS 反向代理后
- 缩小 `APP_CORS_ALLOW_ORIGINS` 范围
- 不要在公网暴露测试镜像长期运行
- 定期备份 `data/`


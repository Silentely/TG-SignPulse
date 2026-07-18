# 运维手册

## 面板运维 API

登录后可用（需 JWT）：

| 端点 | 说明 |
| --- | --- |
| `GET /api/ops/scheduled-jobs` | 查看 APScheduler 下次执行时间 |
| `GET /api/ops/backup/status` | 数据目录备份状态与关键路径体积 |
| `POST /api/ops/backup/export` | 下载推荐路径的 tar.gz 备份包 |
| `GET /api/ops/memory` | 进程内存监控统计（若已启动） |
| `GET /api/ops/version` | 本地版本、Git SHA/分支、构建时间、Python 版本 |
| `POST /api/ops/version/check?force=false` | 远程更新检查（GitHub Releases；可关；失败 soft-fail） |
| `POST /api/config/bot/test` | Bot 通知测试发送 |
| `POST /api/config/import-preview` | 配置导入预览（不写盘） |
| `POST /api/sign-tasks/{name}/clone` | 克隆签到任务 |
| `POST /api/ops/backup/export` | 完整备份：已配置 WebDAV 时上传远端；否则回退浏览器下载 |
| `POST /api/ops/backup/webdav/test` | 测试全局设置中的 WebDAV 连通性 |
| `POST /api/batch/sign-tasks` | 新版签到任务批量 enable/disable/delete/run |
| `GET /api/events/sign-history?token=` | 签到历史 SSE（Dashboard 实时流，token 查询参数） |

### 多实例与数据库

| 变量 | 说明 |
| --- | --- |
| `APP_DATABASE_URL` / `DATABASE_URL` | 可选 SQLAlchemy URL；设置后优先于本地 `db.sqlite` |
| `APP_SCHEDULER_LOCK` | 默认 `1`：启用 `data/.scheduler.lock`；`0` 关闭 |
| `APP_LEGACY_TASKS_READONLY` | **默认 `1`（只读）**；写操作返回 410（`detail=LEGACY_TASKS_READONLY`）。临时兼容写可设 `0`。状态见 `GET /api/tasks/legacy-status`（含 `removal_stage` / `ready_for_route_removal`）或 `python tools/check_legacy_tasks.py`。规划：存量清零且只读 → 评估删除旧路由/ORM 表 |
| `APP_MONITOR_ACCOUNT_ALLOWLIST` | 逗号分隔账号名，仅这些账号挂关键词监听 |
| `APP_MONITOR_SHARD` | 形如 `i/n`（如 `0/3`），按账号名哈希分片监听，多实例各跑一个分片 |

### 上线检查清单（dev → 生产）

1. **数据目录**：持久化挂载 `APP_DATA_DIR`（含 `db.sqlite` / `sessions` / `.signer`），确认可写。
2. **旧 API**：面板已用 sign-tasks；发布前执行 `python tools/check_legacy_tasks.py` 或 `GET /api/tasks/legacy-status`。
3. **单实例**：保持 1 个后端写进程；多副本时必须配调度锁 + 监听分片，且**同一账号 session 不共享**。
4. **Postgres（可选）**：设置 `APP_DATABASE_URL` 时安装 `psycopg2-binary`，并先迁移 schema。
5. **反向代理**：按 [Nginx 样例](../deploy/nginx.md) 配置 SSE/WebSocket；`/api/events/*` 关闭缓冲与 access log。
6. **健康检查**：`/healthz`、`/readyz`（含锁与只读状态）；登录后可看 `/api/ops/runtime-status`。
7. **边界冒烟**（可选）：`python scripts/prod_boundary_check.py`

同一 `data/` 上多副本时：只有获得调度锁的实例会注册签到/旧任务 job。Telegram 监听仍建议单实例。

## 健康检查

系统提供三个健康端点：

| 端点 | 用途 |
| --- | --- |
| `/health` | 基础存活检查 |
| `/healthz` | 容器健康检查 |
| `/readyz` | 服务是否完成启动 |

示例：

```bash
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/healthz
curl http://127.0.0.1:8080/readyz
```

当 `/readyz` 返回 `503` 时，说明应用还在启动中。

## 版本与更新检查

- 本地版本真相源：`tg_signer.__version__`。镜像可通过 `APP_VERSION` 覆盖；空值或占位 `0.0.0` 不覆盖包版本。
- 构建元数据：`GIT_SHA`、`GIT_BRANCH`、`BUILD_TIME`（Docker/CI 注入）。
- 远程检查默认开启；内网可设 `APP_UPDATE_CHECK=0`。关闭后面板仍可用浏览器直连 GitHub 检查。
- 自定义源：`APP_UPDATE_CHECK_URL`（**仅 https**；JSON 需含 `tag_name` + 可选 `html_url`）。
- 服务端仅缓存**成功**结果 6 小时；失败不缓存。`force=true` 跳过缓存。前端另有 24 小时 localStorage 缓存。

示例：

```bash
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/ops/version
curl -X POST -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8080/api/ops/version/check?force=true"
```

## 告警配置

建议至少配置三类告警：

| 告警 | 建议阈值 | 响应动作 |
| --- | --- | --- |
| `/readyz` 连续失败 | 3 次以上 | 检查启动日志、数据库锁和数据目录权限 |
| 任务失败率升高 | 15 分钟内失败率超过 30% | 检查账号状态、代理和目标机器人响应 |
| 监听任务无事件 | 预期活跃聊天 30 分钟无命中 | 检查 Telegram 会话、监听任务状态和 updates 设置 |

通知通道可选：

- Telegram Bot 全局通知
- Bark / ServerChan / 自定义 Webhook
- 外部监控系统通过 `/healthz`、`/readyz` 主动探测

## 查看日志

### Docker 日志

```bash
docker logs -f tg-signpulse
```

### 面板内任务日志

适合查看：

- 哪一步动作失败
- AI 动作有没有拿到答案
- 按钮有没有点击成功
- 监听任务是不是命中了关键词

## 备份与配置迁移

面板「设置 → 数据管理」提供两套能力，用途不同：

| 能力 | 内容 | 可否面板导入 | 用途 |
|------|------|--------------|------|
| **配置 JSON** | 任务 / 监控 / 全局与 AI·TG 设置（AI 密钥脱敏） | ✅ 可导入 | 流程迁移、模板拷贝 |
| **完整备份 tar.gz** | `db.sqlite`、`sessions`、`.signer`、配置文件等 | ❌ 仅导出 | 换机 / 灾难恢复 |

### 配置 JSON 注意

- **不含** Telegram 登录会话；导入后账号仍需已登录或重新登录。
- 导出的 `api_key` 为 `***MASKED***`；再导入时**不会**用占位符覆盖服务器上已有密钥。
- 导入成功后会同步调度并尝试重启关键词监听；请刷新页面。

### 完整备份（面板或命令行）

面板「导出备份包」会打包推荐路径（**不含** `.admin_bootstrap_password`）。

宿主机整目录备份示例：

```bash
tar -czf "tg-signpulse-backup-$(date +%F).tar.gz" -C "$(pwd)" data
```

重点内容：

- `db.sqlite`（及 wal/shm）
- `sessions/`
- `.signer/`（任务配置 + 历史）
- `.global_settings.json` / `.openai_config.json` / `.telegram_api.json`

### 从 tar.gz 恢复（面板无上传恢复，手动操作）

1. **停止** 面板服务（避免写冲突）  
2. 将备份解压到 `APP_DATA_DIR`（默认 `/data` 或 `./data`），覆盖同名路径  
3. 确认目录属主/权限可写  
4. **启动** 服务，用原账号登录验证  

```bash
# 示例：备份文件在当前目录，数据目录为 ./data
systemctl stop tg-signpulse   # 按你的部署方式停止
tar -xzf tg-signpulse-backup-YYYYMMDD-HHMMSS.tar.gz -C ./data
# 若 tar 内路径已是 db.sqlite、sessions 等，应直接落在 data 根下
systemctl start tg-signpulse
```

> PostgreSQL 部署时：`db.sqlite` 备份意义不大，请自行 `pg_dump`；sessions 与 `.signer` 仍须备份。

### 自动化备份脚本

生产环境建议用宿主机 cron 定时备份 `data/`：

```bash
#!/usr/bin/env bash
set -euo pipefail

# 解析项目根目录的绝对路径，确保从任意工作目录执行都能正确定位
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_DIR="${APP_DATA_DIR:-$PROJECT_ROOT/data}"

# 验证 data 目录存在
if [ ! -d "$DATA_DIR" ]; then
    echo "错误: 数据目录不存在: $DATA_DIR" >&2
    exit 1
fi

# 解析为绝对路径，确保 APP_DATA_DIR 指向项目外目录时也能正确备份
DATA_DIR="$(cd "$DATA_DIR" && pwd)"

backup_dir="${BACKUP_DIR:-$PROJECT_ROOT/backups}"
mkdir -p "$backup_dir"

ts="$(date +%Y%m%d-%H%M%S)"
tar -czf "$backup_dir/tg-signpulse-data-$ts.tar.gz" \
    -C "$(dirname "$DATA_DIR")" \
    "$(basename "$DATA_DIR")"

find "$backup_dir" -name 'tg-signpulse-data-*.tar.gz' -mtime +14 -delete
```

如果任务运行频率很高，备份前先执行 `docker compose stop app`，备份完成后再启动，避免备份期间发生 SQLite 写锁冲突。

## 恢复

1. 停止容器
2. 替换或还原 `data/`
3. 重新启动容器

```bash
docker compose down
tar -xzf tg-signpulse-backup-2026-05-09.tar.gz
docker compose up -d
```

## 升级策略

### 使用测试镜像

适合先验证：

```bash
docker compose pull
docker compose up -d
```

测试标签建议使用：

- `test-main`
- `test-<feature-branch>`
- `test-<short-sha>`

### 使用正式镜像

确认测试没问题后，再切换到：

- `vX.Y.Z`
- 或 `latest`

## 常规巡检清单

- `/readyz` 是否正常
- `data/` 是否仍可写
- 最近任务失败率是否异常升高
- 账号状态是否出现 `needs_relogin`
- 监听任务是否仍在接收更新
- 代理是否失效
- AI 接口是否还能返回结果

## 常见排障动作

### 检查数据目录可写

```bash
ls -ld data
touch data/.probe && rm data/.probe
```

### 读取首登密码

```bash
cat data/.admin_bootstrap_password
```

### 观察健康状态

```bash
watch -n 5 'curl -fsS http://127.0.0.1:8080/readyz || true'
```

## 升级前建议

- 先备份 `data/`
- 先在测试标签上验证
- 确认 AI、登录、监听、共享任务都能正常工作
- 再把生产环境切到正式标签

## 事件响应手册

### 场景 1：服务不可用

1. 检查 `docker ps` 和 `docker logs --tail=200 tg-signpulse`。
2. 请求 `/healthz` 与 `/readyz`，确认是进程未启动还是启动未完成。
3. 检查 `data/` 权限、磁盘空间和最近一次升级变更。

### 场景 2：数据库锁定

1. 确认没有多个容器实例挂载同一个 `data/`。
2. 检查是否有长时间运行的任务或外部脚本占用 `db.sqlite`。
3. 重启单个应用实例；如果仍复现，降低任务并发并保留日志。

### 场景 3：账号需要重新登录

1. 在面板查看账号状态是否为 `needs_relogin`。
2. 重新完成 Telegram 登录流程。
3. 如果多个账号同时失效，优先检查代理和 Telegram API 配置。

### 场景 4：监听任务不触发

1. 确认任务执行模式是 `listen` 且任务已启用。
2. 检查 `TG_SESSION_MODE`、`TG_SESSION_NO_UPDATES` 和账号会话是否允许接收 updates。
3. 修改监听规则后触发一次调度同步或重启后端，让监听器重建。

### 场景 5：通知发送失败

1. 检查 Telegram Bot token、chat_id、Bark URL、ServerChan sendkey 或自定义 Webhook。
2. 用 `curl` 在宿主机直接访问通知端点，排除网络与 DNS 问题。
3. 对外部 HTTP 通道增加接收端幂等，避免重试导致重复处理。


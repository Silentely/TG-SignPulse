# 运维手册

## 面板运维 API

登录后可用（需 JWT）：

| 端点 | 说明 |
| --- | --- |
| `GET /api/ops/scheduled-jobs` | 查看 APScheduler 下次执行时间 |
| `GET /api/ops/backup/status` | 数据目录备份状态与关键路径体积（含 `backup_target`、WebDAV 就绪状态） |
| `POST /api/ops/backup/export` | 完整备份：根据设置的备份目标策略（`backup_target`：`auto` / `webdav`）上传 WebDAV；未配置或参数 target=download 时回退浏览器下载流 |
| `POST /api/ops/backup/webdav/test` | 测试全局设置中的 WebDAV 连通性 |
| `GET /api/ops/backup/webdav/files` | 列出远端目录 `.spbak` / `.tar.gz` 备份（PROPFIND） |
| `GET /api/ops/backup/webdav/download?name=` | 流式下载指定远端 `.spbak` / `.tar.gz`（安全文件名） |
| `GET /api/ops/memory` | 进程内存监控统计（若已启动） |
| `GET /api/ops/version` | 本地版本、Git SHA/分支、构建时间、Python 版本 |
| `POST /api/ops/version/check?force=false` | 远程更新检查（GitHub Releases；可关；失败 soft-fail） |
| `POST /api/config/bot/test` | Bot 通知测试发送 |
| `POST /api/config/import-preview` | 配置导入预览（不写盘） |
| `POST /api/sign-tasks/{name}/clone` | 克隆签到任务 |
| `GET /api/sign-tasks/runs/active` | 内存中进行中的签到 run（phase / 账号 / 任务） |
| `GET /api/sign-tasks/{name}/run/status` | 单任务 run 状态（含 `state` / `phase` / `failure_category`） |
| `POST /api/sign-tasks/{name}/run/cancel` | 取消进行中的签到 run（协作式 cancel） |
| `POST /api/batch/sign-tasks` | 新版签到任务批量 enable/disable/delete/run |
| `POST /api/events/ticket` + `GET /api/events/sign-history?ticket=` | 签到历史 SSE：先用 Bearer JWT 换 60 秒一次性票据，再用票据建流（URL 不放长效 JWT） |
| `GET /api/accounts/{account_name}/logs/export` | 导出指定账号的纯文本历史执行日志（`.log`） |
| `POST /api/accounts/status/check` | 同步批量账号会话检测（兼容；账号多时易阻塞） |
| `POST /api/accounts/status/check-jobs` | 异步批量账号会话检测 Job（可取消、可查进度） |
| `GET /api/accounts/status/check-jobs/{job_id}` | 查询批量检测 Job 状态 / 结果 |
| `POST /api/accounts/status/check-jobs/{job_id}/cancel` | 取消进行中的批量检测 Job |
| `GET /api/keyword-hits` | 关键词命中记录列表（可按账号/任务过滤） |
| `GET /api/keyword-hits/groups` | 命中记录分组（`group_by=task\|account\|chat`） |
| `GET /api/keyword-hits/export` | 导出命中记录 CSV（UTF-8 BOM） |
| `DELETE /api/keyword-hits` | 清空命中记录（可按账号/任务过滤） |

### JEV 语义引擎与智能自愈 API

| 端点 | 说明 |
| --- | --- |
| `GET /api/semantic/config` | 获取 JEV 语义配置、运行状态、缓存命中率、熔断器状态 (`stats`) 与容量统计 |
| `PATCH /api/semantic/config` | 热更新 JEV 语义引擎配置（`enabled`、`base_url`、`model`、`api_key`、`timeout_seconds`） |
| `POST /api/semantic/test` | 测试 JEV 语义服务连通性（带 SSRF 检查与凭据外送隔离） |
| `GET /api/semantic/observations` | 查询执行中记录的决策上下文观测事件（`Observations`，支持按账号、任务与类型分页筛选） |
| `PUT /api/semantic/observations/{id}/label` | 为观测记录添加或更新人工复核标签与意图 |
| `GET /api/semantic/suggestions` | 查询规则自愈建议列表（`Suggestions`，支持状态过滤：`pending` / `applied` / `dismissed`） |
| `POST /api/semantic/suggestions/{id}/apply` | 采纳指定规则建议并原子热更新对应任务动作配置 |
| `POST /api/semantic/suggestions/{id}/dismiss` | 忽略指定规则建议 |

### 完整备份落点：WebDAV 与本地归档

用户操作步骤见 **[备份与恢复](/guide/backup-webdav)**。实现要点：

1. 上传/测试/列表前前端会先落盘备份连接配置；服务端只读已保存设置。
2. `GET /api/config/settings` 不回传 WebDAV 密码、Bot Token、全局代理与推送矩阵的明文，均仅 `*_set`。
3. 配置 JSON 导出脱敏上述密钥；导入占位不覆盖已有值。
4. **落点策略（`backup_target`）**：
   - `auto`（默认）：已配置 WebDAV 时自动上传至 WebDAV 远端；未配置或参数携带 `target=download` 时回退为浏览器下载流。
   - `webdav`：仅上传至 WebDAV，未配置时报错阻止。
5. **自动备份**：WebDAV 上传成功后清理本地临时副本并按 `auto_backup_keep` 轮转远端旧包；上传失败保留本地副本并发送 Bot 告警通知。
6. 下载为流式响应；恢复须停服后解压覆盖 `APP_DATA_DIR`（面板「灾难恢复指引」提供宿主机与 Docker 环境下的标准恢复命令）。
7. `GET /api/ops/backup/status` 含 `webdav_configured`、`backup_target`、`auto_backup_enabled`、最近本地自动备份列表。

### 多实例与数据库

| 变量 | 说明 |
| --- | --- |
| `APP_DATABASE_URL` / `DATABASE_URL` | 可选 SQLAlchemy URL；设置后优先于本地 `db.sqlite` |
| `APP_SCHEDULER_LOCK` | 默认 `1`：启用 `data/.scheduler.lock`；`0` 关闭 |
| `APP_LEGACY_TASKS_READONLY` | 历史变量，已无路由消费。`/api/tasks` 已删除；盘点 ORM 残留用 `python tools/check_legacy_tasks.py` |
| `APP_MONITOR_ACCOUNT_ALLOWLIST` | 逗号分隔账号名，仅这些账号挂关键词监听 |
| `APP_MONITOR_SHARD` | 形如 `i/n`（如 `0/3`），按账号名哈希分片监听，多实例各跑一个分片 |

### 上线检查清单（dev → 生产）

1. **数据目录**：持久化挂载 `APP_DATA_DIR`（含 `db.sqlite` / `sessions` / `.signer`），确认可写。
2. **旧 API**：`/api/tasks` 已删除；发布前可执行 `python tools/check_legacy_tasks.py` 盘点 ORM 残留。
3. **单实例**：保持 1 个后端写进程；多副本时必须配调度锁 + 监听分片，且**同一账号 session 不共享**。
4. **Postgres（可选）**：设置 `APP_DATABASE_URL` 时安装 `psycopg2-binary`，并先迁移 schema。
5. **反向代理**：按 [Nginx 样例](../deploy/nginx.md) 配置 SSE/WebSocket；`/api/events/*` 关闭缓冲与 access log。
6. **健康检查**：`/healthz`、`/readyz`（含锁与只读状态）；登录后看 `/api/ops/runtime-status`。
7. **边界冒烟**（可选）：`python scripts/prod_boundary_check.py`

同一 `data/` 上多副本时：只有获得调度锁的实例会注册签到/旧任务 job。Telegram 监听仍建议单实例。

## 健康检查

系统提供三个健康端点：

| 端点 | 用途 |
| --- | --- |
| `/health` | 基础存活检查 |
| `/readyz` | 容器健康检查 |
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
- 远程检查默认开启；内网可设 `APP_UPDATE_CHECK=0`。

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

> **观测性说明**：任务执行日志与运行状态是**内存态**，任务结束后约 60 秒、运行状态约 10 分钟无更新即被回收（`ACTIVE_LOG_CLEANUP_DELAY_SECONDS` / `RUN_STATUS_CLEANUP_DELAY_SECONDS`）；面板账号列表有 5 秒 TTL 缓存。历史日志（含完整流程日志）持久化在 `history/`，不受上述回收影响——长时间未刷新看到空的任务日志属正常回收，不是数据丢失。

# 常见问题

## 首次登录密码在哪里

如果你没有设置 `ADMIN_PASSWORD`，系统会自动生成一个随机密码，并写到：

```text
data/.admin_bootstrap_password
```

用户名默认是 `admin`。

## 为什么任务开启了却没有执行

优先检查：

- 执行模式是不是 `listen`
- 定时表达式或时间段是否正确
- 任务是否启用
- 绑定账号是否仍然有效
- `/readyz` 是否正常（含 `scheduler_lock_held`）
- 多实例时是否误配 `APP_MONITOR_SHARD` 导致监听不在本机

## 旧 /api/tasks 接口为什么返回 410

从较新版本起，旧 ORM 任务接口默认只读（`APP_LEGACY_TASKS_READONLY=1`）。  
新功能请使用 `/api/sign-tasks` 与 `/api/batch/sign-tasks`。

- 查看存量：`GET /api/tasks/legacy-status` 或 `python tools/check_legacy_tasks.py`
- 临时兼容写：仅短期设置 `APP_LEGACY_TASKS_READONLY=0`

### 下线时间表（建议）

| 阶段 | 动作 |
|------|------|
| 当前 | 默认只读；面板仅 sign-tasks；运维盘点 ORM 存量 |
| 迁移完成 | `orm_only_count == 0` 后保持只读，外部脚本改调 sign-tasks |
| 后续版本 | 可移除写路径兼容开关；再下一阶段删除 `/api/tasks` 与 ORM Task 表（破坏性，需公告） |

盘点字段：

- `GET /api/tasks/legacy-status` → `removal_stage`、`ready_for_route_removal`
- `python tools/check_legacy_tasks.py --json` → 同上，并列出 `orm_only_names`

## Dashboard 实时日志连不上

优先检查：

- 是否已登录且 token 未过期
- 反向代理是否关闭 SSE 缓冲（见 [Nginx 部署](deploy/nginx.md)）
- 浏览器控制台是否有 EventSource 错误；面板会指数退避重连

## 设置里「导出 JSON」和「完整备份」有什么区别？

| | 配置 JSON | 完整备份 tar.gz |
|--|-----------|-----------------|
| 含任务配置 | ✅ | ✅（在 `.signer`） |
| 含登录会话 | ❌ | ✅ |
| 含数据库 | ❌ | ✅（SQLite） |
| 面板可导入 | ✅ | ❌（需手动解压恢复） |
| AI 密钥 | 导出脱敏，导入不覆盖已有密钥 | 随配置文件原样打包 |

- 只想搬任务流程 → 用 **JSON**  
- 换服务器整机恢复 → 用 **完整备份**（可上传 WebDAV），停止服务后解压到 data 目录再启动（见 [WebDAV 备份与恢复](guide/backup-webdav.md)、[运维手册](reference/ops.md)）

## 如何配置 WebDAV 自动备份？

见 [WebDAV 备份与恢复](guide/backup-webdav.md)：设置 → 完整备份 → 填 URL/账号 → 测试连接 → 开启自动备份并保存。上传成功会清理本地副本并按保留份数轮转远端；失败会尽量发 Bot 通知。

## 是否已经改成 PostgreSQL、取消 SQLite？

**没有。** 默认数据库仍是 **SQLite**（数据目录下的 `db.sqlite`，WAL 模式）。

- 不设置 `APP_DATABASE_URL` / `DATABASE_URL` → 使用 SQLite  
- 设置 `APP_DATABASE_URL=postgresql+psycopg2://...` 并安装 `psycopg2-binary` → 可选使用 PostgreSQL  

项目**支持** Postgres，但**不强制**迁移，也未移除 SQLite 路径。

## 为什么重启后数据丢了

通常是因为没有挂载 `/data`，或者 `/data` 不可写导致程序降级到了 `/tmp/tg-signpulse`。

## 为什么 AI 动作没有反应

优先检查：

- 是否已经配置 `.openai_config.json`
- API Key / Base URL / Model 是否正确
- 该动作是否需要自定义 `ai_prompt`
- 流程日志里是“没有答案”还是“有答案但没有匹配到按钮”

## 当前默认 AI 模型是什么

默认模型是：

```text
gpt-4o
```

## 现在能不能自定义 AI 提示词

可以。任务编辑器和监听任务的后续动作编辑器都支持 `AI 提示词（可选）`。留空使用默认提示词，填写后只对当前动作生效。

## 测试镜像和正式镜像有什么区别

- `dev` / `dev-*`：dev 分支滚动构建，适合预发
- `vX.Y.Z` + `latest` + 浮动 `main`：仅在推送 Git 标签 `v*` 时一次生成（正式版）
- `main` 合并：只跑 CI 测试，**不**构建 Docker；要镜像请打 tag

不要长期把 `dev` 当正式版使用。`latest` 只跟随正式 tag。

## 监听任务为什么没命中

检查：

- `chat_id` 是否正确
- `message_thread_id` 是否填错
- 匹配模式是 `contains`、`exact` 还是 `regex`
- 正则是否写对
- 账号是否开启 updates

## 什么时候用 `string` 会话模式

当你希望：

- 用 session string 统一迁移
- 更方便做容器化备份
- 避免分散的会话文件

否则默认 `file` 模式就够用。


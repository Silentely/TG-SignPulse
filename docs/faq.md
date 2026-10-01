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

## 旧 /api/tasks 接口为什么不可用

旧 ORM 任务 API（`/api/tasks`、`/api/batch/tasks`）已**完全移除**。  
新功能请使用 `/api/sign-tasks` 与 `/api/batch/sign-tasks`。

- 盘点残留 ORM 表（模型已删）：`python tools/check_legacy_tasks.py --json`
- `/readyz` 含 `legacy_tasks_removed: true`
- 旧 SSE `/api/events/logs` 已移除，请改用 `/api/events/sign-history`

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

- 只想迁移任务流程与参数 → 用 **JSON**  
- 换服务器整机恢复 / 容灾 → 用 **完整备份**（支持 WebDAV 远端备份与本地归档下载），停止服务后解压到 data 目录再启动（见 [备份与恢复](guide/backup-webdav.md)、[运维手册](reference/ops.md)，面板内「灾难恢复指引」弹窗提供标准化复制命令）。

## 如何配置 WebDAV 自动备份？

见 [备份与恢复](guide/backup-webdav.md)：进入 **设置** → **数据管理** → **WebDAV 远端备份** 填写 WebDAV 连接信息（或选择坚果云/Nextcloud/InfiniCLOUD/Alist 等快捷预设），点击 **测试连接**。随后在 **定时与保留策略** 中开启自动备份并设定执行间隔与保留份数，点击 **保存备份设置**。WebDAV 远端上传成功后清理本地临时副本并轮转远端旧包；上传失败会保留本地副本兜底并发送 Telegram Bot 告警通知。

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
gpt-5-nano
```

## 现在能不能自定义 AI 提示词

可以。任务编辑器和监听任务的后续动作编辑器都支持 `AI 提示词（可选）`。留空使用默认提示词，填写后只对当前动作生效。

## 测试镜像和正式镜像有什么区别

- `dev` / `dev-*`：dev 分支滚动构建，适合预发
- `main` / `main-<sha>`：main 分支滚动构建，稳定主干镜像
- `vX.Y.Z` + `latest`：仅在推送 Git 标签 `v*` 时一次生成（正式版）

不要长期把 `dev` 当正式版使用。`latest` 只跟随正式 tag；`main` 跟随 main 分支最新提交。

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

否则默认 `file` 模式就足够用。


## 两步验证（TOTP / 2FA）遗失或无法登录怎么办？（应急容灾恢复）

若您开启了两步验证（TOTP），但手机更换、验证器丢失或时间偏移无法生成正确验证码时，系统提供两种应急恢复途径：

### 途径一：容器内部/命令行一键重置（推荐）

通过命令行运行项目内置的安全重置工具：

- **Docker Compose 容器环境**：
  ```bash
  docker compose exec backend python -m scripts.reset_user_totp <用户名>
  ```
  例如重置 admin 用户的 2FA：
  ```bash
  docker compose exec backend python -m scripts.reset_user_totp admin
  ```
- **纯 Python / 本地运行环境**：
  ```bash
  .venv/bin/python -m scripts.reset_user_totp <用户名>
  ```

该命令会直接清空指定用户的 `totp_secret`，并清除会话中待验证状态。执行后即可使用原有密码直接登录，随后进入「用户设置」重新绑定 TOTP。

### 途径二：临时开启环境变量应急放行

出于安全防御考虑，Web 端默认禁止仅凭密码重置两步验证。若无法方便登录容器执行命令，可在环境变量中临时配置放行开关：

1. 在 `docker-compose.yml` 或 `.env` 中添加环境变量：
   ```env
   ALLOW_PASSWORD_ONLY_TOTP_RESET=true
   ```
2. 重启服务后，在登录页面点击「重置两步验证」，输入正确的账号密码即可一键重置。
3. **完成登录并重新配置验证器后，务必移除该环境变量**并重启容器，保持最高安全防护等级。

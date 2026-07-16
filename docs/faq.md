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

## Dashboard 实时日志连不上

优先检查：

- 是否已登录且 token 未过期
- 反向代理是否关闭 SSE 缓冲（见 [Nginx 部署](deploy/nginx.md)）
- 浏览器控制台是否有 EventSource 错误；面板会指数退避重连

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

- `test-*`：来自分支推送，适合测试环境
- `vX.Y.Z`：正式版本
- `latest`：最近一次正式标签版本

不要长期把测试镜像当正式版使用。

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


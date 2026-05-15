# 快速开始

本指南帮助你在 5 分钟内完成部署、登录、添加账号并创建第一个自动化任务。

## 1. 准备环境

| 需求 | 说明 |
|------|------|
| Docker 24+ | 含 Docker Compose |
| Telegram 账号 | 至少一个，需要能接收验证码 |
| 服务器/本机 | 能访问 Telegram（或配置代理） |
| OpenAI API Key | 可选，仅 AI 动作需要 |

## 2. 选择镜像

| 环境 | 镜像 |
|------|------|
| 生产 | `ghcr.io/akasls/tg-signpulse:latest` 或 `ghcr.io/akasls/tg-signpulse:v2.0.0` |
| 测试 | `ghcr.io/akasls/tg-signpulse:test-main` |

## 3. 最小启动

### 方式一：docker run

```bash
docker run -d \
  --name tg-signpulse \
  --restart unless-stopped \
  -p 8080:8080 \
  -v $(pwd)/data:/data \
  -e TZ=Asia/Shanghai \
  -e APP_SECRET_KEY=$(openssl rand -base64 32) \
  -e ADMIN_PASSWORD=your_strong_password \
  ghcr.io/akasls/tg-signpulse:latest
```

### 方式二：Docker Compose

创建 `docker-compose.yml`：

```yaml
services:
  app:
    image: ghcr.io/akasls/tg-signpulse:latest
    container_name: tg-signpulse
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./data:/data
    environment:
      - TZ=Asia/Shanghai
      - APP_SECRET_KEY=replace-with-a-long-random-string
      - ADMIN_PASSWORD=replace-with-a-strong-password
```

启动：

```bash
docker compose up -d
```

### 关键环境变量

| 变量 | 必须 | 说明 |
|------|------|------|
| `APP_SECRET_KEY` | ✅ 强烈建议 | JWT 密钥，不设置则自动生成 |
| `ADMIN_PASSWORD` | ✅ 强烈建议 | 管理员密码，不设置则随机生成到 `data/.admin_bootstrap_password` |
| `TZ` | 建议 | 时区，影响任务调度时间 |

## 4. 打开面板

浏览器访问：`http://服务器IP:8080`

首次登录：

- 用户名：`admin`
- 密码：你设置的 `ADMIN_PASSWORD`
- 如果未设置，查看 `data/.admin_bootstrap_password` 文件

> 💡 登录后建议立即修改密码，并可选开启 TOTP 两步验证。

## 5. 添加 Telegram 账号

进入「账号管理」页面，选择登录方式：

| 方式 | 适用场景 |
|------|----------|
| 短信验证码 | 通用，需要能接收短信 |
| 二维码扫码 | 手机端 Telegram 扫码确认 |

流程：

1. 输入账号名称（自定义标识）
2. 选择登录方式并完成验证
3. 如果账号开启了 Telegram 2FA，补充密码
4. 登录成功后账号出现在列表中

> ⚠️ 如果网络受限，先在「系统设置 → 全局代理」中配置代理。

## 6. 创建第一个任务

推荐先做一个最简单的签到任务：

1. 在账号任务页点击「新建任务」
2. 输入任务名称（如：`每日签到`）
3. 选择目标聊天（搜索机器人或群组）
4. 添加动作序列：
   - 第 1 步：`发送文本` → `/start`
   - 第 2 步：`点击按钮` → `签到`
5. 设置执行时间（cron 表达式或 HH:MM 格式）
6. 保存任务

### 手动测试

保存后点击「运行」按钮手动执行一次，观察实时日志确认是否成功。

## 7. 验证结果

从三个位置确认运行结果：

| 位置 | 查看内容 |
|------|----------|
| 任务列表 | 最近执行状态和时间 |
| 任务历史 | 每次执行的流程日志和机器人回复 |
| Docker 日志 | `docker logs -f tg-signpulse` |

健康检查：

```bash
curl http://127.0.0.1:8080/healthz   # 应返回 {"status":"ok"}
curl http://127.0.0.1:8080/readyz    # 应返回 {"status":"ready"}
```

## 8. 下一步

| 需求 | 文档 |
|------|------|
| 完整部署说明 | [Docker 部署](../deploy/docker.md) |
| 配置 AI 动作 | [AI 动作](ai.md) |
| 监听消息触发 | [关键词监听](keyword-monitor.md) |
| 多账号共用任务 | [任务编排](tasks.md) |
| 所有配置项 | [配置参考](../reference/configuration.md) |

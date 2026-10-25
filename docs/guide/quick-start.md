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
| 生产 | `ghcr.io/silentely/tg-signpulse:latest` 或 `ghcr.io/silentely/tg-signpulse:v2.3.0` |
| 稳定主干 | `ghcr.io/silentely/tg-signpulse:main` 或 `…:main-<sha>` |
| 预发/开发 | `ghcr.io/silentely/tg-signpulse:dev` |

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
  ghcr.io/silentely/tg-signpulse:latest
```

### 方式二：Docker Compose

创建 `docker-compose.yml`：

```yaml
services:
  app:
    image: ghcr.io/silentely/tg-signpulse:latest
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

> 💡 登录后建议立即在 **系统设置** 中修改密码，并可选开启 TOTP 两步验证。

登录成功后将进入系统仪表盘，直观展示活跃账号、任务总览与近 7 天运行成功率统计：

<p align="center">
  <img src="/screenshots/dashboard.png" alt="TG-SignPulse 仪表盘概览" style="border-radius: 8px; border: 1px solid var(--vp-c-divider);">
</p>

## 5. 添加第一个账号

进入 **账号管理** 页面，点击右下角浮动按钮（或列表中的「添加账号」）：

<p align="center">
  <img src="/screenshots/account-modal.png" alt="添加账号方式选择与扫码登录" style="border-radius: 8px; border: 1px solid var(--vp-c-divider); max-width: 600px;">
</p>

| 方式 | 适用场景 |
|------|----------|
| 二维码扫码 | 手机端 Telegram 直接扫码确认，快捷安全 |
| 短信验证码 | 通用，输入手机号并在客户端或短信接收 5 位验证码 |
| 会话导入 | 已有 Telethon/Pyrogram `.session` 或 StringSession 免收码导入 |

流程：

1. 输入账号名称（自定义标识，如 `Main_Account`）
2. 选择登录方式并完成验证（扫码或输入收到的验证码）
3. 如果账号开启了 Telegram 2FA，补充两步验证密码
4. 登录成功后账号即刻显示在账号列表中，并实时显示网络连通状态

> ⚠️ 如果服务器位于受限网络，建议先在 **系统设置** 中配置代理，或在添加账号时指定独立代理。

<p align="center">
  <img src="/screenshots/accounts.png" alt="账号列表与状态监控" style="border-radius: 8px; border: 1px solid var(--vp-c-divider);">
</p>

## 6. 创建第一个任务

进入 **任务编排** 页面，点击右上角 **新建任务**：

<p align="center">
  <img src="/screenshots/task-editor.png" alt="任务动作流编排与参数配置" style="border-radius: 8px; border: 1px solid var(--vp-c-divider); max-width: 720px;">
</p>

推荐从基础的纯文本签到任务开始：

1. 输入任务名称（如：`每日自动签到`）
2. 勾选绑定的执行账号
3. 选择目标聊天（可直接搜索机器人或群组，如 `@DailyBonusBot`）
4. 添加动作序列：
   - 第 1 步：`发送文本` → `/start` 或 `/checkin`
   - 第 2 步：`点击按钮` → 输入按钮文本如 `立即签到`（或使用 AI 视觉答题）
5. 设置执行时间（支持固定时间如 `08:30`，或时间段随机如 `08:00-09:30`）
6. 保存任务

### 手动测试

保存后在任务卡片上点击 **执行** 按钮手动触发一次，观察实时日志确认是否成功：

<p align="center">
  <img src="/screenshots/tasks.png" alt="任务编排管理列表" style="border-radius: 8px; border: 1px solid var(--vp-c-divider);">
</p>

## 7. 验证结果

从三个位置确认运行结果：

| 位置 | 查看内容 |
|------|----------|
| 仪表盘 | SSE 实时日志流与活跃运行卡片 |
| 任务历史 | 每次执行的流程步骤日志和机器人回复 |
| 查看日志页面 | 细粒度失败分类、按账号/任务检索与一键归档导出 |

<p align="center">
  <img src="/screenshots/logs.png" alt="运行日志与执行记录" style="border-radius: 8px; border: 1px solid var(--vp-c-divider);">
</p>

健康检查：

```bash
curl http://127.0.0.1:8080/healthz   # 应返回 {"status":"ok"}
curl http://127.0.0.1:8080/readyz    # 应返回 {"status":"ready"}
```

## 8. 下一步

| 需求 | 文档 |
|------|------|
| 账号设备与指纹防风控 | [账号管理](accounts.md) |
| 多步动作流与自适应调度 | [任务编排](tasks.md) |
| 配置 AI 视觉与计算题 | [AI 动作](ai.md) |
| 监听消息与自动联动 | [关键词监听](keyword-monitor.md) |
| WebDAV 云端备份与灾难恢复 | [备份与恢复](backup-webdav.md) |
| 完整部署说明 | [Docker 部署](../deploy/docker.md) |
| 所有配置项 | [配置参考](../reference/configuration.md) |

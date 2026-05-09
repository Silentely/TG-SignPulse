# 快速开始

## 1. 准备环境

- 一台可以访问 Telegram 的服务器或本机
- Docker 24+ 与 Docker Compose
- 至少一个 Telegram 账号
- 如果要用 AI 动作，还需要一个 OpenAI 兼容接口的 `API Key`

## 2. 选择镜像

测试环境建议使用分支测试镜像：

```bash
ghcr.io/<owner>/tg-signpulse:test-main
```

生产环境建议使用版本标签：

```bash
ghcr.io/<owner>/tg-signpulse:v1.0.0
```

## 3. 最小启动

```bash
docker run -d \
  --name tg-signpulse \
  -p 8080:8080 \
  -e APP_SECRET_KEY=replace-with-a-long-random-string \
  -e ADMIN_PASSWORD=replace-with-a-strong-password \
  -e APP_DATA_DIR=/data \
  -e TZ=Asia/Shanghai \
  -v $(pwd)/data:/data \
  ghcr.io/<owner>/tg-signpulse:test-main
```

如果你不设置 `ADMIN_PASSWORD`，系统会自动生成一个初始密码，并写到 `data/.admin_bootstrap_password`。

## 4. 打开面板

- Docker 部署默认访问：`http://127.0.0.1:8080`
- 本地前端开发模式默认访问：`http://127.0.0.1:3000`

首次登录账号：

- 用户名：`admin`
- 密码：你设置的 `ADMIN_PASSWORD`
- 如果未设置 `ADMIN_PASSWORD`，到数据目录读取 `.admin_bootstrap_password`

## 5. 添加 Telegram 账号

进入“账号管理”后任选一种方式登录：

- 短信验证码登录
- 二维码登录
- 如果账号开启了 Telegram 2FA，再补充密码

如果网络环境受限，先在设置里配置全局代理，或者给当前账号单独填写代理。

## 6. 创建第一个任务

推荐先做一个最简单的签到任务：

1. 选择一个账号
2. 新建任务，输入任务名
3. 选择目标聊天或机器人
4. 第一步动作填写 `发送文本`
5. 文本内容填写 `/start`
6. 第二步动作填写 `点击按钮`
7. 按钮关键词填写 `签到`
8. 保存并手动运行一次

如果对方机器人有识图或计算题验证，再为后续步骤补一个 AI 动作。

## 7. 验证是否成功

你可以从三个位置确认运行结果：

- 任务列表中的最近执行状态
- 任务详情里的历史记录与流程日志
- Docker 日志：`docker logs -f tg-signpulse`

健康检查：

```bash
curl http://127.0.0.1:8080/healthz
curl http://127.0.0.1:8080/readyz
```

## 8. 下一步

- 需要更完整的部署说明，阅读 [Docker 部署](../deploy/docker.md)
- 需要配置 AI，阅读 [AI 动作](ai.md)
- 需要监听消息触发动作，阅读 [关键词监听](keyword-monitor.md)
- 需要多账号共用一套流程，阅读 [任务编排](tasks.md)


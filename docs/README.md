# TG-SignPulse 文档

> 一个面向 Telegram 多账号自动化、任务编排、关键词监听和 AI 验证处理的控制台产品。

## 产品简介

TG-SignPulse 用来集中管理多个 Telegram 账号，并把“发送消息、点击按钮、识图答题、监听关键词、推送通知”这些动作组合成可重复执行的自动化流程。它同时提供 Web 面板、后端 API、调度器和执行引擎，适合长期稳定挂机。

## 适用场景

- 自动签到、每日打卡、积分领取
- 机器人交互流程编排
- 群组或频道关键词监听
- AI 识图、OCR、计算题、按钮验证
- 多账号共享同一套任务模板
- Docker / GHCR / VPS 持续部署

## 核心能力

- 多账号管理：支持短信登录、二维码登录、2FA 密码、状态检测、重新登录
- 任务编排：支持固定时间、时间段随机执行、监听触发三种执行模式
- AI 动作：支持识图选项、OCR 文本提取、计算题作答、AI 推断后点按钮
- 关键词监听：支持包含、完全匹配、正则；支持继续执行后续动作
- 推送通知：支持 Telegram Bot、转发、Bark、自定义 URL
- 多账号共享任务：一套任务可绑定多个账号执行
- 运维友好：提供健康检查、日志、导入导出、持久化数据目录

## 运行结构

```text
Browser
  -> Next.js Frontend
  -> FastAPI API
       -> SignTaskService / KeywordMonitorService
       -> APScheduler
       -> SQLite + /data
       -> tg_signer execution engine
       -> Telegram
       -> OpenAI-compatible API
```

## 文档导航

| 文档 | 说明 |
| --- | --- |
| [快速开始](guide/quick-start.md) | 5 分钟部署、登录、添加账号、创建第一个任务 |
| [Docker 部署](deploy/docker.md) | Docker、Compose、GHCR 镜像、升级与持久化 |
| [账号管理](guide/accounts.md) | 短信登录、二维码登录、2FA、代理、会话模式 |
| [任务编排](guide/tasks.md) | 任务模型、动作类型、执行模式、多账号共享 |
| [AI 动作](guide/ai.md) | OpenAI 配置、默认模型、默认提示词、自定义提示词 |
| [关键词监听](guide/keyword-monitor.md) | 监听模式、推送通道、后续动作、模板变量 |
| [配置参考](reference/configuration.md) | 环境变量、数据目录、配置文件、默认行为 |
| [运维手册](reference/ops.md) | 健康检查、日志、备份恢复、升级建议 |
| [系统架构](reference/architecture.md) | 前后端、调度器、执行引擎、数据流 |
| [常见问题](faq.md) | 登录、AI、镜像、数据持久化、监听常见问题 |

## 关键默认行为

- 未设置 `ADMIN_PASSWORD` 时，系统会为 `admin` 生成随机初始密码，并写入数据目录下的 `.admin_bootstrap_password`
- 数据目录优先使用 `/data`；若 `/data` 不可写，会自动降级到 `/tmp/tg-signpulse`
- 默认 AI 模型是 `gpt-4o`
- 面板 2FA 的 `APP_TOTP_VALID_WINDOW` 未设置时，实际默认值为 `1`
- 容器默认监听 `8080`，开发态前端默认访问 `http://127.0.0.1:3000`

## 镜像版本说明

- GitHub 分支推送会自动构建测试镜像：`ghcr.io/<owner>/tg-signpulse:test-<branch>`
- 同一次推送还会生成一个短 SHA 测试镜像：`ghcr.io/<owner>/tg-signpulse:test-<sha>`
- Git 标签 `v*` 会构建正式版本镜像：`ghcr.io/<owner>/tg-signpulse:vX.Y.Z`
- Git 标签 `v*` 同时更新 `ghcr.io/<owner>/tg-signpulse:latest`

## 推荐阅读顺序

1. [快速开始](guide/quick-start.md)
2. [账号管理](guide/accounts.md)
3. [任务编排](guide/tasks.md)
4. [AI 动作](guide/ai.md)
5. [关键词监听](guide/keyword-monitor.md)


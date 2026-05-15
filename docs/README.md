# TG-SignPulse 文档

> v2.0.0 · Telegram 多账号自动化、任务编排、关键词监听和 AI 验证处理控制台。

## 产品简介

TG-SignPulse 用来集中管理多个 Telegram 账号，并把「发送消息、点击按钮、识图答题、监听关键词、推送通知」这些动作组合成可重复执行的自动化流程。它同时提供 Web 面板、后端 API、调度器和执行引擎，适合长期稳定挂机。

## 适用场景

- 自动签到、每日打卡、积分领取
- 机器人交互流程编排
- 群组或频道关键词监听与自动响应
- AI 识图、OCR、计算题、按钮验证
- 多账号共享同一套任务模板
- Docker / VPS 持续部署

## 技术架构

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3、Vue Router、Pinia、Tailwind CSS 4、Vite、PWA |
| 后端 | FastAPI、Uvicorn、SQLAlchemy、SQLite (WAL)、APScheduler |
| 认证 | JWT (HS256)、TOTP 2FA、bcrypt、Rate Limiting |
| Telegram | Pyrogram / Kurigram、Session File / String 双模式 |
| AI | OpenAI SDK（兼容接口）、识图 / OCR / 计算题 |
| 部署 | Docker Multi-stage、GitHub Actions、GHCR |

## 核心能力

- **多账号管理**：支持短信登录、二维码登录、2FA 密码、状态检测、重新登录
- **任务编排**：支持固定时间、时间段随机执行、监听触发三种执行模式
- **AI 动作**：支持识图选项、OCR 文本提取、计算题作答、AI 推断后点按钮
- **关键词监听**：支持包含、完全匹配、正则；支持继续执行后续动作
- **推送通知**：支持 Telegram Bot、转发、Bark、自定义 URL
- **多账号共享任务**：一套任务可绑定多个账号执行
- **运维友好**：提供健康检查、日志可视化、导入导出、持久化数据目录

## 文档导航

### 快速开始

| 文档 | 说明 |
|------|------|
| [快速开始](guide/quick-start.md) | 5 分钟部署、登录、添加账号、创建第一个任务 |

### 部署方式

| 文档 | 说明 |
|------|------|
| [Docker 部署](deploy/docker.md) | Docker、Compose、GHCR 镜像、升级与持久化 |

### 使用指南

| 文档 | 说明 |
|------|------|
| [账号管理](guide/accounts.md) | 短信登录、二维码登录、2FA、代理、会话模式 |
| [任务编排](guide/tasks.md) | 任务模型、动作类型、执行模式、多账号共享 |
| [AI 动作](guide/ai.md) | OpenAI 配置、默认模型、自定义提示词 |
| [关键词监听](guide/keyword-monitor.md) | 监听模式、推送通道、后续动作、模板变量 |

### 配置指南

| 文档 | 说明 |
|------|------|
| [配置参考](reference/configuration.md) | 环境变量、数据目录、配置文件、默认行为 |
| [运维手册](reference/ops.md) | 健康检查、日志、备份恢复、升级建议 |
| [系统架构](reference/architecture.md) | 前后端、调度器、执行引擎、数据流 |

### 其他

| 文档 | 说明 |
|------|------|
| [常见问题](faq.md) | 登录、AI、镜像、数据持久化、监听常见问题 |

## 目录结构

```text
TG-SignPulse/
├── backend/            # FastAPI 后端
│   ├── api/            #   API 路由层
│   ├── core/           #   配置、认证、数据库
│   ├── models/         #   SQLAlchemy 数据模型
│   ├── services/       #   业务逻辑层（签到、监听、Telegram）
│   ├── scheduler/      #   APScheduler 调度器
│   └── utils/          #   工具函数
├── tg_signer/          # Telegram 自动化引擎
│   ├── core.py         #   签到执行核心（UserSigner）
│   ├── config.py       #   任务配置模型 (V1→V2→V3)
│   ├── ai_tools.py     #   AI 工具集成
│   └── async_utils.py  #   异步工具
├── frontend/           # Vue 3 前端
│   ├── src/
│   │   ├── views/      #     页面组件
│   │   ├── components/ #     通用组件
│   │   ├── stores/     #     Pinia 状态管理
│   │   └── api/        #     API 调用层
│   └── vite.config.ts
├── docker/             # Docker 入口脚本
├── docs/               # 项目文档 (VitePress)
├── Dockerfile          # 多阶段构建
├── docker-compose.yml  # Compose 编排
└── pyproject.toml      # Python 项目配置
```

## 数据目录结构

```text
/data
├── db.sqlite                    # 主数据库
├── .app_secret_key              # JWT 密钥
├── .admin_bootstrap_password    # 初始管理员密码
├── .global_settings.json        # 全局设置
├── .openai_config.json          # AI 配置
├── .telegram_api.json           # Telegram API 配置
├── logs/                        # 任务执行日志
├── sessions/                    # Telegram 会话文件
│   ├── accounts.json            # 账号元数据
│   └── *.session                # Session 文件
└── .signer/                     # 签到引擎工作目录
    ├── signs/                   # 任务配置
    │   └── <account>/
    │       └── <task>/config.json
    ├── history/                 # 执行历史
    └── avatars/                 # 头像缓存
```

## 运行架构

```text
Browser (Vue 3 SPA)
  └── FastAPI API (/api)
        ├── AuthService (JWT + TOTP)
        ├── TelegramService (账号管理)
        ├── SignTaskService (任务 CRUD + 执行)
        ├── KeywordMonitorService (后台监听)
        ├── APScheduler (定时触发)
        ├── SQLite (WAL mode)
        └── tg_signer Engine
              ├── Pyrogram/Kurigram Client
              ├── OpenAI API (AI 动作)
              └── Telegram API
```

## 镜像版本说明

| 触发条件 | 镜像标签 | 用途 |
|----------|----------|------|
| 分支推送 | `test-<branch>` / `test-<sha>` | 测试环境 |
| Git 标签 `v*` | `v2.0.0` + `latest` | 生产环境 |

## 推荐阅读顺序

1. [快速开始](guide/quick-start.md)
2. [Docker 部署](deploy/docker.md)
3. [账号管理](guide/accounts.md)
4. [任务编排](guide/tasks.md)
5. [配置参考](reference/configuration.md)
6. [AI 动作](guide/ai.md)
7. [关键词监听](guide/keyword-monitor.md)

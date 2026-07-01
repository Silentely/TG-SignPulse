<p align="center">
  <img src="docs/public/logo.svg" width="80" height="80" alt="TG-SignPulse Logo">
</p>

<h1 align="center">TG-SignPulse</h1>


<p align="center">
  <strong>Telegram 多账号自动化管理面板</strong><br>
  签到 · 消息编排 · 关键词监听 · AI 验证
</p>

<p align="center">
  <a href="https://github.com/Silentely/TG-SignPulse/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-BSD--3--Clause-green" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.10--3.13-blue" alt="Python">
  <img src="https://img.shields.io/badge/node-22+-green" alt="Node.js">
  <a href="https://github.com/Silentely/TG-SignPulse/pkgs/container/tg-signpulse"><img src="https://img.shields.io/badge/ghcr.io-available-purple" alt="GHCR"></a>
</p>

<p align="center">
  <a href="README_EN.md">English</a> · <a href="docs/README.md">完整文档</a> · <a href="docs/guide/quick-start.md">快速开始</a>
</p>

---

## 项目简介

TG-SignPulse 是一个 Telegram 自动化管理面板。你可以在网页中管理多个 Telegram 账号，配置自动签到任务，并让任务按固定规则或随机时间段每天自动执行。

> 🤖 AI 驱动：已集成 OpenAI 兼容接口，支持识图、计算题、OCR 等自动验证流程。

---

## 功能概览

| 模块 | 能力 |
|------|------|
| **账号管理** | 多账号登录（短信/二维码）、代理配置、状态检测、重新登录 |
| **任务编排** | 定时/随机时间段/监听触发，支持有序动作序列和动作间隔 |
| **动作类型** | 发送文本、点击按钮、发送骰子、AI 识图、AI 计算、关键词监听 |
| **任务重试** | 每个任务可独立配置重试次数（0–99），失败后自动从断点继续 |
| **话题支持** | 群组 Thread ID 级别的发送与回复过滤 |
| **关键词监听** | 包含/完全匹配/正则，命中后支持 Telegram Bot、转发、Bark、自定义 URL、后续动作 |
| **时区管理** | Web 面板可切换时区（支持 22 个常用时区），调度器自动适配 |
| **通知推送** | 任务失败通知、账号失效通知、登录通知、关键词命中通知 |
| **运维能力** | Docker 部署、持久化数据、健康检查、配置导入导出、日志可视化 |

---

## 技术栈

```
┌─────────────────────────────────────────────────────────┐
│  Frontend          Vue 3 + Vue Router + Pinia           │
│                    Tailwind CSS 4 + Lucide Icons         │
│                    Vite + PWA                            │
├─────────────────────────────────────────────────────────┤
│  Backend           FastAPI + Uvicorn                     │
│                    SQLAlchemy + SQLite (WAL)             │
│                    APScheduler (AsyncIO)                 │
│                    JWT + TOTP 2FA + bcrypt               │
├─────────────────────────────────────────────────────────┤
│  Telegram Engine   Pyrogram / Kurigram                   │
│                    Session File / String 双模式          │
├─────────────────────────────────────────────────────────┤
│  AI Integration    OpenAI SDK (兼容接口)                 │
│                    识图 / OCR / 计算题 / 推断点击         │
├─────────────────────────────────────────────────────────┤
│  Infrastructure    Docker Multi-stage Build              │
│                    GitHub Actions CI/CD                   │
│                    GHCR Container Registry               │
└─────────────────────────────────────────────────────────┘
```

---

## 快速开始

### 前置条件

- Docker 24+ 与 Docker Compose
- 至少一个 Telegram 账号

### 一条命令启动

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

### Docker Compose

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
      - APP_SECRET_KEY=your_secret_key
      - ADMIN_PASSWORD=your_strong_password
```

```bash
docker compose up -d
```

### 登录面板

浏览器打开 `http://服务器IP:8080`

- 用户名：`admin`
- 密码：你设置的 `ADMIN_PASSWORD`（未设置则查看 `data/.admin_bootstrap_password`）

---

## 项目结构

```text
TG-SignPulse/
├── backend/            # FastAPI 后端
│   ├── api/            #   API 路由层
│   ├── core/           #   配置、认证、数据库
│   ├── models/         #   SQLAlchemy 数据模型
│   ├── services/       #   业务逻辑层
│   ├── scheduler/      #   APScheduler 调度器
│   └── utils/          #   工具函数
├── tg_signer/          # Telegram 自动化引擎
│   ├── core.py         #   签到执行核心
│   ├── config.py       #   任务配置模型 (V1→V2→V3)
│   └── ai_tools.py     #   AI 工具集成
├── frontend/           # Vue 3 前端
│   ├── src/
│   └── vite.config.ts
├── docker/             # Docker 入口脚本
├── docs/               # 项目文档 (VitePress)
├── Dockerfile          # 多阶段构建
├── docker-compose.yml  # Compose 编排
└── pyproject.toml      # Python 项目配置
```

---

## 文档

完整文档请查看 [docs/README.md](docs/README.md)，包含：

- [快速开始](docs/guide/quick-start.md) — 5 分钟部署并创建第一个任务
- [Docker 部署](docs/deploy/docker.md) — 镜像策略、Compose、反向代理、升级
- [配置参考](docs/reference/configuration.md) — 环境变量、数据目录、配置文件
- [账号管理](docs/guide/accounts.md) — 登录方式、代理、会话模式
- [任务编排](docs/guide/tasks.md) — 动作类型、执行模式、多账号共享
- [AI 动作](docs/guide/ai.md) — OpenAI 配置与自定义提示词
- [关键词监听](docs/guide/keyword-monitor.md) — 匹配规则、推送通道、后续动作
- [系统架构](docs/reference/architecture.md) — 前后端、调度器、执行引擎

---

## 常用环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `APP_SECRET_KEY` | JWT 密钥（生产必设） | 自动生成 |
| `ADMIN_PASSWORD` | 管理员初始密码 | 随机生成 |
| `APP_DATA_DIR` | 数据目录 | `/data` |
| `TZ` | 时区 | `Asia/Shanghai` |
| `TG_SESSION_MODE` | 会话模式 `file`/`string` | `file` |
| `TG_GLOBAL_CONCURRENCY` | 全局并发数 | `自动（CPU核心数，上限5）` |
| `TG_PROXY` | Telegram 全局代理 | 无 |

更多配置请查看 [配置参考](docs/reference/configuration.md)。

---

## 本地开发

```bash
# 后端
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn backend.main:app --reload --port 8080

# 前端
cd frontend
npm ci
npm run dev
```

- Python 3.10–3.13（推荐 3.12）
- Node.js 22.12.0+
- 不建议使用 Python 3.14+（Telegram 运行时依赖尚未兼容）

---

## 健康检查

```bash
curl http://127.0.0.1:8080/healthz   # 快速健康检查
curl http://127.0.0.1:8080/readyz    # 服务就绪检查
```

---
## 致谢

本项目基于 [tg-signer](https://github.com/amchii/tg-signer) by [amchii](https://github.com/amchii) 进行重构与扩展。

---

## License

[BSD-3-Clause](LICENSE)

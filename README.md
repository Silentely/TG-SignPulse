<p align="center">
  <img src="docs/public/logo.svg" width="80" height="80" alt="TG-SignPulse Logo">
</p>

<h1 align="center">TG-SignPulse</h1>

<p align="center">
  <strong>Telegram 多账号自动化管理面板</strong><br>
  签到 · 消息编排 · 关键词监听 · AI 验证
</p>

<p align="center">
  <a href="https://github.com/AkaSLs/tg-signpulse/releases"><img src="https://img.shields.io/badge/version-v2.0.0-blue" alt="Version"></a>
  <a href="https://github.com/AkaSLs/tg-signpulse/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-BSD--3--Clause-green" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.10--3.13-blue" alt="Python">
  <img src="https://img.shields.io/badge/node-20+-green" alt="Node.js">
  <a href="https://github.com/AkaSLs/tg-signpulse/pkgs/container/tg-signpulse"><img src="https://img.shields.io/badge/ghcr.io-available-purple" alt="GHCR"></a>
</p>

<p align="center">
  <a href="README_EN.md">English</a> · <a href="docs/README.md">完整文档</a> · <a href="docs/guide/quick-start.md">快速开始</a> · <a href="#更新日志">更新日志</a>
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
| **话题支持** | 群组 Thread ID 级别的发送与回复过滤 |
| **关键词监听** | 包含/完全匹配/正则，命中后支持 Telegram Bot、转发、Bark、自定义 URL、后续动作 |
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
  ghcr.io/akasls/tg-signpulse:latest
```

### Docker Compose

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
| `TG_GLOBAL_CONCURRENCY` | 全局并发数 | `1` |
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
- Node.js 20+
- 不建议使用 Python 3.14+（Telegram 运行时依赖尚未兼容）

---

## 健康检查

```bash
curl http://127.0.0.1:8080/healthz   # 快速健康检查
curl http://127.0.0.1:8080/readyz    # 服务就绪检查
```

---

## 更新日志

### v2.0.0 (2026-05-15)

**版本化管理**：从本版本开始采用语义化版本号。

**代码质量**
- 全面清理 DEBUG print 语句，替换为结构化 logging
- 修复 `accounts.py` 中的乱码错误消息
- 修复 SPA fallback 在生产环境错误重定向到开发服务器的问题
- Docker Compose 移除过时的 `version` 字段，补充 tmpfs 挂载
- 前端 `vite-plugin-pwa` 移至 devDependencies

**文档**
- 重写 README，增加技术栈说明和项目结构
- 更新 docs 文档体系，完善部署指南和配置参考
- 修正默认密码文档与实际行为不一致的问题

---

<details>
<summary><strong>历史更新日志</strong></summary>

### 2026-05-03

- 关键词监听常驻修复：关键词监听动作现在会被识别为需要 Telegram updates 的任务
- 关键词命中后续动作修复：点击按钮动作会等待并轮询最近消息中的可点击按钮
- 签到按钮流程重试增强：按钮点击失败时从第 1 步重新执行，默认最多重试 3 次

### 2026-04-29

- 关键词监听后续动作：命中关键词后可直接继续执行动作序列
- Telegram 机器人通知重构：独立配置组件，新增总开关和分类开关
- 任务级失败通知控制：可单独关闭某个任务的失败通知

### 2026-04-28

- 任务前账号状态探测：执行前检测 session 是否可用
- 账号失效通知与持久标记
- 首页重登入口优化

### 2026-04-27

- 关键词监听改为有序动作序列中的动作
- 动作序列布局优化
- 命中消息转发支持

### 2026-04-26

- Telegram 话题 (Thread/Topic) 支持
- 全局代理回退机制
- 剪贴板批量导入导出
- Telegram Bot 失败通知

### 2026-03-20

- SQLite 死锁修复
- 防止任务重复执行 UI 防护

### 2026-03-19

- 主页状态显示修复
- 老账号签到异常修复
- 机器人最近回复可视

### 2026-03-12

- 修复 Pyrogram 超时及 FloodWait 导致的内存泄漏

### 2026-03-06

- 任务动作序列优化
- AI 动作子模式切换
- 任务复制粘贴优化
- 容器权限兼容增强

### 2026-03-01

- AI 动作升级
- 长时运行稳定性优化
- 自定义数据目录支持

</details>

---

## 致谢

本项目基于 [tg-signer](https://github.com/amchii/tg-signer) by [amchii](https://github.com/amchii) 进行重构与扩展。

---

## License

[BSD-3-Clause](LICENSE)

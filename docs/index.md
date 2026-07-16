---
layout: home
title: TG-SignPulse 文档
description: Telegram 多账号自动化管理面板 — 签到、消息编排、关键词监听与 AI 验证

hero:
  name: TG-SignPulse
  text: Telegram 多账号自动化管理面板
  tagline: 签到 · 消息编排 · 关键词监听 · AI 验证 · Docker 一键部署
  image:
    src: /logo.svg
    alt: TG-SignPulse
  actions:
    - theme: brand
      text: 快速开始
      link: /guide/quick-start
    - theme: alt
      text: 功能介绍
      link: /features
    - theme: alt
      text: Docker 部署
      link: /deploy/docker
    - theme: alt
      text: GitHub
      link: https://github.com/Silentely/TG-SignPulse

features:
  - icon: 👥
    title: 多账号共享任务
    details: 一套流程绑定多号，统一维护步骤，适合批量签到与多号机器人交互。
  - icon: 🤖
    title: AI 验证处理
    details: 识图选项、OCR、计算题、推断后点按钮；支持逐动作自定义提示词。
  - icon: 📡
    title: 关键词监听
    details: 包含 / 全匹配 / 正则；命中后通知、转发或继续执行动作序列。
  - icon: 📅
    title: 调度与实时流
    details: Cron / 时段调度、Dashboard SSE、任务 WebSocket 日志与失败分类。
  - icon: 🐳
    title: 容器友好部署
    details: Docker 开箱即用，健康检查、数据持久化、Nginx SSE 样例齐全。
  - icon: 🗄️
    title: 存储灵活
    details: 默认 SQLite（WAL）；可选 APP_DATABASE_URL 切换 PostgreSQL，非强制迁移。
---

## 一键预览文档

::: tip 仓库根目录
文档站脚本在仓库根 `package.json`（不在 `docs/` 子目录）。
:::

```bash
npm install
npm run docs:dev
# 访问 http://127.0.0.1:5173
```

构建静态站点：

```bash
npm run docs:build
npm run docs:preview
```

托管到 Vercel 见 [Vercel 文档站](/deploy/vercel)。

## 面板一键部署（摘要）

```bash
# 详见 deploy/docker
docker compose -f docker-compose.panel.yml up -d
# 浏览器打开映射端口，默认数据目录持久化
```

生产环境建议：

- 持久化挂载 `APP_DATA_DIR`（含 `db.sqlite` / sessions）
- 反向代理关闭 SSE 缓冲（见 [Nginx](/deploy/nginx)）
- 旧 `/api/tasks` 默认只读，新功能用 `/api/sign-tasks`

## 数据库说明

| 模式 | 如何启用 | 说明 |
|------|----------|------|
| **SQLite（默认）** | 不设 `APP_DATABASE_URL` | 单机最省心，WAL 模式，适合大多数部署 |
| **PostgreSQL（可选）** | 设置 `APP_DATABASE_URL=postgresql+psycopg2://...` | 需安装 `psycopg2-binary` 并迁移 schema；**项目未取消 SQLite** |

> Telegram session 文件仍不宜多进程共享同一账号，与库类型无关。

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3、TypeScript、Vite、Pinia、Tailwind、vue-i18n |
| 后端 | FastAPI、SQLAlchemy、APScheduler |
| 数据 | **默认 SQLite**，可选 PostgreSQL |
| 认证 | JWT、TOTP 2FA、bcrypt |
| Telegram | Pyrogram / Kurigram |
| AI | OpenAI 兼容接口 |
| 部署 | Docker、GHCR、GitHub Actions |
| 文档 | VitePress |

## 文档入口

| 入口 | 说明 |
|------|------|
| [功能介绍](/features) | 能力一览与适用场景 |
| [快速开始](/guide/quick-start) | 本地 / 容器起步 |
| [任务编排](/guide/tasks) | sign-tasks 与动作类型 |
| [配置参考](/reference/configuration) | 环境变量与配置文件 |
| [运维手册](/reference/ops) | 健康检查、备份、上线清单 |
| [常见问题](/faq) | 排障与旧 API 说明 |

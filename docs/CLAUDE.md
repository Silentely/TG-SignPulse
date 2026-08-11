[根目录](../CLAUDE.md) > **docs**

# Docs 模块

> VitePress 用户/部署/架构文档站（与面板、引擎分离的对外文档）。

## 变更记录 (Changelog)

> 模块级变更并入根 [`CHANGELOG.md`](../CHANGELOG.md)。本文件由 `/ccg:init` 补扫生成。

## 模块职责

- 产品介绍与功能说明
- 用户指南（账号、任务、关键词监听、AI、备份）
- 部署指南（Docker、Nginx、DNS）
- 架构与运维参考（与代码 CLAUDE 交叉对齐，不复制实现细节）
- FAQ

## 入口与启动

| 项 | 说明 |
|----|------|
| 内容根 | `docs/` |
| 本地预览 | 仓库根 `npm run docs:dev`（端口 **5173**） |
| 构建 | `npm run docs:build`（以根 `package.json` 为准） |
| 配置 | VitePress 配置在 `docs/.vitepress/`（主题/侧栏） |

## 目录结构

```
docs/
├── index.md           # 首页
├── README.md          # 文档总览与架构表
├── features.md        # 功能清单
├── faq.md             # 常见问题
├── guide/             # 用户指南
│   ├── quick-start.md
│   ├── accounts.md
│   ├── tasks.md
│   ├── keyword-monitor.md
│   ├── ai.md
│   └── backup-webdav.md
├── deploy/            # 部署
│   ├── docker.md
│   ├── nginx.md
│   └── dns-aid.md
├── reference/         # 参考
│   ├── architecture.md
│   ├── configuration.md
│   ├── development.md
│   ├── device-management.md
│   └── ops.md
└── public/            # 静态资源
```

## 与代码文档的边界

| 文档 | 面向 | 内容重心 |
|------|------|----------|
| 根 / `backend` / `frontend` / `tg_signer` 的 `CLAUDE.md` | AI 与开发者 | 入口、调用链、文件级地图 |
| `docs/reference/*` | 人类读者 | 架构分层、配置项、运维场景 |
| `docs/guide/*` | 终端用户 | 如何配置任务/监听/AI |

**交叉对齐要点**（`reference/architecture.md` 已与代码一致）：

- 主路径：`/api/sign-tasks`；旧 `/api/tasks` **已移除**
- 调度：APScheduler + `data/.scheduler.lock`；listen 模式交给 `KeywordMonitorService`
- 存储：`db.sqlite` + `sessions/` + `.signer/`（任务 JSON）
- 扩展：单写主实例；可选 `APP_DATABASE_URL`；监听分片 `APP_MONITOR_SHARD`

修改路由或任务体系时：先改代码与模块 CLAUDE，再检查 `docs/reference/architecture.md`、`docs/guide/tasks.md`、`faq.md` 是否过时。

## 测试与质量

- 文档 agent 资源：`scripts/prepare-docs-agent-assets.mjs` / `verify-docs-agent-assets.mjs`
- 无独立 pytest；链接与版本号（如 README 中 v2.3.0）需与 `tg_signer.__version__` 人工对齐

## 相关文件清单

- `docs/README.md`、`docs/index.md`
- `docs/guide/*`、`docs/deploy/*`、`docs/reference/*`
- 根 `package.json` 的 `docs:*` 脚本
- `docker-compose.panel.yml` / `Dockerfile`（部署章节的真实来源）

---
name: quick-start
description: 引导用户在 5 分钟内完成 TG-SignPulse 部署、登录、添加账号与创建第一个签到任务。
---

# TG-SignPulse 快速开始 Skill

## 步骤

1. 阅读 https://tg.cosr.eu.org/guide/quick-start
2. 生产部署参考 https://tg.cosr.eu.org/deploy/docker
3. 配置环境变量见 https://tg.cosr.eu.org/reference/configuration
4. 账号登录见 https://tg.cosr.eu.org/guide/accounts
5. 创建任务见 https://tg.cosr.eu.org/guide/tasks

## 最小验收

- 面板可访问且 `/healthz` 返回正常
- 管理员可登录
- 至少一个 Telegram 账号在线
- 至少一个签到任务可手动触发

## 注意

- 默认 SQLite；可选 `APP_DATABASE_URL` 使用 PostgreSQL
- 旧 `/api/tasks` 写接口默认只读（410），请用 `/api/sign-tasks`
- Agent 调用自托管 API 前先读 https://tg.cosr.eu.org/auth.md

# 功能介绍

TG-SignPulse 是 Telegram 多账号自动化管理面板，把签到、消息交互、关键词监听和 AI 辅助验证收敛到同一套 Web 控制台。

## 核心能力

### 账号管理

- 验证码登录 / 扫码登录
- 代理与会话模式（file / string）
- 设备管理、设备保活、官方消息查看
- 批量状态检查

详见 [账号管理](/guide/accounts)。

### 任务编排（sign-tasks）

- 固定 Cron 或时间段执行
- 多账号共享同一套动作流程
- 发送文本、骰子、点按钮、AI 识图/计算、关键词监听等动作
- 批量启用/停用/触发
- 失败分类与历史日志

> 面板与 API 请使用 **`/api/sign-tasks`**。旧版 ORM `/api/tasks` 默认只读。

详见 [任务编排](/guide/tasks)。

### AI 验证

- 图片 OCR / 选按钮
- 计算题回复
- 计算后点击
- OpenAI 兼容接口（含本地 LLM）

详见 [AI 动作](/guide/ai)。

### 关键词监听

- exact / contains / regex
- 命中后推送、转发、继续动作
- 多实例可配置监听分片

详见 [关键词监听](/guide/keyword-monitor)。

### 通知与设置

- 签到间隔、任务超时/冷却/流程重试、AI 视觉参数可在面板「系统设置」覆盖
- Bot 测试发送、任务成功通知（全局 + 任务级开关）、静默时段
- 监听推送支持 Server酱（任务表单通道）

### 运维与可观测

- `/healthz`、`/readyz`（含调度锁、旧 API 只读状态）
- 版本信息与更新检查（Settings / 侧栏；`/api/ops/version`）
- Dashboard SSE 实时日志
- 任务 WebSocket 日志
- 配置/数据备份导出；可选定时自动备份（`backups/auto-*.tar.gz`）
- 配置导入预览（dry-run）
- 任务克隆与内置模板（文本/按钮/时段/骰子/关键词监听；预填动作后须选会话）
- 系统设置未保存提示与「保存全部」
- 旧任务存量盘点：`GET /api/tasks/legacy-status`、`tools/check_legacy_tasks.py`

详见 [运维手册](/reference/ops)。

## 适合场景

- 多账号机器人签到、日常打卡
- 验证码、诗句填空、数学题、按钮验证
- 群组/频道长期监听与通知
- VPS / Docker 长期托管

## 不适合 / 注意

- 多副本**共享同一 Telegram session 文件**（易损坏会话）
- 把面板直接裸奔在公网且无 HTTPS / 访问控制
- 依赖已弃用的旧 `/api/tasks` 写接口（默认 410）

## 下一步

- [快速开始](/guide/quick-start)
- [Docker 部署](/deploy/docker)
- [配置参考](/reference/configuration)

# 系统架构

## 总览

TG-SignPulse 由四个核心层组成：

1. Next.js 前端面板
2. FastAPI 后端 API
3. 调度与任务服务
4. `tg_signer` Telegram 执行引擎

## 前端

前端负责：

- 登录与鉴权
- 账号管理
- 任务创建与编辑
- AI 配置
- 全局设置
- 运行日志展示

开发模式默认运行在：

```text
http://127.0.0.1:3000
```

## 后端 API

主要路由包括：

- `/api/auth`
- `/api/user`
- `/api/accounts`
- `/api/tasks`
- `/api/sign-tasks`
- `/api/config`
- `/api/events`

后端负责：

- JWT 鉴权
- 数据库存储
- 账号登录流程
- 任务增删改查
- 调度同步
- 关键词监听生命周期管理

## 调度层

调度层基于 APScheduler。

主要职责：

- 读取已启用任务
- 为 `fixed` 与 `range` 任务生成调度
- 在任务变更后同步调度项
- `listen` 模式则交给关键词监听服务，而不是普通 Cron

## 任务服务

`SignTaskService` 负责：

- 任务创建、更新、删除
- 共享任务的账号聚合
- 手动执行任务
- 历史记录和流程日志
- 失败通知

## 关键词监听服务

`KeywordMonitorService` 负责：

- 从任务配置中提取监听规则
- 挂载 Telegram message handler
- 匹配关键词、正则和话题
- 触发通知、转发或继续动作
- 在任务变化后重建监听器

## 执行引擎

`tg_signer` 负责真正和 Telegram 交互：

- 发送文本
- 发送骰子
- 点击按钮
- 等待消息变化
- 调用 AI 识图 / OCR / 计算
- 处理 FloodWait、重试和部分异常恢复

## 数据流

### 定时任务

```text
Scheduler
  -> SignTaskService
  -> tg_signer core
  -> Telegram
  -> Log / History / Notification
```

### 监听任务

```text
Telegram Update
  -> KeywordMonitorService
  -> Keyword Match
  -> Push / Forward / Continue Actions
  -> Log / History
```

## 存储层

主要存储分为三部分：

- `db.sqlite`：面板数据库
- `sessions/`：Telegram 会话
- `.signer/`：任务配置与运行相关数据

AI、全局设置和 Telegram API 配置则单独保存在数据目录根部的 JSON 文件中。

## 设计特点

- 前后端可一体容器化部署
- 任务与账号关系支持从单账号扩展到多账号共享
- 监听任务与定时任务共用动作模型
- AI 提示词支持逐动作覆盖
- 数据目录与运行目录分离，便于迁移与备份


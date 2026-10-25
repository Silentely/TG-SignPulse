# 功能介绍

TG-SignPulse 是 Telegram 多账号自动化管理面板，把签到、消息交互、关键词监听和 AI 辅助验证收敛到同一套 Web 控制台。

<p align="center">
  <img src="/screenshots/dashboard.png" alt="TG-SignPulse 仪表盘概览" style="border-radius: 8px; box-shadow: 0 6px 24px rgba(0,0,0,0.25); border: 1px solid var(--vp-c-divider);">
</p>

## 核心能力

### 账号管理

集中管理多个 Telegram 账号，提供会话生命周期维护、网络代理绑定与设备指纹防护。

<p align="center">
  <img src="/screenshots/accounts.png" alt="多账号管理与状态监控" style="border-radius: 8px; border: 1px solid var(--vp-c-divider);">
</p>

- **验证码登录 / 扫码登录 / 会话导入**：支持 Telethon·Pyrogram `.session`、Pyrogram StringSession 以及 TData `.zip` 导入，免输入手机号，避免反复收码。
- **代理与会话模式**：每个账号可独立配置 SOCKS5 / HTTP 代理，支持强制 Telegram 走代理并自动校验出口 IP 是否泄露宿主 IP。
- **设备指纹画像**：预设桌面端（macOS/Windows）与移动端（Android/iOS）系统与客户端指纹，降低 Telegram 风控风险。
- **设备管理与官方消息**：实时查看已登录设备、一键清退其他设备、一键派生独立 SessionString 导出，并可在线接收官方系统验证码。
- **批量检测与日志导出**：批量检测多账号在线状态与网络连通延迟，支持单个账号历史运行日志一键打包导出。

<p align="center">
  <img src="/screenshots/account-modal.png" alt="扫码登录与会话导入弹窗" style="border-radius: 8px; border: 1px solid var(--vp-c-divider); max-width: 600px;">
</p>

详见 [账号管理](/guide/accounts)。

---

### 任务编排（sign-tasks）

可视化编排自动化打卡与交互步骤，支持单号专用或多号共享同一个任务流程。

<p align="center">
  <img src="/screenshots/tasks.png" alt="任务编排管理列表" style="border-radius: 8px; border: 1px solid var(--vp-c-divider);">
</p>

- **灵活的调度模式**：
  - **固定时间**（Cron 规则，精确到分钟）
  - **时间段随机**（如每日 `08:00–09:30` 间随机执行）
  - **实时监听**（挂起长连监听指定频道/群组）
- **防风控执行策略**：Jitter 错峰延时（`0–3600s`）、账号并发锁互斥、Telegram FloodWait 智能冷却退避保护。
- **自适应动态冷却调度**：自动解析机器人回复中的冷却倒计时（如“请在 4 小时后重试”），动态调整下次运行时间。
- **动作类型丰富**：发送文本、点击内联按钮、发送骰子（🎲/🎯/🎳）、AI 识图/计算、关键词监听等。
- **任务目标精确定位**：支持按 Telegram 对话文件夹筛选、论坛话题（Forum Topics Thread ID）过滤与回复。
- **11 类细粒度失败分类体系**：自动归纳会话失效、频率限制、AI 超时、按钮未找到、内容未变化等异常类型并给出排障指引。

<p align="center">
  <img src="/screenshots/task-editor.png" alt="任务动作流编排与参数配置" style="border-radius: 8px; border: 1px solid var(--vp-c-divider); max-width: 720px;">
</p>

> 面板与 API 请使用 **`/api/sign-tasks`**。旧版 ORM `/api/tasks` 已移除。

详见 [任务编排](/guide/tasks)。

---

### AI 智能验证

开箱集成 OpenAI 兼容标准接口（支持 DeepSeek、GPT-4o、Claude 及本地部署大模型），自动攻克各类签到验证环节。

- **图片 OCR 与文字识别**：识别图片中的验证码并回填发送。
- **数学题与推理问答**：解析图像或文本中的计算题（如 `17 + 8 = ?`），得出答案并自动回复。
- **推断后点击按钮**：结合识别结果，在机器人的内联键盘中精确定位并点击对应答案按钮。
- **动作级自定义 Prompt**：每个 AI 动作均可独立定制提示词与最大重试次数。

详见 [AI 动作](/guide/ai)。

---

### JEV 语义决策与智能自愈

专为 Telegram 交互场景打造的原生语义决策引擎（采用 SystemOne 决策协议），攻克按钮频繁更名与规则失效难题。

- **高鲁棒性按钮语义匹配**：抛弃脆弱的死记硬背式文本与正则，根据会话意图智能推断目标按钮。
- **三态熔断器保护**：内置 `closed`、`half_open`、`open` 熔断机制，网络抖动或异常时零中断自动降级为规则匹配模式。
- **全景可观测性**：首页大盘实时呈现 JEV 健康状态徽章、缓存命中率，熔断触发时即时弹出告警横幅。
- **智能规则反哺建议（Rule Suggestions）**：后台自动收集边缘观测（Observations），生成可一键采纳生效的规则优化建议，实现打卡规则自愈。

详见 [JEV 语义决策](/guide/jev)。

---

### 关键词监听与自动化联动

- **多种匹配模式**：包含匹配（contains）、全文本匹配（exact）、正则表达式（regex）。
- **联动响应**：命中关键词后，支持推送到 Telegram Bot、多号转发、Bark 推送、自定义 Webhook，或触发后续动作序列。
- **分片与分流**：多实例场景下可配置监听分片，均衡群组消息负载。

详见 [关键词监听](/guide/keyword-monitor)。

---

### 运维、可观测与灾难恢复

全方位的系统监控、可观测流与数据容灾机制，保障自动化挂机系统长期稳定运行。

<p align="center">
  <img src="/screenshots/logs.png" alt="实时运行日志与执行记录" style="border-radius: 8px; border: 1px solid var(--vp-c-divider);">
</p>

- **实时日志流（SSE & WebSocket）**：仪表盘 SSE 实时推送与任务运行 WebSocket 流，实时展示等待锁、冷却、执行中各 phase 状态。
- **多维度检索与过滤**：支持按账号、任务、时间范围、成功/失败状态，以及 11 类失败分类标签快速筛选。
- **WebDAV 云端加密备份**：内置坚果云、Nextcloud 等快捷预设，支持定时自动上传 `.spbak` 加密备份包或本地下载完整归档。
- **多渠道通知矩阵**：支持 Telegram Bot、企业微信、飞书机器人、钉钉、Discord Webhook，提供静默时段与失败告警保护。

<p align="center">
  <img src="/screenshots/settings.png" alt="系统设置与 WebDAV 云端备份" style="border-radius: 8px; border: 1px solid var(--vp-c-divider);">
</p>

详见 [备份与恢复](/guide/backup-webdav) 与 [运维手册](/reference/ops)。

---

### 移动端与 PWA 体验

面板采用流式响应式布局，无论在桌面宽屏、平板还是手机端均能获得一致的操控体验。

<p align="center">
  <img src="/screenshots/mobile.png" alt="PWA 移动端自适应" style="border-radius: 8px; border: 1px solid var(--vp-c-divider); max-width: 320px;">
</p>

- **渐进式 Web 应用（PWA）**：支持一键「添加到主屏幕」，无需在应用商店下载即可作为独立 App 启动。
- **深色模式与触控优化**：针对移动端手势优化抽屉导航、标签筛选与卡片操作，随时随地查看打卡大盘。

---

## 适合场景

- 多账号机器人签到、每日打卡、金币与积分领取
- 验证码、诗句填空、数学题、按钮人机校验
- 官方公告群组 / 频道长期关键词监控与即时告警
- VPS / 软路由 / NAS / Docker 长期无人值守托管

## 下一步

- [快速开始](/guide/quick-start)
- [账号管理](/guide/accounts)
- [任务编排](/guide/tasks)
- [AI 动作](/guide/ai)
- [JEV 语义决策](/guide/jev)
- [备份与恢复（WebDAV / 对象存储）](/guide/backup-webdav)
- [Docker 部署](/deploy/docker)

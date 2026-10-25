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

<div style="margin-top: 2.5rem; text-align: center;">
  <h2 style="font-size: 1.75rem; font-weight: 700; margin-bottom: 0.5rem; border: none;">视觉预览</h2>
  <p style="color: var(--vp-c-text-2); font-size: 0.95rem; margin-bottom: 1.5rem;">现代化 Web 控制台与 PWA 移动端自适应，集账号状态监控、多步动作流编排与运行可观测性于一体</p>
  
  <p align="center">
    <a href="/screenshots/dashboard.png" target="_blank">
      <img src="/screenshots/dashboard.png" alt="TG-SignPulse 仪表盘" style="border-radius: 8px; box-shadow: 0 8px 30px rgba(0,0,0,0.3); border: 1px solid var(--vp-c-divider); max-width: 100%;">
    </a>
  </p>
</div>

<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.5rem; margin-top: 2rem;">
  <div style="border: 1px solid var(--vp-c-divider); border-radius: 8px; padding: 1rem; background: var(--vp-c-bg-soft);">
    <h3 style="margin-top: 0; font-size: 1.1rem; font-weight: 600;">⚡ 任务动作流编排</h3>
    <p style="font-size: 0.85rem; color: var(--vp-c-text-2); margin-bottom: 0.75rem;">拖拽式编排发送文本、按钮点击与 AI 识图验证，单步超时与重试细粒度可控。</p>
    <a href="/screenshots/task-editor.png" target="_blank">
      <img src="/screenshots/task-editor.png" alt="任务动作流编排" style="border-radius: 6px; border: 1px solid var(--vp-c-divider);">
    </a>
  </div>
  <div style="border: 1px solid var(--vp-c-divider); border-radius: 8px; padding: 1rem; background: var(--vp-c-bg-soft);">
    <h3 style="margin-top: 0; font-size: 1.1rem; font-weight: 600;">📱 多账号与设备画像</h3>
    <p style="font-size: 0.85rem; color: var(--vp-c-text-2); margin-bottom: 0.75rem;">官方二维码扫码登录、会话导入，配合桌面/移动端设备指纹防风控画像。</p>
    <a href="/screenshots/accounts.png" target="_blank">
      <img src="/screenshots/accounts.png" alt="多账号与设备画像" style="border-radius: 6px; border: 1px solid var(--vp-c-divider);">
    </a>
  </div>
</div>

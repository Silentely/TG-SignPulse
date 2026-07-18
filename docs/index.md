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

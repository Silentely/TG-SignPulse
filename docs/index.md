---
layout: home

hero:
  name: TG-SignPulse
  text: Telegram 自动化、监听与 AI 任务编排面板
  tagline: 面向多账号签到、机器人交互、关键词监听、AI 识图和 Docker 部署的统一控制台。
  image:
    src: /logo.svg
    alt: TG-SignPulse
  actions:
    - theme: brand
      text: 快速开始
      link: /guide/quick-start
    - theme: alt
      text: Docker 部署
      link: /deploy/docker
    - theme: alt
      text: GitHub 仓库
      link: https://github.com/akasls/TG-SignPulse

features:
  - title: 多账号共享任务
    details: 一套任务流程可以绑定多个账号，统一维护步骤，适合批量签到、批量打卡和多号机器人交互。
  - title: AI 验证处理
    details: 支持识图选项、OCR 文本提取、计算题作答、AI 推断后点按钮，并允许逐动作自定义 AI 提示词。
  - title: 监听触发自动化
    details: 支持关键词包含、完全匹配、正则，命中后可通知、转发或继续执行后续动作序列。
  - title: 容器友好部署
    details: 内置 Docker 和 GHCR 测试镜像流程，支持健康检查、数据持久化和 GitHub Pages 文档发布。
---

## 为什么用 TG-SignPulse

TG-SignPulse 不是单一脚本，而是一套可长期维护的 Telegram 自动化控制台。你可以在一个面板里完成账号管理、任务编排、AI 验证、监听规则、日志查看和部署升级。

## 文档入口

- [快速开始](/guide/quick-start)
- [Docker 部署](/deploy/docker)
- [账号管理](/guide/accounts)
- [任务编排](/guide/tasks)
- [AI 动作](/guide/ai)
- [关键词监听](/guide/keyword-monitor)
- [配置参考](/reference/configuration)
- [运维手册](/reference/ops)
- [系统架构](/reference/architecture)
- [常见问题](/faq)

## 适合的场景

- 多账号机器人签到与日常打卡
- 验证码、诗句填空、数学题、按钮验证
- 群组或频道长期监听与通知
- VPS / Docker 长期托管
- GitHub 上对外发布产品文档

## 本地预览

```bash
npm install
npm run docs:dev
```

默认访问：

```text
http://127.0.0.1:5173
```

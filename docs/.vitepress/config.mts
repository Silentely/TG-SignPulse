import { defineConfig } from "vitepress";

const repository = process.env.GITHUB_REPOSITORY || "Silentely/TG-SignPulse";
const repositoryName = repository.split("/")[1] || "TG-SignPulse";
const isGitHubActions = process.env.GITHUB_ACTIONS === "true";
const editBranch =
  process.env.VITEPRESS_EDIT_BRANCH ||
  process.env.GITHUB_REF_NAME ||
  "main";
// Vercel / 本地默认 base=/；仅 GitHub Actions 构建 Pages 时用仓库名子路径
const base =
  process.env.VITEPRESS_BASE ||
  (isGitHubActions && !process.env.VERCEL ? `/${repositoryName}/` : "/");
// 生产文档站：https://tg.cosr.eu.org （Vercel 自定义域名）
const siteUrl =
  process.env.VITEPRESS_SITE_URL ||
  (process.env.VERCEL
    ? "https://tg.cosr.eu.org"
    : isGitHubActions && !process.env.VERCEL
      ? `https://${repository.split("/")[0]}.github.io/${repositoryName}`
      : "http://127.0.0.1:5173");

export default defineConfig({
  lang: "zh-CN",
  title: "TG-SignPulse",
  description:
    "Telegram 多账号自动化管理面板：签到、消息编排、关键词监听与 AI 验证。",
  base,
  // Vercel 上配合根目录 vercel.json 的 rewrite 使用 clean URL
  cleanUrls: true,
  lastUpdated: true,
  ignoreDeadLinks: true,

  head: [
    ["link", { rel: "icon", href: `${base}logo.svg`, type: "image/svg+xml" }],
    ["meta", { name: "theme-color", content: "#229ED9" }],
    ["meta", { name: "author", content: "TG-SignPulse" }],
    ["meta", { property: "og:type", content: "website" }],
    ["meta", { property: "og:title", content: "TG-SignPulse 文档" }],
    [
      "meta",
      {
        property: "og:description",
        content:
          "Telegram 多账号自动化管理面板：签到、消息编排、关键词监听与 AI 验证。",
      },
    ],
    ["meta", { property: "og:url", content: siteUrl }],
    ["meta", { property: "og:site_name", content: "TG-SignPulse" }],
    ["meta", { property: "og:locale", content: "zh_CN" }],
    ["meta", { property: "og:image", content: `${siteUrl}/logo.svg` }],
    ["meta", { name: "twitter:card", content: "summary" }],
    ["meta", { name: "twitter:title", content: "TG-SignPulse 文档" }],
    [
      "meta",
      {
        name: "twitter:description",
        content: "Telegram 多账号自动化：签到 · 编排 · 监听 · AI",
      },
    ],
    [
      "script",
      { type: "application/ld+json" },
      JSON.stringify({
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        name: "TG-SignPulse",
        description:
          "Telegram 多账号自动化管理面板，支持签到、消息编排、关键词监听与 AI 验证。",
        url: siteUrl,
        applicationCategory: "DeveloperApplication",
        operatingSystem: "Linux, macOS, Windows, Docker",
        offers: { "@type": "Offer", price: "0", priceCurrency: "CNY" },
        author: { "@type": "Organization", name: "TG-SignPulse" },
      }),
    ],
  ],

  markdown: {
    lineNumbers: true,
  },

  themeConfig: {
    logo: "/logo.svg",
    siteTitle: "TG-SignPulse",

    nav: [
      { text: "首页", link: "/" },
      { text: "功能介绍", link: "/features" },
      { text: "快速开始", link: "/guide/quick-start" },
      {
        text: "部署",
        items: [
          { text: "Docker 部署", link: "/deploy/docker" },
          { text: "Nginx 反向代理", link: "/deploy/nginx" },
        ],
      },
      {
        text: "参考",
        items: [
          { text: "配置参考", link: "/reference/configuration" },
          { text: "运维手册", link: "/reference/ops" },
          { text: "系统架构", link: "/reference/architecture" },
        ],
      },
      { text: "常见问题", link: "/faq" },
    ],

    sidebar: [
      {
        text: "开始",
        items: [
          { text: "功能介绍", link: "/features" },
          { text: "快速开始", link: "/guide/quick-start" },
          { text: "文档总览", link: "/README" },
        ],
      },
      {
        text: "使用指南",
        items: [
          { text: "账号管理", link: "/guide/accounts" },
          { text: "任务编排", link: "/guide/tasks" },
          { text: "AI 动作", link: "/guide/ai" },
          { text: "关键词监听", link: "/guide/keyword-monitor" },
          { text: "WebDAV 备份与恢复", link: "/guide/backup-webdav" },
        ],
      },
      {
        text: "部署",
        items: [
          { text: "Docker 部署", link: "/deploy/docker" },
          { text: "Nginx 反向代理", link: "/deploy/nginx" },
        ],
      },
      {
        text: "参考",
        items: [
          { text: "配置参考", link: "/reference/configuration" },
          { text: "运维手册", link: "/reference/ops" },
          { text: "系统架构", link: "/reference/architecture" },
          { text: "设备管理", link: "/reference/device-management" },
          { text: "开发规范", link: "/reference/development" },
        ],
      },
      {
        text: "帮助",
        items: [
          { text: "常见问题", link: "/faq" },
        ],
      },
    ],

    socialLinks: [
      { icon: "github", link: `https://github.com/${repository}` },
    ],

    search: {
      provider: "local",
      options: {
        translations: {
          button: {
            buttonText: "搜索文档",
            buttonAriaLabel: "搜索文档",
          },
          modal: {
            noResultsText: "无法找到相关结果",
            resetButtonTitle: "清除查询条件",
            footer: {
              selectText: "选择",
              navigateText: "切换",
              closeText: "关闭",
            },
          },
        },
      },
    },

    editLink: {
      pattern: `https://github.com/${repository}/edit/${editBranch}/docs/:path`,
      text: "在 GitHub 上编辑此页面",
    },

    lastUpdated: {
      text: "最后更新于",
      formatOptions: {
        dateStyle: "medium",
        timeStyle: "short",
      },
    },

    outline: {
      level: [2, 3],
      label: "页面导航",
    },

    footer: {
      message: "基于 <a href=\"https://vitepress.dev/\">VitePress</a> 构建 · 默认 SQLite，可选 PostgreSQL",
      copyright: "Copyright © 2026 TG-SignPulse",
    },

    docFooter: {
      prev: "上一页",
      next: "下一页",
    },

    returnToTopLabel: "回到顶部",
    sidebarMenuLabel: "菜单",
    darkModeSwitchLabel: "主题",
    lightModeSwitchTitle: "切换到浅色模式",
    darkModeSwitchTitle: "切换到深色模式",
  },
});

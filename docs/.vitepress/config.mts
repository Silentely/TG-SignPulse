import { defineConfig } from "vitepress";

const repository = process.env.GITHUB_REPOSITORY || "akasls/TG-SignPulse";
const repositoryName = repository.split("/")[1] || "TG-SignPulse";
const isGitHubActions = process.env.GITHUB_ACTIONS === "true";
const editBranch =
  process.env.VITEPRESS_EDIT_BRANCH ||
  process.env.GITHUB_REF_NAME ||
  "main";
const base =
  process.env.VITEPRESS_BASE ||
  (isGitHubActions ? `/${repositoryName}/` : "/");

export default defineConfig({
  lang: "zh-CN",
  title: "TG-SignPulse",
  description:
    "Telegram 自动化、任务编排、关键词监听与 AI 验证处理文档。",
  base,
  cleanUrls: true,
  lastUpdated: true,
  head: [
    ["link", { rel: "icon", href: `${base}logo.svg` }],
    ["meta", { name: "theme-color", content: "#229ED9" }]
  ],
  themeConfig: {
    logo: "/logo.svg",
    siteTitle: "TG-SignPulse Docs",
    nav: [
      { text: "首页", link: "/" },
      { text: "快速开始", link: "/guide/quick-start" },
      { text: "部署", link: "/deploy/docker" },
      { text: "配置", link: "/reference/configuration" },
      { text: "FAQ", link: "/faq" }
    ],
    sidebar: [
      {
        text: "开始使用",
        items: [
          { text: "文档首页", link: "/" },
          { text: "GitHub 文档入口", link: "/README" },
          { text: "快速开始", link: "/guide/quick-start" }
        ]
      },
      {
        text: "使用指南",
        items: [
          { text: "账号管理", link: "/guide/accounts" },
          { text: "任务编排", link: "/guide/tasks" },
          { text: "AI 动作", link: "/guide/ai" },
          { text: "关键词监听", link: "/guide/keyword-monitor" }
        ]
      },
      {
        text: "部署与运维",
        items: [
          { text: "Docker 部署", link: "/deploy/docker" },
          { text: "配置参考", link: "/reference/configuration" },
          { text: "运维手册", link: "/reference/ops" },
          { text: "系统架构", link: "/reference/architecture" }
        ]
      },
      {
        text: "附录",
        items: [
          { text: "常见问题", link: "/faq" },
          { text: "文档目录", link: "/SUMMARY" }
        ]
      }
    ],
    socialLinks: [
      { icon: "github", link: "https://github.com/akasls/TG-SignPulse" }
    ],
    search: {
      provider: "local"
    },
    editLink: {
      pattern: `https://github.com/akasls/TG-SignPulse/edit/${editBranch}/docs/:path`,
      text: "在 GitHub 上编辑此页"
    },
    outline: {
      level: [2, 3],
      label: "本页导航"
    },
    footer: {
      message: "TG-SignPulse 文档站点基于 VitePress 构建。",
      copyright: "Copyright © 2026 TG-SignPulse"
    },
    docFooter: {
      prev: "上一页",
      next: "下一页"
    },
    returnToTopLabel: "回到顶部",
    sidebarMenuLabel: "菜单",
    darkModeSwitchLabel: "主题切换",
    lightModeSwitchTitle: "切换到浅色模式",
    darkModeSwitchTitle: "切换到深色模式"
  }
});

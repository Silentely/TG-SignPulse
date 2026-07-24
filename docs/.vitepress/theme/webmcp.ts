/**
 * WebMCP：向支持 navigator.modelContext 的浏览器 Agent 暴露文档站工具。
 * 规范参考：https://webmachinelearning.github.io/webmcp/
 */

type JsonSchema = Record<string, unknown>;

type WebMcpTool = {
  name: string;
  description: string;
  inputSchema: JsonSchema;
  execute: (args: Record<string, unknown>) => Promise<unknown> | unknown;
};

type ModelContext = {
  registerTool?: (tool: WebMcpTool) => void;
  provideContext?: (ctx: { tools: WebMcpTool[] }) => void;
};

const DOC_CATALOG: Record<string, { title: string; path: string; summary: string }> =
  {
    home: {
      title: "首页",
      path: "/",
      summary: "TG-SignPulse 产品总览与入口",
    },
    features: {
      title: "功能介绍",
      path: "/features",
      summary: "核心能力与适用场景",
    },
    "quick-start": {
      title: "快速开始",
      path: "/guide/quick-start",
      summary: "5 分钟部署到第一个任务",
    },
    accounts: {
      title: "账号管理",
      path: "/guide/accounts",
      summary: "短信/二维码登录、2FA、代理",
    },
    tasks: {
      title: "任务编排",
      path: "/guide/tasks",
      summary: "动作类型、调度、多账号共享",
    },
    ai: {
      title: "AI 动作",
      path: "/guide/ai",
      summary: "OpenAI 兼容接口与提示词",
    },
    "keyword-monitor": {
      title: "关键词监听",
      path: "/guide/keyword-monitor",
      summary: "匹配规则与推送通道",
    },
    docker: {
      title: "Docker 部署",
      path: "/deploy/docker",
      summary: "容器部署与持久化",
    },
    nginx: {
      title: "Nginx 反向代理",
      path: "/deploy/nginx",
      summary: "反向代理与 SSE 配置",
    },
    configuration: {
      title: "配置参考",
      path: "/reference/configuration",
      summary: "环境变量与数据目录",
    },
    ops: {
      title: "运维手册",
      path: "/reference/ops",
      summary: "健康检查、备份、版本与调度",
    },
    architecture: {
      title: "系统架构",
      path: "/reference/architecture",
      summary: "前后端、调度器与执行引擎",
    },
    faq: {
      title: "常见问题",
      path: "/faq",
      summary: "登录、AI、镜像与监听 FAQ",
    },
    auth: {
      title: "Agent 认证",
      path: "/auth.md",
      summary: "JWT 登录与 OAuth 发现元数据",
    },
  };

function absoluteUrl(path: string): string {
  if (typeof window === "undefined") {
    return `https://tg.cosr.eu.org${path}`;
  }
  return new URL(path, window.location.origin).toString();
}

function getModelContext(): ModelContext | null {
  if (typeof navigator === "undefined") return null;
  const nav = navigator as Navigator & { modelContext?: ModelContext };
  return nav.modelContext ?? null;
}

function buildTools(): WebMcpTool[] {
  return [
    {
      name: "list_docs",
      description:
        "列出 TG-SignPulse 文档站主要页面（标题、路径、摘要），用于导航。",
      inputSchema: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
      execute: async () => {
        return Object.entries(DOC_CATALOG).map(([id, item]) => ({
          id,
          title: item.title,
          url: absoluteUrl(item.path),
          summary: item.summary,
        }));
      },
    },
    {
      name: "search_docs",
      description:
        "按关键词在文档目录中检索相关页面（部署、账号、任务、AI、监听、运维等）。",
      inputSchema: {
        type: "object",
        properties: {
          query: {
            type: "string",
            description: "搜索关键词，例如 docker、TOTP、关键词监听",
          },
        },
        required: ["query"],
        additionalProperties: false,
      },
      execute: async (args) => {
        const q = String(args.query || "")
          .trim()
          .toLowerCase();
        if (!q) return [];
        const hits = Object.entries(DOC_CATALOG)
          .filter(([id, item]) => {
            const blob = `${id} ${item.title} ${item.summary} ${item.path}`.toLowerCase();
            return q.split(/\s+/).every((token) => blob.includes(token));
          })
          .map(([id, item]) => ({
            id,
            title: item.title,
            url: absoluteUrl(item.path),
            summary: item.summary,
          }));
        return hits.length ? hits : Object.entries(DOC_CATALOG).slice(0, 5).map(
          ([id, item]) => ({
            id,
            title: item.title,
            url: absoluteUrl(item.path),
            summary: item.summary,
            note: "无精确匹配，返回推荐入口",
          }),
        );
      },
    },
    {
      name: "get_doc_url",
      description: "根据文档 id 返回规范 URL。",
      inputSchema: {
        type: "object",
        properties: {
          id: {
            type: "string",
            description: `文档 id，可选：${Object.keys(DOC_CATALOG).join(", ")}`,
          },
        },
        required: ["id"],
        additionalProperties: false,
      },
      execute: async (args) => {
        const id = String(args.id || "");
        const item = DOC_CATALOG[id];
        if (!item) {
          return {
            error: "unknown_id",
            available: Object.keys(DOC_CATALOG),
          };
        }
        return {
          id,
          title: item.title,
          url: absoluteUrl(item.path),
          summary: item.summary,
        };
      },
    },
    {
      name: "open_doc",
      description: "在当前浏览器导航到指定文档页。",
      inputSchema: {
        type: "object",
        properties: {
          id: {
            type: "string",
            description: "文档 id，见 list_docs",
          },
        },
        required: ["id"],
        additionalProperties: false,
      },
      execute: async (args) => {
        const id = String(args.id || "");
        const item = DOC_CATALOG[id];
        if (!item) {
          return { error: "unknown_id", available: Object.keys(DOC_CATALOG) };
        }
        const url = absoluteUrl(item.path);
        if (typeof window !== "undefined") {
          window.location.assign(url);
        }
        return { navigated: true, url };
      },
    },
  ];
}

/** 在浏览器端注册 WebMCP 工具；不支持时静默跳过。 */
export function setupWebMcp(): void {
  if (typeof window === "undefined") return;

  const register = () => {
    const ctx = getModelContext();
    if (!ctx) return false;
    const tools = buildTools();
    try {
      if (typeof ctx.provideContext === "function") {
        ctx.provideContext({ tools });
        return true;
      }
      if (typeof ctx.registerTool === "function") {
        for (const tool of tools) {
          ctx.registerTool(tool);
        }
        return true;
      }
    } catch (err) {
      console.debug("[webmcp] register failed", err);
    }
    return false;
  };

  if (register()) return;

  // 部分实现会在 load 后注入 modelContext
  window.addEventListener("load", () => {
    register();
  });
  // 短轮询兜底（约 3s）
  let attempts = 0;
  const timer = window.setInterval(() => {
    attempts += 1;
    if (register() || attempts >= 10) {
      window.clearInterval(timer);
    }
  }, 300);
}

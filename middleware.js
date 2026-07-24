/**
 * Vercel Edge Middleware
 * - Link 响应头（RFC 8288）便于 Agent 发现
 * - Accept: text/markdown 内容协商（Markdown for Agents）
 */
export const config = {
  matcher: [
    "/",
    "/((?!assets/|_next/|favicon|logo\\.svg|vp-icons).*)",
  ],
};

const SITE = "https://tg.cosr.eu.org";

const LINK_HEADER = [
  `<${SITE}/.well-known/api-catalog>; rel="api-catalog"; type="application/linkset+json"`,
  `<${SITE}/.well-known/mcp/server-card.json>; rel="service-desc"; type="application/json"`,
  `<${SITE}/.well-known/agent-skills/index.json>; rel="describedby"; type="application/json"`,
  `<${SITE}/.well-known/agent-card.json>; rel="alternate"; type="application/json"`,
  `<${SITE}/llms.txt>; rel="describedby"; type="text/plain"`,
  `<${SITE}/auth.md>; rel="service-doc"; type="text/markdown"`,
  `<${SITE}/sitemap.xml>; rel="describedby"; type="application/xml"`,
  `<${SITE}/.well-known/oauth-protected-resource>; rel="oauth-protected-resource"; type="application/json"`,
].join(", ");

/** 不参与 markdown 协商的静态/机器可读路径前缀 */
const SKIP_MARKDOWN_PREFIXES = [
  "/assets/",
  "/.well-known/",
  "/_sources/",
  "/robots.txt",
  "/sitemap.xml",
  "/llms.txt",
  "/logo.svg",
  "/hashmap.json",
  "/vp-icons.css",
];

function wantsMarkdown(acceptHeader) {
  if (!acceptHeader) return false;
  const accept = acceptHeader.toLowerCase();
  // 显式 text/markdown 且优先级不低于 text/html
  if (!accept.includes("text/markdown")) return false;
  const parts = accept.split(",").map((p) => p.trim());
  let mdQ = 0;
  let htmlQ = 0;
  for (const part of parts) {
    const [type, ...params] = part.split(";").map((s) => s.trim());
    let q = 1;
    for (const param of params) {
      if (param.startsWith("q=")) {
        const n = Number(param.slice(2));
        if (!Number.isNaN(n)) q = n;
      }
    }
    if (type === "text/markdown") mdQ = q;
    if (type === "text/html") htmlQ = q;
  }
  return mdQ > 0 && mdQ >= htmlQ;
}

function estimateTokens(text) {
  // 粗略估计：中英混合约 2 字符/token
  return Math.max(1, Math.ceil(text.length / 2));
}

function sourcePathFor(pathname) {
  if (pathname === "/" || pathname === "") {
    return "/_sources/index.md";
  }
  // 去掉尾斜杠
  let p = pathname.replace(/\/$/, "");
  // 已是 .md / .txt
  if (p.endsWith(".md") || p.endsWith(".txt")) {
    return `/_sources${p.startsWith("/") ? p : `/${p}`}`;
  }
  return `/_sources${p}.md`;
}

function applyLinkHeader(response) {
  const headers = new Headers(response.headers);
  headers.set("Link", LINK_HEADER);
  // 允许跨源探测 Link / Content-Type
  headers.set(
    "Access-Control-Expose-Headers",
    "Link, Content-Type, x-markdown-tokens",
  );
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

export default async function middleware(request) {
  const url = new URL(request.url);
  const { pathname } = url;

  // 始终为 HTML/协商响应附加 Link（静态文件也附加，便于发现）
  if (!wantsMarkdown(request.headers.get("accept") || "")) {
    const res = await fetch(request);
    // 仅对文档页与首页附加（避免污染二进制资源）
    const isDocLike =
      pathname === "/" ||
      (!pathname.includes(".") && !pathname.startsWith("/assets/")) ||
      pathname.endsWith(".html") ||
      pathname.endsWith(".md") ||
      pathname.endsWith(".txt");
    if (isDocLike && res.status === 200) {
      return applyLinkHeader(res);
    }
    return res;
  }

  // Markdown 协商
  for (const prefix of SKIP_MARKDOWN_PREFIXES) {
    if (pathname === prefix || pathname.startsWith(prefix)) {
      const res = await fetch(request);
      return applyLinkHeader(res);
    }
  }

  const sourcePath = sourcePathFor(pathname);
  const sourceUrl = new URL(sourcePath, url.origin);
  const mdRes = await fetch(sourceUrl.toString(), {
    headers: { Accept: "text/plain,*/*" },
  });

  if (!mdRes.ok) {
    // 回退到原始 HTML，仍附加 Link
    const fallback = await fetch(request);
    return applyLinkHeader(fallback);
  }

  const body = await mdRes.text();
  const tokens = estimateTokens(body);
  const headers = new Headers({
    "Content-Type": "text/markdown; charset=utf-8",
    "x-markdown-tokens": String(tokens),
    "Cache-Control": "public, max-age=300, stale-while-revalidate=86400",
    Link: LINK_HEADER,
    "Access-Control-Expose-Headers":
      "Link, Content-Type, x-markdown-tokens",
  });

  return new Response(body, { status: 200, headers });
}

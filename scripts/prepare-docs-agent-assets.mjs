#!/usr/bin/env node
/**
 * 在 VitePress 构建前后准备 Agent 发现资产：
 * - 同步 markdown 源到 public/_sources（供 Accept: text/markdown）
 * - 生成 sitemap.xml
 * - 计算 agent-skills digest 并写入 index.json
 */
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const docsDir = path.join(root, "docs");
const publicDir = path.join(docsDir, "public");
const sourcesDir = path.join(publicDir, "_sources");
const siteUrl =
  process.env.VITEPRESS_SITE_URL || "https://tg.cosr.eu.org";

/** 公开文档页（不含 superpowers 内部设计稿） */
const DOC_PAGES = [
  { route: "/", file: "index.md", priority: "1.0", changefreq: "weekly" },
  { route: "/features", file: "features.md", priority: "0.9", changefreq: "monthly" },
  { route: "/README", file: "README.md", priority: "0.8", changefreq: "monthly" },
  { route: "/faq", file: "faq.md", priority: "0.7", changefreq: "monthly" },
  {
    route: "/guide/quick-start",
    file: "guide/quick-start.md",
    priority: "0.95",
    changefreq: "monthly",
  },
  {
    route: "/guide/accounts",
    file: "guide/accounts.md",
    priority: "0.8",
    changefreq: "monthly",
  },
  {
    route: "/guide/tasks",
    file: "guide/tasks.md",
    priority: "0.8",
    changefreq: "monthly",
  },
  { route: "/guide/ai", file: "guide/ai.md", priority: "0.8", changefreq: "monthly" },
  {
    route: "/guide/keyword-monitor",
    file: "guide/keyword-monitor.md",
    priority: "0.8",
    changefreq: "monthly",
  },
  {
    route: "/guide/backup-webdav",
    file: "guide/backup-webdav.md",
    priority: "0.7",
    changefreq: "monthly",
  },
  {
    route: "/deploy/docker",
    file: "deploy/docker.md",
    priority: "0.9",
    changefreq: "monthly",
  },
  {
    route: "/deploy/nginx",
    file: "deploy/nginx.md",
    priority: "0.7",
    changefreq: "monthly",
  },
  {
    route: "/deploy/dns-aid",
    file: "deploy/dns-aid.md",
    priority: "0.4",
    changefreq: "yearly",
  },
  {
    route: "/reference/configuration",
    file: "reference/configuration.md",
    priority: "0.85",
    changefreq: "monthly",
  },
  {
    route: "/reference/ops",
    file: "reference/ops.md",
    priority: "0.8",
    changefreq: "monthly",
  },
  {
    route: "/reference/architecture",
    file: "reference/architecture.md",
    priority: "0.7",
    changefreq: "monthly",
  },
  {
    route: "/reference/device-management",
    file: "reference/device-management.md",
    priority: "0.6",
    changefreq: "monthly",
  },
  {
    route: "/reference/development",
    file: "reference/development.md",
    priority: "0.6",
    changefreq: "monthly",
  },
  { route: "/auth.md", file: null, priority: "0.5", changefreq: "yearly" },
  { route: "/llms.txt", file: null, priority: "0.5", changefreq: "monthly" },
];

const SKILLS = [
  {
    name: "docs-navigator",
    type: "skill-md",
    description:
      "根据主题定位 TG-SignPulse 官方文档页面（部署、账号、任务、AI、监听、运维）。",
    relativePath: ".well-known/agent-skills/docs-navigator/SKILL.md",
  },
  {
    name: "quick-start",
    type: "skill-md",
    description:
      "引导完成 TG-SignPulse 安装、登录、添加账号与创建第一个签到任务。",
    relativePath: ".well-known/agent-skills/quick-start/SKILL.md",
  },
];

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function sha256File(filePath) {
  const buf = fs.readFileSync(filePath);
  return crypto.createHash("sha256").update(buf).digest("hex");
}

function copyMarkdownSources() {
  ensureDir(sourcesDir);
  // 首页
  const homeMd = path.join(docsDir, "index.md");
  if (fs.existsSync(homeMd)) {
    fs.copyFileSync(homeMd, path.join(sourcesDir, "index.md"));
    // 根路径 `/` 的 markdown 协商也落到 index.md
    fs.copyFileSync(homeMd, path.join(sourcesDir, "home.md"));
  }
  for (const page of DOC_PAGES) {
    if (!page.file) continue;
    const src = path.join(docsDir, page.file);
    if (!fs.existsSync(src)) {
      console.warn(`[agent-assets] skip missing ${page.file}`);
      continue;
    }
    // clean URL 对应：/guide/quick-start -> _sources/guide/quick-start.md
    const destRel =
      page.route === "/"
        ? "index.md"
        : `${page.route.replace(/^\//, "")}.md`;
    const dest = path.join(sourcesDir, destRel);
    ensureDir(path.dirname(dest));
    fs.copyFileSync(src, dest);
  }
  // auth.md / llms.txt 已在 public，再镜像一份便于协商
  for (const name of ["auth.md", "llms.txt", "robots.txt"]) {
    const p = path.join(publicDir, name);
    if (fs.existsSync(p)) {
      fs.copyFileSync(p, path.join(sourcesDir, name));
    }
  }
  console.log(`[agent-assets] markdown sources -> ${sourcesDir}`);
}

function writeSitemap() {
  const lastmod = new Date().toISOString().slice(0, 10);
  const urls = DOC_PAGES.map((page) => {
    const loc =
      page.route === "/"
        ? `${siteUrl}/`
        : `${siteUrl}${page.route.startsWith("/") ? page.route : `/${page.route}`}`;
    return `  <url>
    <loc>${loc}</loc>
    <lastmod>${lastmod}</lastmod>
    <changefreq>${page.changefreq}</changefreq>
    <priority>${page.priority}</priority>
  </url>`;
  }).join("\n");

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls}
</urlset>
`;
  const out = path.join(publicDir, "sitemap.xml");
  fs.writeFileSync(out, xml, "utf8");
  console.log(`[agent-assets] sitemap -> ${out} (${DOC_PAGES.length} urls)`);
}

function writeAgentSkillsIndex() {
  const skills = SKILLS.map((skill) => {
    const abs = path.join(publicDir, skill.relativePath);
    if (!fs.existsSync(abs)) {
      throw new Error(`Skill file missing: ${abs}`);
    }
    const digest = `sha256:${sha256File(abs)}`;
    return {
      name: skill.name,
      type: skill.type,
      description: skill.description,
      url: `/${skill.relativePath}`,
      digest,
    };
  });

  const index = {
    $schema: "https://schemas.agentskills.io/discovery/0.2.0/schema.json",
    skills,
  };
  const outDir = path.join(publicDir, ".well-known", "agent-skills");
  ensureDir(outDir);
  const out = path.join(outDir, "index.json");
  fs.writeFileSync(out, `${JSON.stringify(index, null, 2)}\n`, "utf8");
  console.log(`[agent-assets] agent-skills index -> ${out}`);
}

function main() {
  ensureDir(publicDir);
  copyMarkdownSources();
  writeSitemap();
  writeAgentSkillsIndex();
}

main();

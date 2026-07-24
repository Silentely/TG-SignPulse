#!/usr/bin/env node
/**
 * 本地校验 docs 构建产物是否包含 Agent 发现所需文件。
 * 用法：npm run docs:build && npm run docs:verify-agent
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const dist = path.resolve(__dirname, "../docs/.vitepress/dist");

const required = [
  "robots.txt",
  "sitemap.xml",
  "llms.txt",
  "auth.md",
  "_sources/index.md",
  "_sources/guide/quick-start.md",
  ".well-known/api-catalog",
  ".well-known/agent-skills/index.json",
  ".well-known/agent-skills/docs-navigator/SKILL.md",
  ".well-known/agent-skills/quick-start/SKILL.md",
  ".well-known/mcp/server-card.json",
  ".well-known/agent-card.json",
  ".well-known/oauth-protected-resource",
  ".well-known/oauth-authorization-server",
  ".well-known/openid-configuration",
  ".well-known/health.json",
  ".well-known/openapi-selfhosted.json",
];

if (!fs.existsSync(dist)) {
  console.error(`[verify] dist 不存在: ${dist}`);
  process.exit(1);
}

let failed = 0;
for (const rel of required) {
  const abs = path.join(dist, rel);
  if (!fs.existsSync(abs)) {
    console.error(`[fail] missing ${rel}`);
    failed += 1;
    continue;
  }
  const st = fs.statSync(abs);
  if (!st.isFile() || st.size === 0) {
    console.error(`[fail] empty/invalid ${rel}`);
    failed += 1;
    continue;
  }
  console.log(`[ok] ${rel} (${st.size} bytes)`);
}

// robots 必须含 AI 规则与 Content-Signal、Sitemap
const robots = fs.readFileSync(path.join(dist, "robots.txt"), "utf8");
for (const needle of [
  "User-agent: GPTBot",
  "User-agent: Claude-Web",
  "User-agent: Google-Extended",
  "Content-Signal:",
  "Sitemap:",
]) {
  if (!robots.includes(needle)) {
    console.error(`[fail] robots.txt missing: ${needle}`);
    failed += 1;
  } else {
    console.log(`[ok] robots.txt has ${needle}`);
  }
}

// skills index schema
const skills = JSON.parse(
  fs.readFileSync(path.join(dist, ".well-known/agent-skills/index.json"), "utf8"),
);
if (skills.$schema !== "https://schemas.agentskills.io/discovery/0.2.0/schema.json") {
  console.error("[fail] agent-skills $schema mismatch");
  failed += 1;
} else {
  console.log("[ok] agent-skills $schema");
}
for (const s of skills.skills || []) {
  if (!s.digest?.startsWith("sha256:") || !s.url || !s.name) {
    console.error(`[fail] skill entry incomplete: ${JSON.stringify(s)}`);
    failed += 1;
  }
}

// api-catalog shape
const catalog = JSON.parse(
  fs.readFileSync(path.join(dist, ".well-known/api-catalog"), "utf8"),
);
if (!Array.isArray(catalog.linkset) || catalog.linkset.length === 0) {
  console.error("[fail] api-catalog linkset empty");
  failed += 1;
} else {
  console.log(`[ok] api-catalog linkset (${catalog.linkset.length})`);
}

// 不应把 public 下的 md 编成 /public/*.html 文档页
const badPage = path.join(dist, "public/auth.html");
if (fs.existsSync(badPage)) {
  console.error("[fail] unexpected public/auth.html (srcExclude 未生效)");
  failed += 1;
} else {
  console.log("[ok] no public/*.html page leak");
}

// middleware + vercel headers 存在于仓库
const root = path.resolve(__dirname, "..");
for (const f of ["middleware.js", "vercel.json"]) {
  if (!fs.existsSync(path.join(root, f))) {
    console.error(`[fail] missing ${f}`);
    failed += 1;
  } else {
    console.log(`[ok] repo ${f}`);
  }
}

if (failed) {
  console.error(`\n[verify] FAILED (${failed} issues)`);
  process.exit(1);
}
console.log("\n[verify] PASS — agent discovery static assets OK");
console.log(
  "部署到 Vercel 后 Link 头与 Accept: text/markdown 由 middleware.js / vercel.json 生效。",
);
console.log("DNS-AID 需在域名 DNS 面板手动配置，见 docs/deploy/dns-aid.md");

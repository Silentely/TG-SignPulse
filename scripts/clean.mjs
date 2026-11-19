#!/usr/bin/env node
/**
 * 清理本地构建与依赖产物（不触碰业务代码与数据）。
 * 用法：pnpm run clean
 */
import { rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const targets = [
  "node_modules",
  "frontend/node_modules",
  "docs/node_modules",
  ".mypy_cache",
  "htmlcov",
  ".coverage",
  "coverage.xml",
  "dist",
  "frontend/dist",
  "frontend/playwright-report",
  "frontend/test-results",
  "playwright-report",
  "docs/.vitepress/dist",
];

for (const target of targets) {
  rmSync(path.join(root, target), { recursive: true, force: true });
  console.log(`removed ${target}`);
}

# TG-SignPulse Frontend (Vue 3 + TypeScript + Vite)

Web UI for TG-SignPulse, styled with Tailwind CSS v4 and a unified Design System inspired by Linear, SST, and Warp.

## Design System & UI 规范

- [DESIGN.md](./DESIGN.md): 权威设计规范文档，定义了全局语义颜色令牌（`--sp-*`）、倒角层级、微阴影、Warp 终端控制台与核心 UI Primitives。
- [DESIGN.reference.md](./DESIGN.reference.md): 视觉灵感来源（Linear、SST、Warp）与设计映射说明。

> **组件与页面开发强制约束**：
> 后续新增任何视图、设置子选项卡（如 `Settings.vue` 中的新 Tab）、弹窗或子组件时，**必须统一沿用 `.ui-card`、`.ui-btn-*`、`.ui-input`、`.ui-badge` 以及 `--sp-*` 变量**，严禁使用硬编码非语义 Tailwind 类（如 `border-gray-200 dark:border-gray-800`、`bg-gray-100` 等），以保证在浅色与深色主题下的渲染一致性。详见 [DESIGN.md 第 5 节规范](./DESIGN.md#5-新组件与设置子页开发约束-component--view-development-guidelines)。

## Development

```bash
# Install dependencies
npm install

# Start development server
npm run dev

# Run type checks
npm run typecheck

# Run test suite
npm test

# Build production bundle
npm run build
```

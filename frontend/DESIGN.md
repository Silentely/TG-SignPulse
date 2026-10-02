# TG-SignPulse Design System Specification (`DESIGN.md`)

> **Authoritative Design Guide for TG-SignPulse Web UI**
> Sourced and refined from Refero visual systems:
> - **Dark Mode & General Shell**: Linear (*Midnight Precision Instrument*)
> - **Light Mode**: SST (*Code Terminal in a Gallery / Ink on Paper*)
> - **Console & Execution Logs**: Warp (*Obsidian Command Center*)

---

## 1. Core Principles & Philosophy

1. **Precision Instrument Over Flash**:
   TG-SignPulse is a mission-critical Telegram automated management console. UI elements prioritize operational density, hairline structural clarity (0.5px–1px borders), and zero visual distractions.

2. **Strict Color Semantics**:
   - **Accent / Interaction**: Telegram Cyan / Sky (`#0ea5e9` light, `#38bdf8` dark).
   - **Success**: Emerald (`#10b981` light, `#34d399` dark).
   - **Warning**: Amber (`#f59e0b` light, `#fbbf24` dark).
   - **Destructive**: Rose (`#e11d48` light, `#fb7185` dark).
   - **Neutral**: Slate / Zinc tones for dividers, disabled states, and auxiliary badges.

3. **Surface & Elevation Strategy**:
   - Elevation is communicated primarily through **hairline borders (1px) and stepped surface lightness**, not heavy blurry box-shadows.
   - Light mode canvas is pristine `#ffffff` with subtle tinted surface layers (`#f8f9fb` / `#f1f3f7`).
   - Dark mode canvas is void black `#08090a` with carbon `#0f1011` cards and obsidian `#161718` elevated overlays.

4. **Domain Partitioning**:
   - **Shell & Pages**: Follows Linear Dark / SST Light clean card & table aesthetics.
   - **Runtime Logs & Console**: Follows Warp Obsidian Terminal aesthetics (stepped charcoal `#121212` / `#1e1e1d` containers, monospaced metadata, subtle colored status indicators) in both light and dark modes.

---

## 2. Token Definitions

### 2.1 CSS Custom Properties & Semantic Mappings

All tokens are defined under `:root` (Light mode) and `.dark` (Dark mode) in `frontend/src/style.css`. Legacy `--sp-*` names are fully preserved as direct semantic mappings to guarantee backward compatibility with existing components and tests.

```css
:root {
  /* Surfaces */
  --sp-canvas: #ffffff;
  --sp-bg: #f8f9fb;
  --sp-surface: #ffffff;
  --sp-surface-subtle: #f8f9fb;
  --sp-surface-muted: #f3f4f8;
  --sp-surface-elevated: #ffffff;
  --sp-surface-raised: var(--sp-surface-elevated);
  --sp-surface-overlay: #ffffff;
  --sp-bg-elevated: #ffffff;
  --sp-bg-elevated-2: #f8f9fc;
  --sp-bg-muted: #f3f4f8;

  /* Borders & Dividers */
  --sp-border: #e6e8ec;
  --sp-border-subtle: #eeeff3;
  --sp-border-strong: #d0d4dc;
  --sp-border-focus: var(--sp-accent);

  /* Typography */
  --sp-text-primary: #1e2029; /* SST Ink tone */
  --sp-text-secondary: #4b5262;
  --sp-text-muted: #747c8c;
  --sp-text-disabled: #a5abba;
  --sp-fg: var(--sp-text-primary);
  --sp-fg-secondary: var(--sp-text-secondary);
  --sp-fg-muted: var(--sp-text-muted);
  --sp-fg-disabled: var(--sp-text-disabled);
  --sp-text: var(--sp-text-primary);

  /* Brand & Accents */
  --sp-accent: #0284c7; /* Sky 600 / Telegram Cyan */
  --sp-accent-hover: #0369a1;
  --sp-accent-soft: rgba(2, 132, 199, 0.08);

  /* Status Colors */
  --sp-success: #059669;
  --sp-success-soft: rgba(5, 150, 105, 0.09);
  --sp-warning: #d97706;
  --sp-warning-soft: rgba(217, 119, 6, 0.10);
  --sp-danger: #e11d48;
  --sp-danger-soft: rgba(225, 29, 72, 0.09);
  --sp-info: #0284c7;
  --sp-info-soft: rgba(2, 132, 199, 0.09);
  --sp-violet: #7c3aed;

  /* Radii */
  --sp-radius-sm: 4px;
  --sp-radius: 6px;
  --sp-radius-md: 6px;
  --sp-radius-lg: 10px;
  --sp-radius-xl: 12px;
  --sp-radius-pill: 9999px;

  /* Elevation (Hairline + Micro-diffuse) */
  --sp-shadow-sm: 0 1px 2px rgba(15, 23, 42, 0.03);
  --sp-shadow-md: 0 4px 16px rgba(15, 23, 42, 0.05);
  --sp-shadow-lg: 0 12px 32px rgba(15, 23, 42, 0.08);

  /* Warp Console */
  --sp-terminal-bg: #101216;
  --sp-terminal-surface: #181b20;
  --sp-terminal-border: #262b33;
  --sp-terminal-text: #f3f4f6;
  --sp-terminal-muted: #8b92a0;
}

.dark {
  /* Surfaces */
  --sp-canvas: #08090a; /* Linear Void */
  --sp-bg: #08090a;
  --sp-surface: #0f1011; /* Linear Carbon */
  --sp-surface-subtle: #0c0d0f;
  --sp-surface-muted: #141517;
  --sp-surface-elevated: #161718; /* Linear Obsidian */
  --sp-surface-raised: var(--sp-surface-elevated);
  --sp-surface-overlay: #1b1d20;
  --sp-bg-elevated: #0f1011;
  --sp-bg-elevated-2: #161718;
  --sp-bg-muted: #141517;

  /* Borders & Dividers */
  --sp-border: #23252a; /* Linear Graphite */
  --sp-border-subtle: #1a1b1e;
  --sp-border-strong: #383b3f; /* Linear Smoke */
  --sp-border-focus: var(--sp-accent);

  /* Typography */
  --sp-text-primary: #ffffff;
  --sp-text-secondary: #d0d6e0;
  --sp-text-muted: #8a8f98;
  --sp-text-disabled: #62666d;
  --sp-fg: var(--sp-text-primary);
  --sp-fg-secondary: var(--sp-text-secondary);
  --sp-fg-muted: var(--sp-text-muted);
  --sp-fg-disabled: var(--sp-text-disabled);
  --sp-text: var(--sp-text-primary);

  /* Brand & Accents */
  --sp-accent: #38bdf8; /* Sky 400 */
  --sp-accent-hover: #7dd3fc;
  --sp-accent-soft: rgba(56, 189, 248, 0.14);

  /* Status Colors */
  --sp-success: #34d399;
  --sp-success-soft: rgba(52, 211, 153, 0.12);
  --sp-warning: #fbbf24;
  --sp-warning-soft: rgba(251, 191, 36, 0.12);
  --sp-danger: #fb7185;
  --sp-danger-soft: rgba(251, 113, 133, 0.12);
  --sp-info: #38bdf8;
  --sp-info-soft: rgba(56, 189, 248, 0.14);
  --sp-violet: #a78bfa;

  /* Elevation */
  --sp-shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.4);
  --sp-shadow-md: 0 10px 28px rgba(0, 0, 0, 0.5);
  --sp-shadow-lg: 0 16px 40px rgba(0, 0, 0, 0.65);

  /* Warp Console */
  --sp-terminal-bg: #090a0d;
  --sp-terminal-surface: #121418;
  --sp-terminal-border: #1f232b;
  --sp-terminal-text: #faf9f6;
  --sp-terminal-muted: #868684;
}
```

---

## 3. UI Primitives Specifications

### 3.1 App Shell (`Layout.vue`)
- **Sidebar (`.ui-sidebar`)**:
  - Light mode: crisp translucent white background with hairline right border (`--sp-border`).
  - Dark mode: void/carbon background (`rgba(10, 11, 14, 0.96)`), 1px solid `--sp-border`.
  - Active Nav (`.ui-nav-active`): subtle tinted background pill, vertical accent pip on the left border, font-medium text.
  - Brand Mark (`.ui-brand-mark`): 28px x 28px square mark with 6px border radius, high-contrast dark indigo/white gradient.
- **Top Header (`.ui-header-glass`)**:
  - 56px (3.5rem) height, backdrop blur (12px), hairline bottom border.
  - Icon buttons (`.ui-icon-btn`): 32px x 32px rounded-md ghost buttons with responsive hover feedback.

### 3.2 Cards (`.ui-card`)
- Border-radius: `10px` or `12px` (outer containers).
- Background: `--sp-surface` (Carbon in dark mode, clean white in light mode).
- Border: `1px solid var(--sp-border)`.
- Interactive hover (`.ui-card-hover`): smooth border color transition to `--sp-border-strong` with minimal `translateY(-1px)`.

### 3.3 Buttons
- **Primary (`.ui-btn-primary`)**:
  - High-contrast solid fill: Deep ink `#0f172a` in light mode, high-contrast `#f8fafc` in dark mode (Linear style).
  - Radius: `6px`. Font weight: `500`.
  - Focused state: 2px outline with accent color.
- **Secondary (`.ui-btn-secondary`)**:
  - Surface muted background with 1px border.
  - Radius: `6px`.
- **Danger (`.ui-btn-danger`)**:
  - Ghost/tinted background with rose outline and text.
- **Table Row Actions (`.ui-row-action`)**:
  - Compact height (`32px`), inline icon + text or stacked layout (`.ui-row-action--stack`), muted by default, color on hover.

### 3.4 Form Inputs (`.ui-input`, `.ui-select-trigger`)
- Height: `36px` to `38px`.
- Radius: `6px`.
- Background: `--sp-surface-muted`.
- Focus: hairline border color shift to `--sp-accent` and subtle ring (`box-shadow: 0 0 0 3px var(--sp-accent-soft)`).

### 3.5 Status Badges & Chips (`.ui-badge`, `.ui-chip-*`)
- Height: `20px` to `22px`.
- Radius: `4px` (Linear badge standard).
- Visual format: Subtle background tint, 1px matching border, crisp foreground label, and an optional 5px indicator dot (`.ui-badge-dot` or pulsing dot `.ui-pulse-dot`).

### 3.6 Warp Console & Logs (`.ui-terminal`, `.ui-terminal-block`)
- Dedicated to log viewers, terminal traces, and realtime SSE runs.
- Always renders on a deeply dark, stepped canvas (`#090a0d` to `#121418`) regardless of app theme, ensuring developer clarity and readability.
- Hairline borders separating execution steps (`#1f232b`).
- Monospace font stack: `ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace`.
- Semantic line tones: emerald for successes, rose for exceptions, amber for timeouts/retries, muted gray for timestamps.

---

## 4. Do's and Don'ts

### Do
- Always use CSS variables (`var(--sp-*)`) or utility classes referencing them rather than ad-hoc arbitrary hex codes.
- Maintain equal vertical rhythm and 4px grid spacing throughout the interface.
- Keep hairline borders 1px and clean; rely on surface color steps for layered hierarchy.
- Preserve accessibility attributes (`role="dialog"`, `aria-label`, `tabindex`, keyboard traps) on all interactive overlays.

### Don't
- Do not introduce heavy drop shadows, neon multi-colored glows, or garish gradients.
- Do not override or alter Pinia stores, Vue Router paths, or API query parameters.
- Do not make the entire application a terminal—reserve the Warp aesthetic strictly for console and log surfaces.
- Do not remove or alter existing CSS class names (`.ui-card`, `.ui-btn-primary`, `.ui-badge`, etc.) to prevent breaking components or Vitest unit tests.
---

## 5. 新组件与设置子页开发约束 (Component & View Development Guidelines)

后续新增任何页面、设置子选项卡（如 Settings 中的新 Tab）、弹窗或子组件时，**必须统一遵从以下约束，杜绝散落硬编码颜色**：

### 5.1 容器与表面规范 (Containers & Surfaces)
- **卡片容器**：统一使用 `.ui-card` 类，禁止手写 `bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg`。
- **次级容器 / 嵌套背景**：统一使用 `bg-[var(--sp-surface-muted)]` 或 `bg-[var(--sp-surface-elevated)]`。
- **分割线与边框**：统一使用 `border-[var(--sp-border)]` 或 `border-[var(--sp-border-subtle)]`，禁止使用 `border-gray-100` / `border-gray-200` / `border-gray-700` / `border-gray-800` 等非语义 Tailwind 类。

### 5.2 文本与排版规范 (Typography)
- **主标题与正文**：统一使用 `text-[var(--sp-text)]`。
- **次级文本**：统一使用 `text-[var(--sp-text-secondary)]`。
- **说明文案 / 占位符 / 时间戳**：统一使用 `text-[var(--sp-text-muted)]`。
- **分区大写标签**：统一使用 `.ui-section-label`。

### 5.3 操作按钮规范 (Actions & Buttons)
- **主要操作**（保存、创建、确认）：统一使用 `.ui-btn-primary`。
- **次要操作**（取消、返回、刷新、重置）：统一使用 `.ui-btn-secondary`。
- **危险操作**（删除、清空、注销）：统一使用 `.ui-btn-danger`。
- **表格与卡片内行内操作**：统一使用 `.ui-row-action`（可选修饰符 `.ui-row-action--positive`、`.ui-row-action--danger`、`.ui-row-action--stack`）。
- **小图标按钮**：统一使用 `.ui-icon-btn`。

### 5.4 表单控件规范 (Form Controls)
- **文本输入与文本域**：统一使用 `.ui-input`。
- **下拉选择器**：统一使用 `<CustomSelect>` 组件或 `.ui-select-trigger` / `.ui-dropdown`。
- **复选框**：统一使用 `.ui-checkbox`。
- **开关切换**：统一使用 `.ui-switch` 与 `.ui-switch-knob`。
- **状态徽章**：统一使用 `.ui-badge`（搭配 `.ui-badge-success` / `.ui-badge-error` / `.ui-badge-warn` / `.ui-badge-neutral`）或 `.ui-chip-*`。

### 5.5 审查与自查 Checklist
在提交任何前端改动或 PR 前，运行以下自查：
1. 检查组件 template 是否包含未语义化的 `gray-`、`slate-`、`zinc-` 颜色类（特别是 `border-gray-*`、`bg-gray-*`、`text-gray-*`）；
2. 确认在浅色模式与深色模式下均已通过对比度测试，无双深或双浅对比度失真；
3. 运行 `npm run typecheck && npm test && npm run build` 确保无测试与构建回归。

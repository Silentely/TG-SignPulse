> This file is a visual reference source.
> It is NOT the authoritative TG-SignPulse design system.
> TG-SignPulse product requirements, existing interaction behavior,
> accessibility requirements, and `frontend/DESIGN.md` take precedence.

# Upstream Design References: Linear, SST, and Warp

This document normalizes and synthesizes the upstream visual systems sourced from Refero Styles into concrete reference models for the **TG-SignPulse** UI upgrade.

## Source URLs

- Primary Dark / Linear: https://styles.refero.design/style/90ce5883-bb24-4466-93f7-801cd617b0d1
- Runtime / Console / Warp: https://styles.refero.design/style/720c9806-2d70-4dd1-9a19-12efd71fc742
- Primary Light / SST: https://styles.refero.design/style/19f92be1-65ac-4432-a82b-0aa1e685d97d
- DESIGN.md for AI Agents: https://styles.refero.design/design-md/design-md-for-ai-agents
- Semantic Design Systems: https://styles.refero.design/design-md/semantic-design-systems
- Design System Context Files: https://styles.refero.design/ai-agents/design-system-context-files
- What is DESIGN.md: https://styles.refero.design/design-md/what-is-design-md
- DESIGN.md Resources: https://styles.refero.design/design-md/design-md-resources

---

## 1. Upstream Style Profiles

### 1.1 Linear — "Midnight Precision Instrument"
- **Refero ID**: `90ce5883-bb24-4466-93f7-801cd617b0d1`
- **Primary Role in TG-SignPulse**: Flagship foundation for **Dark Mode**, navigation layout, cards, hairline borders, micro-interactions, and typographic hierarchy.
- **Visual Essence**:
  - Extremely deep near-black backgrounds (`#08090a` void canvas, `#0f1011` carbon cards, `#161718` obsidian elevated surfaces).
  - Hairline borders (`#23252a` graphite, `#383b3f` smoke) defining structure rather than heavy drop shadows.
  - High typographic clarity: Paper `#ffffff` headers, Mist `#d0d6e0` body, Fog `#8a8f98` secondary, Ash `#62666d` tertiary metadata.
  - Compact geometric radii: `6px` for buttons and form inputs, `12px` for outer cards, `4px` for tags/badges, `9999px` for status pills.
  - Minimalist, distraction-free tool atmosphere with high data density.

### 1.2 SST — "Code Terminal in a Gallery"
- **Refero ID**: `19f92be1-65ac-4432-a82b-0aa1e685d97d`
- **Primary Role in TG-SignPulse**: Flagship foundation for **Light Mode**, offering crisp contrast without glare, paired with refined developer-tool elegance.
- **Visual Essence**:
  - Pristine paper canvas (`#ffffff`), soft lavender-tinted gray surface accents (`#e8e8f2`, `#f4f4f8`).
  - Cool off-black typographic voice: SST Ink (`#303055`) dark indigo-violet replacing abrasive pure black, paired with Slate (`#403f53`) body copy and Fog (`#767682`) metadata.
  - Hairline borders (`#e8e8f2`, `#dcdce6`), zero muddy or heavy drop shadows.
  - Flat, calm, structured layouts with 4px–8px border radii for controls and 12px for cards.
  - Retains a serious, high-craft developer tool aesthetic.

### 1.3 Warp — "Obsidian Command Center"
- **Refero ID**: `720c9806-2d70-4dd1-9a19-12efd71fc742`
- **Primary Role in TG-SignPulse**: Specialized visual language reserved strictly for **Logs & Console surfaces** (`FlowLogViewer`, terminal blocks, runtime execution streams, trace viewers, and status badges).
- **Visual Essence**:
  - Stepped obsidian surfaces: `#121212` canvas, `#1e1e1d` elevated shell, `#353534` raised terminal header/blocks, `#2f2f2f` interactive borders.
  - Monospaced typography with crisp contrast (`#faf9f6` primary, `#e3e2e0` secondary, `#afaeac` muted, `#868684` dimmed).
  - Terminal Sage (`#799c92`) and refined status accents for execution steps, timestamps, and structured output.
  - No decorative gradients or rounded bubble aesthetics—sharp, technical execution.

---

## 2. Normalized Token Reference Matrix

| Semantic Slot | Linear (Dark) | SST (Light) | Warp (Console/Logs) | TG-SignPulse Token Mapping |
| :--- | :--- | :--- | :--- | :--- |
| **Canvas Background** | `#08090a` (Void) | `#ffffff` (Paper) | `#121212` (Void) | `--sp-canvas` / `--sp-bg` |
| **Card / Surface Background** | `#0f1011` (Carbon) | `#ffffff` / `#f8f9fc` | `#1e1e1d` (Charcoal) | `--sp-surface` / `--sp-bg-elevated` |
| **Elevated / Popover Background** | `#161718` (Obsidian) | `#ffffff` (Paper) | `#353534` (Iron) | `--sp-surface-elevated` / `--sp-bg-elevated-2` |
| **Hairline Border (Subtle)** | `#23252a` (Graphite) | `#e8e8f2` (Mist) | `#2a2a29` (Border) | `--sp-border` |
| **Hairline Border (Strong/Hover)**| `#383b3f` (Smoke) | `#d4d4e2` (Slate hairline) | `#40403f` (Hover) | `--sp-border-strong` |
| **Primary Text** | `#ffffff` (Paper) | `#303055` (SST Ink) | `#faf9f6` (Warm White) | `--sp-text-primary` / `--sp-text` |
| **Secondary Text** | `#d0d6e0` (Mist) | `#403f53` (Slate) | `#e3e2e0` (Smoke) | `--sp-text-secondary` |
| **Muted Text / Metadata** | `#8a8f98` (Fog) | `#767682` (Fog) | `#afaeac` / `#868684` | `--sp-text-muted` |
| **Interactive Accent** | `#5e6ad2` (Linear Blue) | `#303055` / `#0ea5e9` | `#799c92` (Sage) | `--sp-accent` (Telegram Cyan `#0ea5e9` / `#38bdf8`) |
| **Success Status** | `#10b981` | `#047857` / `#10b981` | `#34d399` | `--sp-success` (`#10b981` / `#34d399`) |
| **Warning Status** | `#f59e0b` | `#b45309` / `#f59e0b` | `#fbbf24` | `--sp-warning` (`#f59e0b` / `#fbbf24`) |
| **Destructive / Danger** | `#f43f5e` | `#be123c` / `#e11d48` | `#fb7185` | `--sp-danger` (`#f43f5e` / `#fb7185`) |
| **Terminal/Console Surface** | `#0f1011` | `#121212` (Dark Console) | `#121212` / `#1e1e1d` | `--sp-terminal-bg`, `--sp-terminal-block` |

---

## 3. Product-Specific Synthesis Rules for TG-SignPulse

1. **Brand Identity Preservation**:
   - Linear uses acid-lime accents for some CTAs; SST uses text links with chevrons. **TG-SignPulse retains its Telegram-inspired cyan/sky blue (`#0ea5e9` light, `#38bdf8` dark) as the primary brand/interaction color.**
   - Statuses (success, warning, error, canceled) remain strictly semantic and immediately recognizable.

2. **Unified Dual-Theme Geometry**:
   - Light and Dark modes share identical spatial rhythm, padding scales, and border-radii (`6px` for inputs/buttons, `12px` for cards, `4px` for tags).
   - Light mode adopts SST's crisp ink contrast and hairline dividers without muddy shadows.
   - Dark mode adopts Linear's near-black obsidian depth and graphite hairline dividers.

3. **Domain Partitioning**:
   - General App Shell, navigation, accounts, tasks, settings, and login follow the **Linear Dark / SST Light** system.
   - Execution details, task output, logs view (`Logs.vue`), real-time run stream, and `FlowLogViewer.vue` follow the **Warp Console** system across both light and dark modes to maintain professional terminal integrity.

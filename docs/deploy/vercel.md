# Vercel 托管文档站

本仓库文档由 **VitePress** 构建，脚本在**仓库根目录** `package.json`。

## 推荐配置（Root Directory = 仓库根）

在 [Vercel Dashboard](https://vercel.com/new) 导入 GitHub 仓库后：

| 项 | 值 |
|----|-----|
| **Framework Preset** | Other |
| **Root Directory** | 留空（项目根） |
| **Install Command** | `npm install` |
| **Build Command** | `npm run docs:build` |
| **Output Directory** | `docs/.vitepress/dist` |
| **Node.js Version** | `22.x`（Project → Settings → General） |

根目录已提供 `vercel.json`，一般会自动读取上述构建命令与输出目录。

### 环境变量（可选）

| 变量 | 示例 | 说明 |
|------|------|------|
| `VITEPRESS_BASE` | `/` | 文档站点 base，Vercel 自定义域名/子域名请用 `/`（默认即可） |
| `VITEPRESS_SITE_URL` | `https://docs.example.com` | 用于 OG / 结构化数据的绝对站点 URL |
| `VITEPRESS_EDIT_BRANCH` | `dev` | 「在 GitHub 上编辑」链接指向的分支，默认 `main` |

在 Vercel → Project → Settings → Environment Variables 中添加（Production / Preview 按需勾选）。

> **不要**在 Vercel 上设置 `GITHUB_ACTIONS=true`，否则 `base` 会变成 GitHub Pages 的子路径（如 `/TG-SignPulse/`），在 Vercel 上会 404。

### cleanUrls

VitePress 开启了 `cleanUrls: true`，页面文件为 `guide/quick-start.html`，访问路径为 `/guide/quick-start`。  
`vercel.json` 中的 rewrite 会把无扩展名路径映射到对应 `.html`。

---

## 备选：Root Directory = `docs`

若你在 Vercel 里把 **Root Directory** 设为 `docs`：

1. 使用 `docs/vercel.json`（相对路径以 `docs/` 为根）
2. Dashboard 中应显示：
   - Install: `cd .. && npm install`
   - Build: `cd .. && npm run docs:build`
   - Output: `.vitepress/dist`

推荐仍用**仓库根**作为 Root Directory，路径更直观。

---

## 绑定自定义域名

1. Project → Settings → Domains  
2. 添加 `docs.your-domain.com`  
3. 按 Vercel 提示配置 DNS（CNAME 到 `cname.vercel-dns.com` 或 A 记录）  
4. 设置环境变量 `VITEPRESS_SITE_URL=https://docs.your-domain.com` 后 **Redeploy**

---

## 分支与预览

| 环境 | 说明 |
|------|------|
| Production | 默认跟踪 `main`（可在 Settings → Git 改成 `dev`） |
| Preview | 每个 PR / 推送非生产分支自动生成预览 URL |

若文档只在 `dev` 上维护，可在 Git 设置里将 Production Branch 设为 `dev`。

---

## 本地验证与线上一致

```bash
# 仓库根
npm install
npm run docs:build
npm run docs:preview
# 打开 http://127.0.0.1:4173
```

确认首页、侧栏、搜索、`/guide/quick-start` 等 clean URL 均可打开。

---

## 常见问题

### 样式丢失 / 资源 404

- 检查 `VITEPRESS_BASE` 是否误设为子路径  
- Output Directory 必须是 `docs/.vitepress/dist`（Root=仓库根时）

### 子页面刷新 404

- 确认已部署最新 `vercel.json` 的 rewrite  
- 或关闭 VitePress `cleanUrls`（不推荐）

### 构建失败：找不到 vitepress

- Root Directory 是否指错到 `frontend/`  
- Install Command 是否在含 `package.json`（根目录）的位置执行 `npm install`

### 与面板主站一起部署？

文档站与 Vue 面板是两套产物。常见做法：

- 文档：`docs.example.com` → 本 Vercel 项目  
- 面板：另一项目 / 自建 Docker  

不要把 `frontend` 的 Vite 输出和文档站混在同一个 Output Directory。

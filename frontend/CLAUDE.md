[根目录](../../CLAUDE.md) > **frontend**

# Frontend 模块

> Vue 3 + TypeScript + Vite 构建的 TG-SignPulse Web 管理面板。

## 变更记录 (Changelog)

| 日期 | 变更内容 |
|------|----------|
| 2026-06-30 | 初始化 frontend 模块 CLAUDE.md |
| 2026-06-30 | 补扫：3 个 Views 组件深度分析 |
| 2026-06-30 | 补扫：Composables 组合式函数 + 13 个 Components 组件详情 |

## 模块职责

提供 TG-SignPulse 的完整 Web 管理界面，包括：
- Dashboard 数据概览
- Telegram 账号管理（添加/编辑/删除/登录）
- 签到任务管理（CRUD/执行/历史查看）
- 日志查看（登录审计 + 任务历史）
- 系统设置（全局配置/AI 配置/TOTP/密码修改）

## 入口与启动

| 文件 | 职责 |
|------|------|
| `index.html` | HTML 入口，加载 `/src/main.ts` |
| `src/main.ts` | Vue 应用初始化（推断，未直接读取） |
| `src/App.vue` | 根组件，仅渲染 `<router-view>` + `<GlobalToast>` |
| `src/router/index.ts` | 路由定义，含 JWT 过期检查导航守卫 |

### 开发命令

```bash
npm run dev      # Vite 开发服务器 (端口 3000)
npm run build    # vue-tsc 类型检查 + vite build
npm run preview  # 预览构建产物
```

### Vite 配置要点 (`vite.config.ts`)

- 代理 `/api` 到 `http://127.0.0.1:8080`（含 WebSocket 支持）
- 集成 `vite-plugin-pwa`，支持离线缓存 API 响应

## 对外接口

### 路由定义

| 路径 | 名称 | 组件 | 职责 |
|------|------|------|------|
| `/` | - | Layout | 重定向到 dashboard |
| `/dashboard` | dashboard | Dashboard.vue | 数据概览面板 |
| `/accounts` | accounts | Accounts.vue | 账号管理 |
| `/tasks` | tasks | Tasks.vue | 签到任务管理 |
| `/logs` | logs | Logs.vue | 日志查看 |
| `/settings` | settings | Settings.vue | 系统设置 |
| `/login` | login | Login.vue | 登录页 |

### 导航守卫

- 无 token 且访问非登录页 → 跳转 `/login`
- 有 token 且访问登录页 → 跳转 `/dashboard`
- JWT 过期检查：解析 `payload.exp`，过期则清除 token

## 关键依赖与配置

### 核心依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| vue | ^3.5.34 | 框架核心 |
| vue-router | ^5.0.6 | 路由管理 |
| pinia | ^3.0.4 | 状态管理 |
| vue-i18n | ^9.14.4 | 国际化 |
| lucide-vue-next | ^1.0.0 | 图标库 |
| tailwindcss | ^4.3.0 | 样式框架 |

### 状态管理 (`src/stores/auth.ts`)

- `useAuthStore`: 管理 JWT token（localStorage 持久化）
- 提供 `setToken`, `clearToken`, `logout`, `isTokenExpired` 方法

### API 调用层 (`src/lib/api.ts`)

- 统一 `request<T>()` 函数，自动注入 Bearer token
- 401 响应自动清除 token 并跳转登录
- 导出所有 API 函数：auth、accounts、tasks、sign-tasks、config、logs、user

### 类型定义 (`src/lib/types.ts`)

- `Account`, `Task`, `TaskLog`, `TokenResponse` 核心业务类型

### Composables

| 文件 | 职责 |
|------|------|
| `useTheme.ts` | 暗黑/亮色主题切换 |
| `useToast.ts` | 全局消息提示 |
| `useI18n.ts` | 国际化包装器（兼容旧 API） |

## 组件结构

```
src/components/
├── GlobalToast.vue          # 全局消息提示（Teleport + TransitionGroup）
├── Modal.vue                # 通用模态框（header/content/footer 三 slot）
├── CustomSelect.vue         # 单选下拉（支持禁用项和缩进）
├── MultiSelect.vue          # 多选 + "全选"模式
├── DatePicker.vue           # 日历网格（中英文切换）
├── LanguageSwitch.vue       # zh-CN ↔ en-US 切换
├── accounts/
│   ├── AddAccountModal.vue  # 添加账号（验证码/QR/2FA 三种登录流程，7 个 API）
│   └── EditAccountModal.vue # 编辑账号（updateAccount）
├── settings/
│   └── UserProfileModal.vue # 用户资料（用户名/密码/TOTP 三 Tab，7 个 API）
└── tasks/
    ├── AddTaskModal.vue     # 添加任务（createSignTask）
    ├── EditTaskModal.vue    # 编辑任务（updateSignTask）
    ├── TaskLogsModal.vue    # 任务日志（WebSocket 实时 + HTTP 轮询降级）
    └── TaskForm.vue         # 任务表单（17 个 ref 自动 buildPayload，3 个 API）
```

### 跨组件共性问题

1. **Token 读取不一致**：所有业务组件直接 `localStorage.getItem`，绕过 Pinia authStore
2. **类型安全薄弱**：多处 `any`（account、task、payload）
3. **错误展示不统一**：未使用 `useToast`，统一用内联 `error` ref
4. **组件命名缺失**：均未显式定义 `name` 属性

## Views 组件详情（补扫 2026-06-30）

### Accounts.vue — 账号管理视图

| 维度 | 详情 |
|------|------|
| 子组件 | `AddAccountModal`, `EditAccountModal` |
| API 调用 | `listAccounts`, `deleteAccount`, `checkAccountsStatus` + 直接 fetch 头像 |
| 状态变量 | 8 个 ref（accounts, pageLoading, showAddModal, showEditModal 等） |
| 特色 | 头像异步加载（`URL.createObjectURL`）、状态映射（active/empty/error）、重新登录流程 |

### Logs.vue — 日志查看视图

| 维度 | 详情 |
|------|------|
| 子组件 | `Modal`, `CustomSelect`, `DatePicker` |
| API 调用 | `getTaskHistoryLogs`, `getTaskHistoryLogDetail`, `getLoginAuditLogs`, `listAccounts` |
| 状态变量 | 12 个 ref/computed |
| 特色 | 双 Tab（任务/登录）、前端筛选（任务名+状态）、详情弹窗含 flow_logs、i18n 翻译详情 |

### Settings.vue — 系统设置视图

| 维度 | 详情 |
|------|------|
| 子组件 | 无（纯表单页面） |
| API 调用 | 10 个（全局设置、TG 配置、AI 配置、导入导出、连接测试） |
| 状态变量 | 8 个 ref + 5 个独立 loading 状态 |
| 特色 | 数据导入导出（Blob + 临时 a 标签下载）、Toast 提示、AI 连接测试 |

### Dashboard.vue — 数据概览面板

| 维度 | 详情 |
|------|------|
| 子组件 | `Modal`（日志详情弹窗） |
| API 调用 | `listAccounts`, `listSignTasks`, `getRecentAccountLogs` |
| 状态变量 | 4 个 ref + 30 秒轮询定时器 |
| 特色 | 三个 API 独立 try-catch 隔离失败；日志按日期前端过滤 |

### Tasks.vue — 签到任务管理（高复杂度）

| 维度 | 详情 |
|------|------|
| 子组件 | `AddTaskModal`, `EditTaskModal`, `TaskLogsModal` |
| API 调用 | `listSignTasks`, `deleteSignTask`, `startSignTaskRun`, `listAccounts`, `toggleSignTaskEnabled` + 直接 fetch 头像 |
| 状态变量 | 11 个 ref + 路由 watch |
| 特色 | localStorage 头像缓存（data URL + 401 缓存 1 小时）；通配符 `*` 展开为全部账号；点击外部关闭下拉菜单 |

### Login.vue — 登录入口

| 维度 | 详情 |
|------|------|
| 子组件 | 无 |
| API 调用 | `login` |
| 状态变量 | 6 个 ref + authStore(Pinia) + i18n + theme |
| 特色 | 根据后端错误动态显示 TOTP 错误；authStore.setToken 持久化 |

## Composables（组合式函数）

| 文件 | 导出 | 引用数 | 职责 |
|------|------|--------|------|
| `useI18n.ts` | `useI18n()` | 多 | vue-i18n 适配层，兼容旧版 locale API |
| `useTheme.ts` | `useTheme()` | 2 | 暗黑/亮色主题切换 + View Transitions 动画 |
| `useToast.ts` | `useToast()`, `ToastItem` | 多 | 全局消息提示（success/error/info），自动消失 |

### ⚠️ 注意事项

1. **主任务路径**：前端一律走 `/api/sign-tasks` 与 `/api/batch/sign-tasks`，勿再接旧版 `/api/tasks`
2. **TaskForm**：支持多目标会话（共享动作序列）；批量操作在 Tasks 列表页
3. **Logs.vue 前端筛选**：任务名和状态过滤在前端完成，大数据量时可能有性能问题
4. **Settings**：支持配置 JSON 导出与完整 data 目录 tar.gz 备份
5. **类型**：`types.ts` 中 ORM 风格 `Task/TaskLog` 已标记 deprecated，新代码用 `SignTask`

## 数据模型

前端数据模型与后端 API 对齐，核心类型：

- **Account**: `{ id, account_name, api_id, api_hash, proxy, status, last_login_at, created_at, updated_at }`
- **Task**: `{ id, name, cron, enabled, account_id, last_run_at, created_at, updated_at }`
- **SignTask**: 扩展类型，含 `sign_at`, `chats`, `random_seconds`, `execution_mode` 等

## 测试与质量

- 前端暂无独立测试（依赖后端 API 集成测试）
- 类型安全由 `vue-tsc` 保障
- 构建命令含类型检查：`vue-tsc -b && vite build`

## 常见问题 (FAQ)

**Q: 前端如何与后端通信？**
A: 通过 `/api` 前缀的 REST API，Vite 开发模式下代理到 `http://127.0.0.1:8080`。

**Q: 登录态如何保持？**
A: JWT token 存储在 localStorage (`tg-signer-token`)，每次请求通过 `Authorization: Bearer` 头部发送。

## 相关文件清单

- `package.json` — 依赖与脚本
- `vite.config.ts` — Vite 配置（代理、PWA）
- `tailwind.config.js` — Tailwind 配置
- `tsconfig.json` / `tsconfig.app.json` / `tsconfig.node.json` — TypeScript 配置
- `index.html` — HTML 入口
- `src/main.ts` — 应用入口（推断）
- `src/App.vue` — 根组件
- `src/router/index.ts` — 路由定义
- `src/stores/auth.ts` — 认证状态
- `src/lib/api.ts` — API 调用层
- `src/lib/types.ts` — 类型定义

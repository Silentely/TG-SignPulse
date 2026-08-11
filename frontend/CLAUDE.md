[根目录](../CLAUDE.md) > **frontend**

# Frontend 模块

> Vue 3 + TypeScript + Vite 构建的 TG-SignPulse Web 管理面板。

## 变更记录 (Changelog)

> 完整变更记录已拆分至 [`CHANGELOG.md`](./CHANGELOG.md)，避免 CLAUDE.md 过长影响上下文。

## 模块职责

提供完整 Web 管理界面：

- Dashboard 数据概览
- Telegram 账号管理（添加/编辑/删除/登录/设备/官方消息）
- 签到任务管理（CRUD/克隆/执行/历史/命中）
- 日志查看（登录审计 + 任务历史）
- 系统设置（全局/AI/Bot/Telegram API/数据管理/关于/用户资料）

## 入口与启动

| 文件 | 职责 |
|------|------|
| `index.html` | HTML 入口 |
| `src/main.ts` | `createApp` + Pinia + Router + i18n |
| `src/App.vue` | 根组件：`<router-view>` + 全局 Toast/Confirm 等 |
| `src/router/index.ts` | 路由 + `resolveAuthRedirect` 导航守卫 |
| `src/i18n/index.ts` | vue-i18n 实例 |

### 开发命令

```bash
npm run dev          # Vite 开发服务器（端口 3000）
npm run build        # vue-tsc -b + vite build
npm run preview      # 预览构建产物
npm run typecheck    # 仅类型检查
npm test             # vitest run
npm run test:watch   # vitest 监听
```

### Vite 要点（`vite.config.ts`）

- 代理 `/api` → `http://127.0.0.1:8080`（含 WebSocket）
- `vite-plugin-pwa` 离线缓存

Node：`engines` 要求 `>=22.23.1 <23`（与根 `.nvmrc` 一致）。

## 对外接口（页面路由）

| 路径 | 名称 | 组件 | 职责 |
|------|------|------|------|
| `/` | — | Layout | 重定向 `/dashboard` |
| `/dashboard` | dashboard | Dashboard.vue | 概览 |
| `/accounts` | accounts | Accounts.vue | 账号 |
| `/tasks` | tasks | Tasks.vue | 签到任务 |
| `/logs` | logs | Logs.vue | 日志 |
| `/settings` | settings | Settings.vue | 设置（多子面板） |
| `/login` | login | Login.vue | 登录 |

### 导航守卫

- 无 token 访问业务页 → `/login`
- 有 token 访问登录页 → `/dashboard`
- JWT `exp` 过期 → 清 token（逻辑在 `lib/auth-guard.ts` + `stores/auth`）

## 关键依赖与配置

| 依赖 | 用途 |
|------|------|
| vue ^3.5 | 框架 |
| vue-router ^5 | 路由 |
| pinia ^3 | 状态 |
| vue-i18n ^9 | 国际化 |
| lucide-vue-next | 图标 |
| tailwindcss ^4 | 样式 |
| vite ^8 + vite-plugin-pwa | 构建与 PWA |
| vitest + @vue/test-utils | 单元测试 |

### 状态管理（`src/stores/`）

| Store | 职责 |
|-------|------|
| `auth.ts` | JWT（localStorage）、过期判断、logout |
| `accounts.ts` | 账号列表缓存与刷新 |
| `activeRuns.ts` | 进行中的签到运行状态 |

### API 层

- 入口：`src/lib/api.ts` → re-export `lib/api/index.ts`
- 域文件：`auth` / `accounts` / `sign-tasks` / `keyword-hits` / `config` / `settings` / `logs` / `ops`
- 核心：`lib/api/core.ts`（`request`、Bearer、401 跳转；**不**从 barrel 对外暴露工具函数）
- 类型：`lib/types.ts`（`SignTask` 为主；ORM 风格 `Task`/`TaskLog` 已 deprecated）

### Composables（15）

| 文件 | 职责 |
|------|------|
| `useI18n.ts` | i18n 包装（引用最多） |
| `useTheme.ts` | 明暗主题 + View Transitions |
| `useToast.ts` | 全局提示 |
| `useConfirm.ts` | 确认对话框 |
| `useTaskListRuntime.ts` / `useTaskListActions.ts` | Tasks 列表运行时与批量动作 |
| `useTaskRunStream.ts` / `useTaskHits.ts` | 运行流 / 关键词命中 |
| `useDashboardData.ts` | Dashboard 数据 |
| `useLogsPage.ts` | 日志页 |
| `useSettingsPage.ts` / `Save` / `Backup` / `VersionCheck` | 设置页拆分 |
| `useAccountBatchCheck.ts` | 账号批量状态检查 |

## 组件结构（32 个）

```
src/components/
├── 基础：Modal, ConfirmDialog, CustomSelect, MultiSelect, DatePicker,
│         GlobalToast, FlowLogViewer, PageRetry
├── accounts/：AddAccountModal, EditAccountModal, DeviceManagerModal, OfficialMessagesModal
├── tasks/：Add/Edit/CloneTaskModal, TaskForm(+Actions/Listen/Target),
│          TaskListCard, TaskListToolbar, TaskLogsModal(+History/Hits)
└── settings/：UserProfileModal, General/Ai/BotNotify/TelegramApi/
               DataManagement/AboutSettings, SettingsFieldHint
```

### 跨组件约定

1. **Token**：业务请求用 `useAuthStore().token`，勿散落读 localStorage
2. **错误提示**：列表/表单主路径 `useToast` / `notifyApiError`；弹窗可局部 `error` ref
3. **TaskForm payload**：`lib/task-form-payload.ts` 纯函数构造
4. **主任务 API**：只走 `/api/sign-tasks` 与 `/api/batch/sign-tasks`

## Views 要点

| 视图 | 要点 |
|------|------|
| Accounts | 见「Accounts 全链路」 |
| Tasks | 见「Tasks 全链路」 |
| Logs | 见「Logs / Dashboard / Settings」 |
| Settings | 见「Logs / Dashboard / Settings」 |
| Dashboard | 见「Logs / Dashboard / Settings」 |
| Login | TOTP 错误由后端语义驱动，避免脆弱文案匹配 |

## Accounts 全链路（`views/Accounts.vue`）

```text
Accounts.vue
  ├─ accountsStore.refreshAccounts（本页为单一事实来源，强制刷新）
  ├─ mapAccountInfoToUiItem + filterAccountsByQuery
  ├─ AvatarUrlCache + mapPool 并发拉头像（卸载 disposed 防 blob 泄漏）
  ├─ useAccountBatchCheck → 批量/单账号状态 Job 轮询
  └─ Add/Edit/Device/OfficialMessages Modal
```

### `useAccountBatchCheck`

| 能力 | 实现要点 |
|------|----------|
| 批量检测 | `startAccountStatusCheckJob` + `getAccountStatusCheckJob` 链式轮询 |
| 单账号 | `checkAccountsStatus` / 重检失败名单 |
| 进度 | `batchProgressPct`；结果写入 `batchResultMap` 并回写 UI `status` / `needs_relogin` |
| 取消 | `cancelAccountStatusCheckJob`；`onUnmounted` 停 poll |

其它：`deleteAccount` 确认删除；跳转 Tasks 可带 `?account=`；重登延时句柄卸载清理。

## Tasks 全链路（`views/Tasks.vue`）

页面本身偏薄：列表状态 + 深链 + 弹窗编排；重逻辑下沉 composable / 纯函数。

```text
Tasks.vue
  ├─ listSignTasks → mapSignTaskToListFields / withModeIcon
  ├─ useLatestResponseGuard（账号筛选竞态：丢弃过期响应）
  ├─ useTaskListRuntime  → activeRuns / 命中角标 / 头像 blob / 取消
  ├─ useTaskListActions  → 批量 / 克隆 / 启停 / 删除 / 单次 run
  ├─ TaskListToolbar + TaskListCard
  └─ Add/Edit/Clone/TaskLogs Modal
```

### `useTaskListRuntime`

| 能力 | 实现要点 |
|------|----------|
| 活跃 run | `useActiveRunsStore`：从任务 `active_run` seed + `refresh` 轮询；`ensurePolling` |
| 倒计时 | 有活跃 run 时 1s `nowTick`；用于冷却/等待文案 |
| 命中角标 | 监听模式任务 → `listKeywordHitGroups(group_by=task)` 链式轮询 |
| 头像 | `fetchChatAvatar` + 并发池；**blob URL 注册表**，列表替换/卸载统一 `revoke` |
| 取消 | `cancelSignTaskRun`；`cancelBusyKey` 防重复点 |
| 账号状态 | `listAccounts` 映射 invalid / needsRelogin 角标 |

### `useTaskListActions`

| 能力 | 实现要点 |
|------|----------|
| 账号解析 | 统一 `resolveTaskAccountName` / `resolveTaskRealAccounts`（跳过 `*` 通配） |
| 批量 | `batchSignTasks`：enable / disable / delete / run；delete 走 `useConfirm` |
| 克隆 | `cloneSignTask` + `CloneTaskModal`；**禁止把 `*` 当账号名提交** |
| 单次运行 | `startSignTaskRun`；多账号弹出 run 菜单；成功后 `openLogsAfterRun` |
| 启停/删除 | `toggleSignTaskEnabled` / `deleteSignTask` |

### 深链与筛选

| Query | 行为 |
|-------|------|
| `?account=` | 列表按账号过滤；`loadTasks` 带参；chip 可清除 |
| `?task=` | 写入搜索框 |
| `?tab=hits&task=` | 自动打开 `TaskLogsModal` 命中 Tab；关弹窗时去掉 `tab` 防反复弹出 |

筛选组合：`filterTasksByModeAndQuery`（全部 / 仅监听 / 仅定时 + 搜索）。

## Logs / Dashboard / Settings

### Logs（`useLogsPage` + 薄 `Logs.vue`）

| 能力 | 要点 |
|------|------|
| Tab | `tasks` 任务历史 / `login` 登录审计 |
| 任务筛选 | 账号、日期、成功/失败、`failure_category`；部分在前端再滤 |
| 竞态 | `useLatestResponseGuard` 分管列表 / 登录日志 / 详情 |
| 详情 | `getTaskHistoryLogDetail` → `FlowLogViewer` |
| 清空 | `clearTaskHistoryLogs` / `clearLoginAuditLogs` + `useConfirm` |
| 深链 | 可接 Dashboard 跳转的 `account` / `task` / `at` / `category` |

### Dashboard（`useDashboardData` + 薄 `Dashboard.vue`）

| 能力 | 要点 |
|------|------|
| 统计 | 活跃账号、任务总数、近成功/失败（多 API **隔离失败**，单项失败不拖垮整页） |
| 数据源 | `listSignTasks`、`getRecentAccountLogs`、`listScheduledJobs`、`listKeywordHits`、状态 Job |
| 实时 | 签到历史 **SSE**（`EventSource`）；断线指数退避重连（上限 30s）；`disposed` 停写 store |
| 活跃 run | 共享 `useActiveRunsStore` |
| 导航 | 日志条目 → Logs 页 query（账号/任务/时间/失败分类） |

### Settings（`useSettingsPage` + 子面板组件）

`Settings.vue` 只接线；逻辑在 composable + `lib/settings-form`。

| 子模块 | 职责 |
|--------|------|
| `useSettingsPage` | 表单状态、脏检查、分节 snap、加载全局/TG/AI/运行时/内存 |
| `useSettingsSave` | 分节/全部保存、Bot 测试、保活手动执行 |
| `useSettingsBackup` | 导出/导入、WebDAV 测连/列表/下载 |
| `useSettingsVersionCheck` | 关于页版本与检查更新 |
| 子组件 | General / TelegramApi / Ai / BotNotify / DataManagement / About |

脏状态：sticky 未保存横幅 + `dirtySectionLabels`；`onBeforeRouteLeave` 可拦截离开。

## 测试与质量

- `frontend/src/test/*.spec.ts`（约 40 个）：auth、api、composables、task-form、locales 一致性等
- `npm run typecheck` / `npm run build` 为发布前基线

## 常见问题 (FAQ)

**Q: 如何与后端通信？**  
A: `/api` REST + 部分 WebSocket；开发期 Vite 代理到 `127.0.0.1:8080`。

**Q: 登录态？**  
A: localStorage 中 JWT（如 `tg-signer-token`），`Authorization: Bearer`。

**Q: 旧 Task API？**  
A: 前端不得再调用 `/api/tasks`；类型上优先 `SignTask`。

## 相关文件清单

- `package.json` / `vite.config.ts` / `tailwind.config.js` / `tsconfig*.json`
- `src/main.ts`、`App.vue`、`router/index.ts`
- `src/stores/*`、`src/composables/*`、`src/components/**`、`src/views/*`
- `src/lib/api.ts`、`src/lib/api/*`、`src/lib/types.ts` 及各类纯函数工具
- `src/test/*` — vitest 用例

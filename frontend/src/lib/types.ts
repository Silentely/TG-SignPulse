/** @deprecated 旧版 ORM 账号类型；面板账号请用 api.ts 的 AccountInfo */
export type Account = {
  id: number;
  account_name: string;
  api_id: string;
  api_hash: string;
  proxy?: string | null;
  status: string;
  last_login_at?: string | null;
  created_at: string;
  updated_at: string;
};

/** @deprecated 旧版 ORM 任务类型；新任务请用 api.ts 的 SignTask */
export type Task = {
  id: number;
  name: string;
  cron: string;
  enabled: boolean;
  account_id: number;
  last_run_at?: string | null;
  created_at: string;
  updated_at: string;
};

/** @deprecated 旧版 ORM 任务日志；新日志请用 TaskHistoryLog / SignTaskHistoryItem */
export type TaskLog = {
  id: number;
  task_id: number;
  status: string;
  log_path?: string | null;
  output?: string | null;
  started_at: string;
  finished_at?: string | null;
};

export type TokenResponse = {
  access_token: string;
  token_type: string;
};

// ─── Dashboard 视图模型 ───
export interface DashboardLog {
  time: string;
  account: string;
  task: string;
  status: 'success' | 'error';
  text: string;
  /** ISO 时间，用于日志深链 */
  created_at?: string;
  /** 失败分类（SSE / 历史） */
  failure_category?: string;
}

// ─── Accounts 视图模型 ───
export type AccountUiStatus = 'active' | 'empty' | 'error';

export interface AccountUiItem {
  id: string;
  name: string;
  remark?: string | null;
  status: string;
  message: string;
  avatarUrl: string;
  avatarLoaded: boolean;
  raw: import('./api').AccountInfo;
}

// ─── Tasks 视图模型 ───
import type { Component } from 'vue';

export interface TaskUiItem {
  id: string;
  name: string;
  scheduleMode: string;
  targetStr: string;
  /** 目标会话总数（多 chat 时用于 +N 展示） */
  targetCount: number;
  /** 监听任务最近命中条数（可选，列表角标） */
  hitCount?: number;
  lastRunStr: string;
  lastRunSuccess: boolean | null;
  modeIcon: Component;
  isListenMode: boolean;
  enabled: boolean;
  chatAvatarUrl: string;
  chatName: string;
  raw: import('./api').SignTask;
}

// ─── Logs 视图模型 ───
export interface TaskLogUiItem {
  id: number;
  time: string;
  created_at: string;
  account: string;
  task: string;
  status: 'success' | 'error';
  text: string;
  flow_line_count: number;
  failure_category?: string;
}

export interface LoginLogUiItem {
  id: number;
  time: string;
  username: string;
  ip: string;
  status: 'success' | 'error';
  text: string;
}

// ─── TaskForm 动作类型 ───
export type TaskActionType =
  | 'send_text'
  | 'send_dice'
  | 'click_text_button'
  | 'vision_click'
  | 'calc_send'
  | 'vision_send'
  | 'calc_click'
  | 'bot_cmd'
  | 'delay';

export interface TaskActionItem {
  id: number;
  type: TaskActionType;
  value: string;
  aiPrompt: string;
  commandPrefix?: string;
}

// 后端原始 action 结构
export interface RawTaskAction {
  action: number;
  text?: string;
  dice?: string;
  delay?: number;
  ai_prompt?: string;
  bot_username?: string;
  command_prefix?: string;
  keywords?: string[];
  match_mode?: string;
  push_channel?: string;
  ignore_self?: boolean;
  active_time_start?: string;
  active_time_end?: string;
  forward_chat_id?: string;
  forward_message_thread_id?: string;
  bark_url?: string;
  custom_url?: string;
  server_chan_send_key?: string;
  continue_actions?: RawTaskAction[];
}

// 构建 API 请求体时的中间类型
export interface BuiltAction {
  action: number;
  text?: string;
  dice?: string;
  delay?: string;
  ai_prompt?: string;
  bot_username?: string;
  command_prefix?: string;
  keywords?: string[];
  match_mode?: string;
  push_channel?: string;
  ignore_self?: boolean;
  active_time_start?: string;
  active_time_end?: string;
  forward_chat_id?: string;
  forward_message_thread_id?: string;
  bark_url?: string;
  custom_url?: string;
  server_chan_send_key?: string;
  continue_actions?: BuiltAction[];
}

// ─── API 错误类型 ───
export interface ApiError extends Error {
  status?: number;
  code?: string;
}

// FastAPI 校验错误结构
export interface FastApiValidationError {
  loc: string[];
  msg: string;
  type: string;
}

// ─── 缓存条目类型 ───
export interface CacheEntry<T> {
  data: T;
  timestamp: number;
}

// ─── 工具函数 ───

/** 常见 API / 网络错误码 → 默认英文文案（无 i18n 时兜底） */
const API_ERROR_CODE_MESSAGES: Record<string, string> = {
  NETWORK_TIMEOUT: 'Request timed out',
  NETWORK_ERROR: 'Network error',
  ACCOUNT_SESSION_INVALID: 'Account session invalid, please re-login',
  TASK_LOG_NOT_FOUND: 'Task log not found',
  LOGIN_LOG_NOT_FOUND: 'Login log not found',
  INVALID_DATE_FILTER: 'Invalid date filter',
  LEGACY_TASKS_READONLY:
    'Legacy /api/tasks is read-only; use /api/sign-tasks',
  TASK_NOT_FOUND: 'Task not found',
  ACCOUNT_NOT_FOUND: 'Account not found',
  RATE_LIMITED: 'Too many requests, please try later',
  INVALID_USERNAME_OR_PASSWORD: 'Invalid username or password',
  TOTP_REQUIRED_OR_INVALID: '2FA code invalid or missing',
}

const CODE_LIKE = /^[A-Z][A-Z0-9_]{2,}$/

/**
 * 从未知错误提取稳定错误码（优先 ApiError.code，其次 message/detail 若为 CODE 形态）。
 */
export function getErrorCode(e: unknown): string | undefined {
  if (e && typeof e === 'object') {
    const record = e as Record<string, unknown>
    if (typeof record.code === 'string' && record.code.trim()) {
      return record.code.trim()
    }
  }
  if (e instanceof Error) {
    const msg = (e.message || '').trim()
    if (CODE_LIKE.test(msg)) return msg
  }
  if (typeof e === 'string') {
    const msg = e.trim()
    if (CODE_LIKE.test(msg)) return msg
  }
  if (e && typeof e === 'object') {
    const record = e as Record<string, unknown>
    if (typeof record.detail === 'string' && CODE_LIKE.test(record.detail.trim())) {
      return record.detail.trim()
    }
    if (typeof record.message === 'string' && CODE_LIKE.test(record.message.trim())) {
      return record.message.trim()
    }
  }
  return undefined
}

/**
 * 从未知错误值中提取可读消息。
 * 空字符串 / 空白消息回退为默认文案，避免 toast 出现空白提示。
 * 已知错误码映射为可读英文；UI 可用 getErrorCode + i18n 再覆盖。
 */
export function getErrorMessage(e: unknown, fallback = 'Unknown error'): string {
  const code = getErrorCode(e)
  if (code && API_ERROR_CODE_MESSAGES[code]) {
    return API_ERROR_CODE_MESSAGES[code]
  }

  // 410 旧接口只读：detail 常为长英文说明，压缩展示
  if (e && typeof e === 'object') {
    const status = (e as ApiError).status
    const msg =
      e instanceof Error
        ? (e.message || '').trim()
        : typeof (e as Record<string, unknown>).detail === 'string'
          ? String((e as Record<string, unknown>).detail).trim()
          : ''
    if (status === 410 || /legacy.*read-?only|APP_LEGACY_TASKS_READONLY/i.test(msg)) {
      return API_ERROR_CODE_MESSAGES.LEGACY_TASKS_READONLY
    }
  }

  if (e instanceof Error) {
    const msg = (e.message || '').trim()
    return msg || fallback
  }
  if (typeof e === 'string') {
    const msg = e.trim()
    return msg || fallback
  }
  if (e && typeof e === 'object') {
    const record = e as Record<string, unknown>
    if (typeof record.message === 'string' && record.message.trim()) {
      return record.message.trim()
    }
    if (typeof record.detail === 'string' && record.detail.trim()) {
      return record.detail.trim()
    }
    try {
      const serialized = JSON.stringify(e)
      return serialized && serialized !== '{}' ? serialized : fallback
    } catch {
      return fallback
    }
  }
  return fallback
}

/**
 * 结合 i18n 翻译函数解析错误文案。
 * `t` 应能解析 `apiErrors.<CODE>`；未命中时回退 getErrorMessage。
 */
export function getLocalizedErrorMessage(
  e: unknown,
  t: (key: string) => string,
  fallback = 'Unknown error',
): string {
  const code = getErrorCode(e)
  if (code) {
    const key = `apiErrors.${code}`
    const localized = t(key)
    if (localized && localized !== key) return localized
  }
  // 410 旧任务
  if (e && typeof e === 'object' && (e as ApiError).status === 410) {
    const key = 'apiErrors.LEGACY_TASKS_READONLY'
    const localized = t(key)
    if (localized && localized !== key) return localized
  }
  return getErrorMessage(e, fallback)
}



/** 旧版 ORM 账号/任务/任务日志类型已删除：面板统一使用 api.ts 的 AccountInfo / SignTask / SignTaskHistoryItem。
 *  保留 TokenResponse 及下方视图模型类型。 */

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
export interface AccountUiItem {
  id: string;
  name: string;
  remark?: string | null;
  status: string;
  message: string;
  avatarUrl: string;
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

// ─── 工具函数 ───

/** 常见 API / 网络错误码 → 默认英文文案（无 i18n 时兜底） */
const API_ERROR_CODE_MESSAGES: Record<string, string> = {
  NETWORK_TIMEOUT: 'Request timed out',
  NETWORK_ABORTED: 'Request cancelled',
  NETWORK_ERROR: 'Network error',
  ACCOUNT_SESSION_INVALID: 'Account session invalid, please re-login',
  TASK_LOG_NOT_FOUND: 'Task log not found',
  LOGIN_LOG_NOT_FOUND: 'Login log not found',
  INVALID_DATE_FILTER: 'Invalid date filter',
  LEGACY_TASKS_READONLY:
    'Legacy /api/tasks has been removed; use /api/sign-tasks',
  TASK_NOT_FOUND: 'Task not found',
  ACCOUNT_NOT_FOUND: 'Account not found',
  RATE_LIMITED: 'Too many requests, please try later',
  INVALID_USERNAME_OR_PASSWORD: 'Invalid username or password',
  TOTP_REQUIRED_OR_INVALID: '2FA code invalid or missing',
  WEBDAV_NOT_CONFIGURED: 'WebDAV is not configured',
  BACKUP_EMPTY: 'Nothing to back up',
  AI_KEY_DECRYPT_FAILED: 'API Key decrypt failed; check APP_SECRET_KEY and re-save',
  CONFIG_IMPORT_FAILED: 'Config import failed',
  CLEAR_LOGS_FAILED: 'Failed to clear logs',
  JOB_NOT_FOUND: 'Job not found',
  JOB_NOT_CANCELABLE: 'Job cannot be cancelled (missing or already finished)',
  SESSION_PASSWORD_NEEDED: 'Two-step verification enabled; enter the 2FA password',
  PASSWORD_HASH_INVALID: 'Incorrect 2FA password',
  TASK_EXPORT_FAILED: 'Failed to export task',
  TASK_CONFIG_INVALID: 'Invalid task config',
  TASK_IMPORT_FAILED: 'Failed to import task',
  CONFIG_EXPORT_FAILED: 'Failed to export configs',
  TASK_DELETE_FAILED: 'Failed to delete task',
  AI_CONFIG_READ_FAILED: 'Failed to read AI config',
  AI_CONFIG_SAVE_FAILED: 'Failed to save AI config',
  AI_CONFIG_DELETE_FAILED: 'Failed to delete AI config',
  SETTINGS_READ_FAILED: 'Failed to read settings',
  SETTINGS_SAVE_FAILED: 'Failed to save settings',
  TG_CONFIG_READ_FAILED: 'Failed to read Telegram config',
  TG_CONFIG_SAVE_FAILED: 'Failed to save Telegram config',
  TG_CONFIG_RESET_FAILED: 'Failed to reset Telegram config',
  API_CREDENTIALS_REQUIRED: 'api_id and api_hash are required',
  API_ID_INVALID: 'api_id must be a positive integer',
  DATA_DIR_NOT_WRITABLE: 'Data directory is not writable',
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
 * 超长错误文案截断：未知错误对象的 message/detail/序列化结果都可能
 * 携带长堆栈或嵌套字段，统一截断避免 toast 刷屏。
 */
const MAX_ERROR_MESSAGE_LENGTH = 200

function truncateErrorMessage(text: string): string {
  return text.length > MAX_ERROR_MESSAGE_LENGTH
    ? `${text.slice(0, MAX_ERROR_MESSAGE_LENGTH)}…`
    : text
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
    if (
      status === 410 ||
      /legacy.*(read-?only|removed)|APP_LEGACY_TASKS_READONLY|LEGACY_EVENTS_LOGS_REMOVED/i.test(
        msg,
      )
    ) {
      return API_ERROR_CODE_MESSAGES.LEGACY_TASKS_READONLY
    }
  }

  if (e instanceof Error) {
    const msg = (e.message || '').trim()
    return msg ? truncateErrorMessage(msg) : fallback
  }
  if (typeof e === 'string') {
    const msg = e.trim()
    return msg ? truncateErrorMessage(msg) : fallback
  }
  if (e && typeof e === 'object') {
    const record = e as Record<string, unknown>
    if (typeof record.message === 'string' && record.message.trim()) {
      return truncateErrorMessage(record.message.trim())
    }
    if (typeof record.detail === 'string' && record.detail.trim()) {
      return truncateErrorMessage(record.detail.trim())
    }
    if (Array.isArray(record.detail) && record.detail.length > 0) {
      const msgs = record.detail
        .map((item) => {
          if (!item || typeof item !== 'object') return String(item || '')
          const rec = item as Record<string, unknown>
          const loc = Array.isArray(rec.loc) && rec.loc.length > 0 ? String(rec.loc[rec.loc.length - 1]) : ''
          const prefix = loc ? (loc + ': ') : ''
          const msg = typeof rec.msg === 'string' ? rec.msg.trim() : JSON.stringify(rec)
          return prefix + msg
        })
        .filter(Boolean)
      if (msgs.length > 0) {
        return truncateErrorMessage(msgs.join('; '))
      }
    }
    try {
      const serialized = JSON.stringify(e)
      if (serialized && serialized !== '{}') {
        return truncateErrorMessage(serialized)
      }
      return fallback
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



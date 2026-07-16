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
  forward_chat_id?: string;
  forward_message_thread_id?: string;
  bark_url?: string;
  custom_url?: string;
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
  forward_chat_id?: string;
  forward_message_thread_id?: string;
  bark_url?: string;
  custom_url?: string;
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
/**
 * 从未知错误值中提取可读消息。
 * 空字符串 / 空白消息回退为默认文案，避免 toast 出现空白提示。
 */
export function getErrorMessage(e: unknown, fallback = 'Unknown error'): string {
  if (e instanceof Error) {
    const msg = (e.message || '').trim()
    // 网络层约定错误码，给出可读英文回退（UI 可再做 i18n 映射）
    if (msg === 'NETWORK_TIMEOUT') return 'Request timed out'
    if (msg === 'NETWORK_ERROR') return 'Network error'
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



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

// ─── API 错误工具 ───
export function getErrorMessage(e: unknown): string {
  if (e instanceof Error) return e.message;
  if (typeof e === 'string') return e;
  return '未知错误';
}


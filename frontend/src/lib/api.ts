import type { Task, TaskLog, TokenResponse } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE || "/api";

const toRecord = (headers?: HeadersInit): Record<string, string> => {
  if (!headers) return {};
  if (headers instanceof Headers) {
    return Object.fromEntries(headers.entries());
  }
  if (Array.isArray(headers)) {
    return Object.fromEntries(headers);
  }
  return headers as Record<string, string>;
};

async function request<T>(
  path: string,
  options: RequestInit = {},
  token?: string | null
): Promise<T> {
  const mergedHeaders: Record<string, string> = {
    ...toRecord(options.headers),
    "Content-Type": "application/json",
  };
  if (token) {
    mergedHeaders["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: mergedHeaders,
    cache: "no-store", // 禁用缓存，确保获取最新数据
  });
  if (!res.ok) {
    // 尝试解析 JSON 错误响应
    let errorMessage = "请求失败";
    let errorCode: string | undefined;
    try {
      const errorData = await res.json();
      if (errorData && typeof errorData === "object") {
        errorMessage = errorData.detail || errorData.message || JSON.stringify(errorData);
        errorCode = errorData.code;
      } else {
        errorMessage = JSON.stringify(errorData);
      }
    } catch {
      // 如果不是 JSON，使用文本
      try {
        errorMessage = await res.text() || "请求失败";
      } catch {
        // 忽略
      }
    }

    // 如果是认证失败 (401) 且请求携带了 token，清除 token 并跳转到登录页
    // 注意：登录相关请求（不带 token）不应触发跳转
    if (res.status === 401 && token) {
      if (typeof window !== "undefined") {
        const currentToken = localStorage.getItem("tg-signer-token");
        if (currentToken === token) {
          localStorage.removeItem("tg-signer-token");
          window.location.href = "/";
        }
      }
    }

    const err: any = new Error(errorMessage);
    err.status = res.status;
    if (errorCode) {
      err.code = errorCode;
    }
    throw err;
  }
  if (res.status === 204) {
    return {} as T;
  }
  return res.json();
}

// ============ 认证 ============

export const login = (payload: {
  username: string;
  password: string;
  totp_code?: string;
}) =>
  request<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const getMe = (token: string) =>
  request("/auth/me", {}, token);

export const resetTOTP = (payload: { username: string; password: string }) =>
  request<{ success: boolean; message: string }>("/auth/reset-totp", {
    method: "POST",
    body: JSON.stringify(payload),
  });


// ============ 账号管理（重构版）============

export interface LoginStartRequest {
  account_name: string;
  phone_number: string;
  proxy?: string;
}

export interface LoginStartResponse {
  phone_code_hash: string;
  phone_number: string;
  account_name: string;
  message: string;
}

export interface LoginVerifyRequest {
  account_name: string;
  phone_number: string;
  phone_code: string;
  phone_code_hash: string;
  password?: string;
  proxy?: string;
}

export interface LoginVerifyResponse {
  success: boolean;
  user_id?: number;
  first_name?: string;
  username?: string;
  message: string;
}

export interface QrLoginStartRequest {
  account_name: string;
  proxy?: string;
}

export interface QrLoginStartResponse {
  login_id: string;
  qr_uri: string;
  qr_image?: string | null;
  expires_at: string;
}

export interface QrLoginStatusResponse {
  status: string;
  expires_at?: string;
  message?: string;
  account?: AccountInfo | null;
  user_id?: number;
  first_name?: string;
  username?: string;
}

export interface QrLoginCancelResponse {
  success: boolean;
  message: string;
}

export interface QrLoginPasswordRequest {
  login_id: string;
  password: string;
}

export interface QrLoginPasswordResponse {
  success: boolean;
  message: string;
  account?: AccountInfo | null;
  user_id?: number;
  first_name?: string;
  username?: string;
}

export interface AccountInfo {
  name: string;
  session_file: string;
  exists: boolean;
  size: number;
  remark?: string | null;
  proxy?: string | null;
  status?: "connected" | "invalid" | "checking" | "error" | string;
  status_message?: string | null;
  status_code?: string | null;
  status_checked_at?: string | null;
  needs_relogin?: boolean;
}

export interface AccountStatusCheckRequest {
  account_names?: string[];
  timeout_seconds?: number;
}

export interface AccountStatusItem {
  account_name: string;
  ok: boolean;
  status: "connected" | "invalid" | "error" | "not_found" | string;
  message?: string;
  code?: string;
  checked_at?: string;
  needs_relogin?: boolean;
  user_id?: number;
}

export interface AccountStatusCheckResponse {
  results: AccountStatusItem[];
}

export const startAccountLogin = (token: string, data: LoginStartRequest) =>
  request<LoginStartResponse>("/accounts/login/start", {
    method: "POST",
    body: JSON.stringify(data),
  }, token);

export const verifyAccountLogin = (token: string, data: LoginVerifyRequest) =>
  request<LoginVerifyResponse>("/accounts/login/verify", {
    method: "POST",
    body: JSON.stringify(data),
  }, token);

export const listAccounts = (token: string) =>
  request<{ accounts: AccountInfo[]; total: number }>("/accounts", {}, token);

export const checkAccountsStatus = (token: string, data: AccountStatusCheckRequest) =>
  request<AccountStatusCheckResponse>("/accounts/status/check", {
    method: "POST",
    body: JSON.stringify(data),
  }, token);

export const deleteAccount = (token: string, accountName: string) =>
  request<{ success: boolean; message: string }>(`/accounts/${accountName}`, {
    method: "DELETE",
  }, token);

export const checkAccountExists = (token: string, accountName: string) =>
  request<{ exists: boolean; account_name: string }>(`/accounts/${accountName}/exists`, {}, token);

export const updateAccount = (
  token: string,
  accountName: string,
  data: {
    new_account_name?: string | null;
    remark?: string | null;
    proxy?: string | null;
  }
) =>
  request<{ success: boolean; message: string; account?: AccountInfo | null }>(`/accounts/${accountName}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  }, token);

export const startQrLogin = (token: string, data: QrLoginStartRequest) =>
  request<QrLoginStartResponse>("/accounts/qr/start", {
    method: "POST",
    body: JSON.stringify(data),
  }, token);

export const getQrLoginStatus = (token: string, loginId: string) =>
  request<QrLoginStatusResponse>(`/accounts/qr/status?login_id=${encodeURIComponent(loginId)}`, {}, token);

export const cancelQrLogin = (token: string, loginId: string) =>
  request<QrLoginCancelResponse>("/accounts/qr/cancel", {
    method: "POST",
    body: JSON.stringify({ login_id: loginId }),
  }, token);

export const submitQrPassword = (token: string, data: QrLoginPasswordRequest) =>
  request<QrLoginPasswordResponse>("/accounts/qr/password", {
    method: "POST",
    body: JSON.stringify(data),
  }, token);

// ============ 任务管理 ============

export const fetchTasks = (token: string) =>
  request<Task[]>("/tasks", {}, token);

export const createTask = (
  token: string,
  payload: { name: string; cron: string; account_id: number; enabled: boolean }
) =>
  request<Task>(
    "/tasks",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    token
  );

export const updateTask = (
  token: string,
  id: number,
  payload: Partial<{ name: string; cron: string; enabled: boolean; account_id: number }>
) =>
  request<Task>(
    `/tasks/${id}`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
    token
  );

export const deleteTask = (token: string, id: number) =>
  request(`/tasks/${id}`, { method: "DELETE" }, token);

export const runTask = (token: string, id: number) =>
  request<TaskLog>(`/tasks/${id}/run`, { method: "POST" }, token);

export const fetchTaskLogs = (token: string, id: number, limit = 50) =>
  request<TaskLog[]>(`/tasks/${id}/logs?limit=${limit}`, {}, token);

// ============ 配置管理 ============

export const listConfigTasks = (token: string) =>
  request<{ sign_tasks: string[]; monitor_tasks: string[]; total: number }>("/config/tasks", {}, token);

export const exportSignTask = async (token: string, taskName: string, accountName?: string) => {
  const params = new URLSearchParams();
  if (accountName) params.append("account_name", accountName);
  const url = `${API_BASE}/config/export/sign/${taskName}${params.toString() ? `?${params.toString()}` : ""}`;
  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    let errorMessage = "Export failed";
    try {
      const errorData = await res.json();
      errorMessage = errorData.detail || errorData.message || JSON.stringify(errorData);
    } catch {
      errorMessage = await res.text() || "Export failed";
    }
    throw new Error(errorMessage);
  }
  return res.text();
};

export const importSignTask = (
  token: string,
  configJson: string,
  taskName?: string,
  accountName?: string
) =>
  request<{ success: boolean; task_name: string; message: string }>("/config/import/sign", {
    method: "POST",
    body: JSON.stringify({ config_json: configJson, task_name: taskName, account_name: accountName }),
  }, token);

export const exportAllConfigs = async (token: string) => {
  const res = await fetch(`${API_BASE}/config/export/all`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    let errorMessage = "Export failed";
    try {
      const errorData = await res.json();
      errorMessage = errorData.detail || errorData.message || JSON.stringify(errorData);
    } catch {
      errorMessage = await res.text() || "Export failed";
    }
    throw new Error(errorMessage);
  }
  return res.text();
};

export const importAllConfigs = (token: string, configJson: string, overwrite = false) =>
  request<{
    signs_imported: number;
    signs_skipped: number;
    monitors_imported: number;
    monitors_skipped: number;
    settings_imported: number;
    errors: string[];
    message: string;
  }>("/config/import/all", {
    method: "POST",
    body: JSON.stringify({ config_json: configJson, overwrite }),
  }, token);

export const deleteSignConfig = (token: string, taskName: string, accountName?: string) => {
  const params = new URLSearchParams();
  if (accountName) params.append("account_name", accountName);
  const url = `/config/sign/${taskName}${params.toString() ? `?${params.toString()}` : ""}`;
  return request<{ success: boolean; message: string }>(url, {
    method: "DELETE",
  }, token);
};

// ============ 用户设置 ============

export const changePassword = (token: string, oldPassword: string, newPassword: string) =>
  request<{ success: boolean; message: string }>("/user/password", {
    method: "PUT",
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
  }, token);

export const getTOTPStatus = (token: string) =>
  request<{ enabled: boolean; secret?: string }>("/user/totp/status", {}, token);

export const setupTOTP = (token: string) =>
  request<{ enabled: boolean; secret: string }>("/user/totp/setup", {
    method: "POST",
  }, token);

export const fetchTOTPQRCode = async (token: string) => {
  const res = await fetch(`${API_BASE}/user/totp/qrcode`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) {
    let errorMessage = "QR code fetch failed";
    try {
      const errorData = await res.json();
      errorMessage = errorData.detail || errorData.message || JSON.stringify(errorData);
    } catch {
      errorMessage = await res.text() || errorMessage;
    }
    throw new Error(errorMessage);
  }
  const blob = await res.blob();
  return window.URL.createObjectURL(blob);
};

export const enableTOTP = (token: string, totpCode: string) =>
  request<{ success: boolean; message: string }>("/user/totp/enable", {
    method: "POST",
    body: JSON.stringify({ totp_code: totpCode }),
  }, token);

export const disableTOTP = (token: string, totpCode: string) =>
  request<{ success: boolean; message: string }>("/user/totp/disable", {
    method: "POST",
    body: JSON.stringify({ totp_code: totpCode }),
  }, token);

export const changeUsername = (token: string, newUsername: string, password: string) =>
  request<ChangeUsernameResponse>("/user/username", {
    method: "PUT",
    body: JSON.stringify({ new_username: newUsername, password: password }),
  }, token);

// ============ AI 配置 ============

export interface AIConfig {
  has_config: boolean;
  base_url?: string;
  model?: string;
  api_key_masked?: string;
}

export interface ChangeUsernameResponse {
  success: boolean;
  message: string;
  access_token?: string;
}

export interface AITestResult {
  success: boolean;
  message: string;
  model_used?: string;
}

export const getAIConfig = (token: string) =>
  request<AIConfig>("/config/ai", {}, token);

export const saveAIConfig = (
  token: string,
  config: { api_key?: string; base_url?: string; model?: string }
) =>
  request<{ success: boolean; message: string }>("/config/ai", {
    method: "POST",
    body: JSON.stringify(config),
  }, token);

export const testAIConnection = (token: string) =>
  request<AITestResult>("/config/ai/test", {
    method: "POST",
  }, token);

export const deleteAIConfig = (token: string) =>
  request<{ success: boolean; message: string }>("/config/ai", {
    method: "DELETE",
  }, token);

// ============ 全局设置 ============

export interface GlobalSettings {
  sign_interval?: number | null;  // null 表示随机 1-120 秒
  log_retention_days?: number;    // 日志保留天数，默认 7
  data_dir?: string | null;
  global_proxy?: string | null;
  telegram_bot_notify_enabled?: boolean;
  telegram_bot_login_notify_enabled?: boolean;
  telegram_bot_task_failure_enabled?: boolean;
  telegram_bot_token?: string | null;
  telegram_bot_chat_id?: string | null;
  telegram_bot_message_thread_id?: number | null;
}

export const getGlobalSettings = (token: string) =>
  request<GlobalSettings>("/config/settings", {}, token);

export const saveGlobalSettings = (token: string, settings: GlobalSettings) =>
  request<{ success: boolean; message: string }>("/config/settings", {
    method: "POST",
    body: JSON.stringify(settings),
  }, token);

// ============ Telegram API 配置 ============

export interface TelegramConfig {
  api_id: string;
  api_hash: string;
  is_custom: boolean;
  default_api_id: string;
  default_api_hash: string;
}

export const getTelegramConfig = (token: string) =>
  request<TelegramConfig>("/config/telegram", {}, token);

export const saveTelegramConfig = (
  token: string,
  config: { api_id: string; api_hash: string }
) =>
  request<{ success: boolean; message: string }>("/config/telegram", {
    method: "POST",
    body: JSON.stringify(config),
  }, token);

export const resetTelegramConfig = (token: string) =>
  request<{ success: boolean; message: string }>("/config/telegram", {
    method: "DELETE",
  }, token);

// ============ 账号日志 ============

export interface AccountLog {
  id: number;
  account_name: string;
  task_name: string;
  message: string;
  summary?: string;
  bot_message?: string;
  success: boolean;
  created_at: string;
}

export const getAccountLogs = (token: string, accountName: string, limit: number = 100) =>
  request<AccountLog[]>(`/accounts/${accountName}/logs?limit=${limit}`, {}, token);

export const getRecentAccountLogs = (token: string, limit: number = 50) =>
  request<AccountLog[]>(`/accounts/logs/recent?limit=${limit}`, {}, token);

export const clearRecentAccountLogs = (token: string) =>
  request<{ success: boolean; cleared: number; message: string; code?: string }>(
    "/accounts/logs/clear",
    { method: "POST" },
    token
  );

export const clearAccountLogs = (token: string, accountName: string) =>
  request<{ success: boolean; cleared: number; message: string; code?: string }>(
    `/accounts/${accountName}/logs/clear`,
    { method: "POST" },
    token
  );

export const exportAccountLogs = async (token: string, accountName: string) => {
  const res = await fetch(`${API_BASE}/accounts/${accountName}/logs/export`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
  if (!res.ok) throw new Error("Export failed");
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `logs_${accountName}.txt`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
};

// ============ 控制台日志 ============

export interface LoginAuditLog {
  id: number;
  username: string;
  ip_address?: string | null;
  user_agent?: string | null;
  detail?: string | null;
  success: boolean;
  created_at: string;
}

export interface TaskHistoryLog {
  id: number;
  account_name: string;
  task_name: string;
  message: string;
  summary?: string | null;
  bot_message?: string | null;
  success: boolean;
  created_at: string;
  flow_line_count: number;
}

export interface TaskHistoryLogDetail extends TaskHistoryLog {
  flow_logs: string[];
  flow_truncated: boolean;
  last_target_message?: string | null;
}

export const getLoginAuditLogs = (
  token: string,
  options?: {
    limit?: number;
    date?: string;
  }
) => {
  const params = new URLSearchParams();
  if (options?.limit) params.append("limit", String(options.limit));
  if (options?.date) params.append("date", options.date);
  const query = params.toString();
  return request<LoginAuditLog[]>(`/logs/login${query ? `?${query}` : ""}`, {}, token);
};

export const clearLoginAuditLogs = (token: string) =>
  request<{ success: boolean; cleared: number; message: string }>(
    "/logs/login/clear",
    { method: "POST" },
    token
  );

export const deleteLoginAuditLog = (token: string, logId: number) =>
  request<{ success: boolean; message: string }>(
    `/logs/login/${logId}`,
    { method: "DELETE" },
    token
  );

export const getTaskHistoryLogs = (
  token: string,
  options?: {
    limit?: number;
    account_name?: string;
    date?: string;
  }
) => {
  const params = new URLSearchParams();
  if (options?.limit) params.append("limit", String(options.limit));
  if (options?.account_name) params.append("account_name", options.account_name);
  if (options?.date) params.append("date", options.date);
  const query = params.toString();
  return request<TaskHistoryLog[]>(`/logs/tasks${query ? `?${query}` : ""}`, {}, token);
};

export const getTaskHistoryLogDetail = (
  token: string,
  options: {
    account_name: string;
    task_name: string;
    created_at: string;
  }
) => {
  const params = new URLSearchParams();
  params.append("account_name", options.account_name);
  params.append("task_name", options.task_name);
  params.append("created_at", options.created_at);
  return request<TaskHistoryLogDetail>(`/logs/tasks/item?${params.toString()}`, {}, token);
};

export const clearTaskHistoryLogs = (token: string) =>
  request<{ success: boolean; cleared: number; message: string }>(
    "/logs/tasks/clear",
    { method: "POST" },
    token
  );

export const deleteTaskHistoryLog = (
  token: string,
  options: {
    account_name: string;
    task_name: string;
    created_at: string;
  }
) => {
  const params = new URLSearchParams();
  params.append("account_name", options.account_name);
  params.append("task_name", options.task_name);
  params.append("created_at", options.created_at);
  return request<{ success: boolean; message: string }>(
    `/logs/tasks/item?${params.toString()}`,
    { method: "DELETE" },
    token
  );
};

// ============ 签到任务管理 ============

export interface SignTaskChat {
  chat_id: number;
  name: string;
  actions: any[];
  delete_after?: number;
  action_interval: number;
  message_thread_id?: number;
}

export interface LastRunInfo {
  time: string;
  success: boolean;
  message?: string;
}

export interface SignTask {
  name: string;
  account_name: string;
  account_names?: string[];
  sign_at: string;
  chats: SignTaskChat[];
  random_seconds: number;
  sign_interval: number;
  enabled: boolean;
  last_run?: LastRunInfo | null;
  execution_mode?: "fixed" | "range" | "listen";
  range_start?: string;
  range_end?: string;
  notify_on_failure?: boolean;
  task_group_id?: string;
  last_run_account_name?: string;
}

export interface CreateSignTaskRequest {
  name: string;
  account_name: string;
  account_names?: string[];
  sign_at: string;
  chats: SignTaskChat[];
  random_seconds?: number;
  sign_interval?: number;
  execution_mode?: "fixed" | "range" | "listen";
  range_start?: string;
  range_end?: string;
  notify_on_failure?: boolean;
}

export interface UpdateSignTaskRequest {
  account_names?: string[];
  sign_at?: string;
  chats?: SignTaskChat[];
  random_seconds?: number;
  sign_interval?: number;
  execution_mode?: "fixed" | "range" | "listen";
  range_start?: string;
  range_end?: string;
  notify_on_failure?: boolean;
}

export interface ChatInfo {
  id: number;
  title?: string;
  username?: string;
  type: string;
  first_name?: string;
}

export interface ChatSearchResponse {
  items: ChatInfo[];
  total: number;
  limit: number;
  offset: number;
}

export async function listSignTasks(token: string, accountName?: string, forceRefresh?: boolean): Promise<SignTask[]> {
  const params = new URLSearchParams();
  if (accountName) params.append('account_name', accountName);
  if (forceRefresh) params.append('force_refresh', 'true');
  if (!accountName) params.append('aggregate', 'true');
  const url = `/sign-tasks${params.toString() ? `?${params.toString()}` : ''}`;
  return request<SignTask[]>(url, {}, token);
}

export const getSignTask = (token: string, name: string, accountName?: string) => {
  const params = new URLSearchParams();
  if (accountName) params.append("account_name", accountName);
  const url = `/sign-tasks/${encodeURIComponent(name)}${params.toString() ? `?${params.toString()}` : ""}`;
  return request<SignTask>(url, {}, token);
};

export const createSignTask = (token: string, data: CreateSignTaskRequest) =>
  request<SignTask>("/sign-tasks", {
    method: "POST",
    body: JSON.stringify(data),
  }, token);

export const updateSignTask = (token: string, name: string, data: UpdateSignTaskRequest, accountName?: string) =>
  request<SignTask>(`/sign-tasks/${encodeURIComponent(name)}${accountName ? `?account_name=${encodeURIComponent(accountName)}` : ''}`, {
    method: "PUT",
    body: JSON.stringify(data),
  }, token);

export const deleteSignTask = (token: string, name: string, accountName?: string) =>
  request<{ ok: boolean }>(`/sign-tasks/${encodeURIComponent(name)}${accountName ? `?account_name=${encodeURIComponent(accountName)}` : ''}`, {
    method: "DELETE",
  }, token);

export const runSignTask = (token: string, name: string, accountName: string) =>
  request<{ success: boolean; output: string; error: string }>(`/sign-tasks/${encodeURIComponent(name)}/run?account_name=${encodeURIComponent(accountName)}`, {
    method: "POST",
  }, token);

export interface SignTaskRunStatus {
  run_id: string;
  state: "idle" | "stale" | "running" | "finished" | string;
  success?: boolean | null;
  error?: string;
  output?: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export const startSignTaskRun = (token: string, name: string, accountName: string) =>
  request<SignTaskRunStatus>(`/sign-tasks/${encodeURIComponent(name)}/run/start?account_name=${encodeURIComponent(accountName)}`, {
    method: "POST",
  }, token);

export const getSignTaskRunStatus = (
  token: string,
  name: string,
  accountName: string,
  runId?: string
) => {
  const params = new URLSearchParams();
  params.append("account_name", accountName);
  if (runId) params.append("run_id", runId);
  return request<SignTaskRunStatus>(
    `/sign-tasks/${encodeURIComponent(name)}/run/status?${params.toString()}`,
    {},
    token
  );
};

export const getAccountChats = (token: string, accountName: string, forceRefresh?: boolean) =>
  request<ChatInfo[]>(`/sign-tasks/chats/${encodeURIComponent(accountName)}${forceRefresh ? '?force_refresh=true' : ''}`, {}, token);

export const searchAccountChats = (
  token: string,
  accountName: string,
  query: string,
  limit: number = 50,
  offset: number = 0
) => {
  const params = new URLSearchParams();
  params.append("q", query);
  params.append("limit", String(limit));
  params.append("offset", String(offset));
  return request<ChatSearchResponse>(`/sign-tasks/chats/${encodeURIComponent(accountName)}/search?${params.toString()}`, {}, token);
};

export const getSignTaskLogs = (token: string, name: string, accountName?: string) => {
    const params = new URLSearchParams();
    if (accountName) params.append("account_name", accountName);
    const url = `/sign-tasks/${encodeURIComponent(name)}/logs${params.toString() ? `?${params.toString()}` : ""}`;
    return request<string[]>(url, {}, token);
};

export interface SignTaskHistoryItem {
  time: string;
  success: boolean;
  message?: string;
  flow_logs?: string[];
  flow_truncated?: boolean;
  flow_line_count?: number;
  account_name?: string;
  last_target_message?: string;
}

export const getSignTaskHistory = (
  token: string,
  name: string,
  accountName?: string,
  limit: number = 20
) => {
  const params = new URLSearchParams();
  if (accountName) params.append("account_name", accountName);
  params.append("limit", String(limit));
  return request<SignTaskHistoryItem[]>(
    `/sign-tasks/${encodeURIComponent(name)}/history?${params.toString()}`,
    {},
    token
  );
};

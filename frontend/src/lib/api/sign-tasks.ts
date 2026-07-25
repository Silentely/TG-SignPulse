/**
 * 签到任务管理 API：CRUD、执行、运行状态、历史、批量操作、聊天查询。
 */
import { request } from "./core";
import type { RawTaskAction } from "../types";

export interface SignTaskChat {
  chat_id: number;
  name: string;
  actions: RawTaskAction[];
  delete_after?: number;
  action_interval: number;
  message_thread_id?: number;
  sender_filter?: string;
  source_account?: string;
}

export interface LastRunInfo {
  time: string;
  success: boolean;
  message?: string;
}

export interface ActiveRunSummary {
  run_id?: string;
  state?: string;
  phase?: string | null;
  phase_detail?: string;
  account_name?: string;
  task_name?: string;
  started_at?: string | null;
  wait_seconds?: number | null;
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
  notify_on_success?: boolean;
  task_group_id?: string;
  last_run_account_name?: string;
  retry_count?: number;
  active_run?: ActiveRunSummary | null;
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
  notify_on_success?: boolean;
  retry_count?: number;
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
  notify_on_success?: boolean;
  retry_count?: number;
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

export const toggleSignTaskEnabled = (token: string, name: string, accountName?: string) =>
  request<SignTask>(`/sign-tasks/${encodeURIComponent(name)}/toggle-enabled${accountName ? `?account_name=${encodeURIComponent(accountName)}` : ''}`, {
    method: "PATCH",
  }, token);

export const runSignTask = (token: string, name: string, accountName: string) =>
  request<{ success: boolean; output: string; error: string }>(`/sign-tasks/${encodeURIComponent(name)}/run?account_name=${encodeURIComponent(accountName)}`, {
    method: "POST",
  }, token);

export interface SignTaskRunStatus {
  run_id: string;
  state: "idle" | "stale" | "running" | "finished" | "cancelled" | "timeout" | string;
  success?: boolean | null;
  error?: string;
  output?: string;
  started_at?: string | null;
  finished_at?: string | null;
  phase?: string | null;
  phase_detail?: string;
  wait_seconds?: number | null;
  account_name?: string;
  task_name?: string;
  failure_category?: string | null;
  timeout_seconds?: number | null;
  retry_count_effective?: number | null;
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

export const listActiveSignTaskRuns = (token: string) =>
  request<{ runs: ActiveRunSummary[] }>(`/sign-tasks/runs/active`, {}, token);

export const cancelSignTaskRun = (
  token: string,
  name: string,
  accountName: string,
  runId?: string
) => {
  const params = new URLSearchParams();
  params.append("account_name", accountName);
  if (runId) params.append("run_id", runId);
  return request<{
    ok: boolean;
    cancelled: boolean;
    error?: string;
    status?: SignTaskRunStatus;
  }>(
    `/sign-tasks/${encodeURIComponent(name)}/run/cancel?${params.toString()}`,
    { method: "POST" },
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
  // 兼容模板中的可选访问
  created_at?: string;
  bot_message?: string;
  summary?: string;
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

// ─── 新版签到任务批量操作 ───

export type SignBatchAction = "enable" | "disable" | "delete" | "run";

export interface SignBatchTaskItem {
  name: string;
  account_name?: string | null;
}

export interface SignBatchTaskResult {
  name: string;
  account_name: string;
  success: boolean;
  message: string;
}

export interface SignBatchTaskResponse {
  total: number;
  success_count: number;
  fail_count: number;
  results: SignBatchTaskResult[];
}

export const batchSignTasks = (
  token: string,
  tasks: SignBatchTaskItem[],
  action: SignBatchAction,
  runAccountName?: string
) =>
  request<SignBatchTaskResponse>(
    "/batch/sign-tasks",
    {
      method: "POST",
      body: JSON.stringify({
        tasks,
        action,
        run_account_name: runAccountName || null,
      }),
    },
    token
  );

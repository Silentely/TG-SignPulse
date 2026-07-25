/**
 * 控制台日志 API：登录审计日志、任务历史日志（含详情、清理、删除）。
 */
import { request } from "./core";

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
  failure_category?: string | null;
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

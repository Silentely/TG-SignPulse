/**
 * 配置管理 API：任务配置列表、单任务/全量导入导出、预览、删除。
 */
import { API_BASE, request } from "./core";
import type { SignTask } from "./sign-tasks";

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

export type ImportAllConfigsResult = {
  signs_imported: number;
  signs_skipped: number;
  monitors_imported: number;
  monitors_skipped: number;
  settings_imported: number;
  settings_skipped?: number;
  errors: string[];
  warnings?: string[];
  message: string;
};

export const importAllConfigs = (token: string, configJson: string, overwrite = false) =>
  request<ImportAllConfigsResult>("/config/import/all", {
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

export interface ImportPreviewResult {
  signs_count: number;
  monitors_count: number;
  settings_keys: string[];
  conflicts: string[];
  errors: string[];
}

export const importConfigPreview = (token: string, configJson: string) =>
  request<ImportPreviewResult>("/config/import-preview", {
    method: "POST",
    body: JSON.stringify({ config_json: configJson }),
  }, token);

export const cloneSignTask = (
  token: string,
  taskName: string,
  newName: string,
  accountName?: string,
) =>
  request<SignTask>(`/sign-tasks/${encodeURIComponent(taskName)}/clone`, {
    method: "POST",
    body: JSON.stringify({
      new_name: newName,
      account_name: accountName || undefined,
    }),
  }, token);

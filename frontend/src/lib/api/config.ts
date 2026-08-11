/**
 * 配置管理 API：任务配置列表、单任务/全量导入导出、预览、删除。
 */
import { LONG_TIMEOUT_MS, request, requestText } from "./core";
import type { SignTask } from "./sign-tasks";

export const exportAllConfigs = (token: string) =>
  requestText("/config/export/all", {}, token, LONG_TIMEOUT_MS);

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
  request<ImportAllConfigsResult>(
    "/config/import/all",
    {
      method: "POST",
      body: JSON.stringify({ config_json: configJson, overwrite }),
    },
    token,
    LONG_TIMEOUT_MS,
  );

export interface ImportPreviewResult {
  signs_count: number;
  monitors_count: number;
  settings_keys: string[];
  conflicts: string[];
  errors: string[];
}

export const importConfigPreview = (token: string, configJson: string) =>
  request<ImportPreviewResult>(
    "/config/import-preview",
    {
      method: "POST",
      body: JSON.stringify({ config_json: configJson }),
    },
    token,
    LONG_TIMEOUT_MS,
  );

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

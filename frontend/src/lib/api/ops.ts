/**
 * 运维 Ops API：调度预览、备份导出、WebDAV 备份、内存统计、版本检查、运行时状态。
 */
import { fetchWithAuth, LONG_TIMEOUT_MS, request } from "./core";

export interface ScheduledJob {
  id: string;
  name: string;
  next_run_time?: string | null;
  trigger: string;
  kind: "sign" | "legacy_db" | "system" | "other" | string;
}

export interface ScheduledJobsResponse {
  jobs: ScheduledJob[];
  total: number;
  timezone: string;
}

export const listScheduledJobs = (token: string) =>
  request<ScheduledJobsResponse>("/ops/scheduled-jobs", {}, token);

export interface BackupStatus {
  data_dir: string;
  writable: boolean;
  size_bytes: number;
  size_human: string;
  entries: Array<{
    path: string;
    exists: boolean;
    size_bytes: number;
    size_human: string;
  }>;
  recommended_paths: string[];
  notes?: string[];
  restore_hint?: string;
  webdav_configured?: boolean;
  auto_backup_enabled?: boolean;
  local_auto_backups?: Array<{
    name: string;
    size_bytes: number;
    size_human: string;
    mtime: string;
  }>;
}

export const getBackupStatus = (token: string) =>
  request<BackupStatus>("/ops/backup/status", {}, token);

/** 完整备份：优先上传 WebDAV；未配置时服务端可能回退为下载流 */
export async function exportBackupArchive(token: string): Promise<{
  mode: "webdav" | "download";
  message?: string;
  remote_url?: string;
  filename?: string;
}> {
  // 压缩与 WebDAV 上传可能超过普通 API 的 30 秒窗口；与服务端 httpx 600s 对齐。
  const res = await fetchWithAuth(
    "/ops/backup/export",
    {},
    { method: "POST" },
    token,
    LONG_TIMEOUT_MS,
  );
  const ct = (res.headers.get("Content-Type") || "").toLowerCase();
  if (ct.includes("application/json")) {
    const data = await res.json();
    if (data && data.success === false) {
      throw new Error(
        String(data.message || data.detail || "WebDAV backup upload failed"),
      );
    }
    return {
      mode: "webdav",
      message: data.message,
      remote_url: data.remote_url,
      filename: data.filename,
    };
  }
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") || "";
  const match = /filename="?([^"]+)"?/.exec(cd);
  const filename = match?.[1] || `tg-signpulse-backup-${Date.now()}.tar.gz`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return { mode: "download", filename };
}

export const testWebdavBackup = (token: string) =>
  request<{ success: boolean; message: string; status_code?: number }>(
    "/ops/backup/webdav/test",
    { method: "POST" },
    token,
  );

export interface WebDavRemoteFile {
  name: string;
  href?: string;
  size_bytes?: number | null;
  mtime?: string | null;
}

export const listWebdavBackupFiles = (token: string) =>
  request<{
    success: boolean;
    files: WebDavRemoteFile[];
    message?: string;
    status_code?: number;
  }>("/ops/backup/webdav/files", {}, token);

/** 从 WebDAV 下载指定备份包到浏览器 */
export async function downloadWebdavBackup(
  token: string,
  name: string,
): Promise<{ filename: string }> {
  const qs = new URLSearchParams({ name });
  const res = await fetchWithAuth(
    `/ops/backup/webdav/download?${qs.toString()}`,
    {},
    {},
    token,
    LONG_TIMEOUT_MS,
  );
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") || "";
  const match = /filename="?([^"]+)"?/.exec(cd);
  const filename = match?.[1] || name;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return { filename };
}

export interface MemoryStatsResponse {
  available: boolean;
  stats: Record<string, unknown>;
}

export const getMemoryStats = (token: string) =>
  request<MemoryStatsResponse>("/ops/memory", {}, token);

export interface RuntimeStatus {
  ready: boolean;
  scheduler_lock_held: boolean;
  legacy_tasks_writable: boolean;
  database_is_sqlite: boolean;
  monitor_shard: string;
  monitor_allowlist: string;
}

export const getRuntimeStatus = (token: string) =>
  request<RuntimeStatus>("/ops/runtime-status", {}, token);

export interface AppVersionInfo {
  version: string;
  git_sha: string;
  git_branch: string;
  build_time: string;
  app_name: string;
  python: string;
  update_check_enabled: boolean;
}

export interface UpdateCheckInfo {
  enabled: boolean;
  latest_version: string | null;
  latest_url: string | null;
  update_available: boolean;
  checked_at: string | null;
  error: string | null;
  source: string;
  cached: boolean;
}

export interface AppVersionCheckResult extends AppVersionInfo {
  update_check: UpdateCheckInfo;
}

export const getAppVersion = (token: string) =>
  request<AppVersionInfo>("/ops/version", {}, token);

export const checkAppVersion = (token: string, force = false) =>
  request<AppVersionCheckResult>(
    `/ops/version/check?force=${force ? "true" : "false"}`,
    { method: "POST" },
    token,
  );

/**
 * 运维 Ops API：调度预览、备份导出、WebDAV / 对象存储备份、内存统计、版本检查、运行时状态。
 */
import {
  createRequestAbort,
  fetchWithAuth,
  LONG_TIMEOUT_MS,
  MEDIUM_TIMEOUT_MS,
  request,
} from "./core";
import { downloadBlob, normalizeNetworkError } from "../download";
export interface ScheduledJob {
  id: string;
  name: string;
  next_run_time?: string | null;
  trigger: string;
  kind: "sign" | "legacy_db" | "system" | "other" | string;
  execution_mode?: string | null;
  range_start?: string | null;
  range_end?: string | null;
  task_name?: string | null;
  account_name?: string | null;
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
  /** 对象存储（S3/R2/MinIO）是否已配置且启用 */
  s3_configured?: boolean;
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

/** 完整备份：优先上传 WebDAV，其次对象存储；均未配置时服务端回退为下载流 */
export async function exportBackupArchive(token: string): Promise<{
  mode: "webdav" | "s3" | "download";
  message?: string;
  remote_url?: string;
  filename?: string;
}> {
  // 整段墙钟超时：打包 + 上传/下载 body 均受 LONG_TIMEOUT 约束
  const abort = createRequestAbort(LONG_TIMEOUT_MS, null);
  try {
    const res = await fetchWithAuth(
      "/ops/backup/export",
      {},
      { method: "POST", signal: abort.signal },
      token,
      null,
    );
    const ct = (res.headers.get("Content-Type") || "").toLowerCase();
    if (ct.includes("application/json")) {
      const data = await res.json();
      if (data && data.success === false) {
        throw new Error(
          String(data.message || data.detail || "Backup upload failed"),
        );
      }
      // mode 由服务端按「WebDAV → 对象存储」优先级返回，前端据此提示
      const mode: "webdav" | "s3" =
        data.mode === "s3" ? "s3" : "webdav";
      return {
        mode,
        message: data.message,
        remote_url: data.remote_url,
        filename: data.filename,
      };
    }
    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") || "";
    const match = /filename="?([^"]+)"?/.exec(cd);
    const filename = match?.[1] || `tg-signpulse-backup-${Date.now()}.tar.gz`;
    downloadBlob(blob, filename);
    return { mode: "download", filename };
  } catch (e: unknown) {
    throw normalizeNetworkError(e, abort);
  } finally {
    abort.cleanup();
  }
}

export const testWebdavBackup = (token: string) =>
  request<{ success: boolean; message: string; status_code?: number }>(
    "/ops/backup/webdav/test",
    { method: "POST" },
    token,
    MEDIUM_TIMEOUT_MS,
  );

/** 远端备份包条目：WebDAV 与对象存储列表返回同构字段 */
export interface RemoteBackupFile {
  name: string;
  href?: string;
  size_bytes?: number | null;
  mtime?: string | null;
}

export const listWebdavBackupFiles = (token: string) =>
  request<{
    success: boolean;
    files: RemoteBackupFile[];
    message?: string;
    status_code?: number;
  }>("/ops/backup/webdav/files", {}, token, MEDIUM_TIMEOUT_MS);

/** 从 WebDAV 下载指定备份包到浏览器 */
export async function downloadWebdavBackup(
  token: string,
  name: string,
): Promise<{ filename: string }> {
  const qs = new URLSearchParams({ name });
  const abort = createRequestAbort(LONG_TIMEOUT_MS, null);
  try {
    const res = await fetchWithAuth(
      `/ops/backup/webdav/download?${qs.toString()}`,
      {},
      { signal: abort.signal },
      token,
      null,
    );
    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") || "";
    const match = /filename="?([^"]+)"?/.exec(cd);
    const filename = match?.[1] || name;
    downloadBlob(blob, filename);
    return { filename };
  } catch (e: unknown) {
    throw normalizeNetworkError(e, abort);
  } finally {
    abort.cleanup();
  }
}

export const testS3Backup = (token: string) =>
  request<{ success: boolean; message: string; status_code?: number }>(
    "/ops/backup/s3/test",
    { method: "POST" },
    token,
    MEDIUM_TIMEOUT_MS,
  );

export const listS3BackupFiles = (token: string) =>
  request<{
    success: boolean;
    files: RemoteBackupFile[];
    message?: string;
    status_code?: number;
  }>("/ops/backup/s3/files", {}, token, MEDIUM_TIMEOUT_MS);

/** 从对象存储下载指定备份包到浏览器 */
export async function downloadS3Backup(
  token: string,
  name: string,
): Promise<{ filename: string }> {
  const qs = new URLSearchParams({ name });
  const abort = createRequestAbort(LONG_TIMEOUT_MS, null);
  try {
    const res = await fetchWithAuth(
      `/ops/backup/s3/download?${qs.toString()}`,
      {},
      { signal: abort.signal },
      token,
      null,
    );
    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") || "";
    const match = /filename="?([^"]+)"?/.exec(cd);
    const filename = match?.[1] || name;
    downloadBlob(blob, filename);
    return { filename };
  } catch (e: unknown) {
    throw normalizeNetworkError(e, abort);
  } finally {
    abort.cleanup();
  }
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
  /** 旧 /api/tasks 路由已移除 */
  legacy_tasks_removed?: boolean;
  database_is_sqlite: boolean;
  monitor_shard: string;
  monitor_allowlist: string;
  scheduler_role?: string;
  uptime_seconds?: number;
}

export const getRuntimeStatus = (token: string) =>
  request<RuntimeStatus>("/ops/runtime-status", {}, token);

export interface AppVersionInfo {
  version: string;
  git_sha: string;
  git_branch: string;
  build_time: string;
  app_name: string;
  os_platform?: string;
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

export interface DailyTrendItem {
  date: string;
  total: number;
  success: number;
  failed: number;
  success_rate: number;
}

export interface TrendsResponse {
  days: number;
  total_runs: number;
  total_success: number;
  total_failed: number;
  overall_success_rate: number;
  trends: DailyTrendItem[];
  categories: Record<string, number>;
}

export const getHistoryTrends = (token: string, days = 7) =>
  request<TrendsResponse>(`/ops/trends?days=${days}`, {}, token);

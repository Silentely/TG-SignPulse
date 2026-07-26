/**
 * 关键词命中记录 API：列表、分组、导出 URL、清理。
 */
import { LONG_TIMEOUT_MS, request, requestBlob } from "./core";

/** 关键词命中记录 */
export interface KeywordHitRecord {
  id: string;
  time: string;
  account_name: string;
  task_name: string;
  chat_id?: number | string | null;
  chat_title?: string;
  keyword?: string;
  keywords?: string[];
  message_id?: number | null;
  message_text?: string;
  sender?: string;
  url?: string;
  push_channel?: string;
  message_thread_id?: number | null;
}

export interface KeywordHitsListResponse {
  total: number;
  offset: number;
  limit: number;
  items: KeywordHitRecord[];
}

export interface KeywordHitGroup {
  key: string;
  label: string;
  count: number;
  items: KeywordHitRecord[];
}

export const listKeywordHits = (
  token: string,
  params?: {
    account_name?: string;
    task_name?: string;
    limit?: number;
    offset?: number;
  },
) => {
  const q = new URLSearchParams();
  if (params?.account_name) q.set("account_name", params.account_name);
  if (params?.task_name) q.set("task_name", params.task_name);
  if (params?.limit != null) q.set("limit", String(params.limit));
  if (params?.offset != null) q.set("offset", String(params.offset));
  const qs = q.toString();
  return request<KeywordHitsListResponse>(
    `/keyword-hits${qs ? `?${qs}` : ""}`,
    {},
    token,
  );
};

export const listKeywordHitGroups = (
  token: string,
  params?: {
    account_name?: string;
    task_name?: string;
    group_by?: "task" | "account" | "chat";
    limit_per_group?: number;
  },
) => {
  const q = new URLSearchParams();
  if (params?.account_name) q.set("account_name", params.account_name);
  if (params?.task_name) q.set("task_name", params.task_name);
  if (params?.group_by) q.set("group_by", params.group_by);
  if (params?.limit_per_group != null) {
    q.set("limit_per_group", String(params.limit_per_group));
  }
  const qs = q.toString();
  return request<{ group_by: string; groups: KeywordHitGroup[] }>(
    `/keyword-hits/groups${qs ? `?${qs}` : ""}`,
    {},
    token,
  );
};

export const exportKeywordHitsUrl = (params?: {
  account_name?: string;
  task_name?: string;
  limit?: number;
}) => {
  const q = new URLSearchParams();
  if (params?.account_name) q.set("account_name", params.account_name);
  if (params?.task_name) q.set("task_name", params.task_name);
  if (params?.limit != null) q.set("limit", String(params.limit));
  const qs = q.toString();
  return `/api/keyword-hits/export${qs ? `?${qs}` : ""}`;
};

export const clearKeywordHits = (
  token: string,
  params?: { account_name?: string; task_name?: string },
) => {
  const q = new URLSearchParams();
  if (params?.account_name) q.set("account_name", params.account_name);
  if (params?.task_name) q.set("task_name", params.task_name);
  const qs = q.toString();
  return request<{ ok: boolean; deleted: number }>(
    `/keyword-hits${qs ? `?${qs}` : ""}`,
    { method: "DELETE" },
    token,
  );
};

/**
 * 下载关键词命中记录导出（CSV）。复用 requestBlob 的鉴权与 401 跳转；
 * exportKeywordHitsUrl 仅构造 URL，本函数实际拉取二进制内容。
 */
export const exportKeywordHitsBlob = (
  token: string,
  params?: { account_name?: string; task_name?: string; limit?: number },
) => {
  const q = new URLSearchParams();
  if (params?.account_name) q.set("account_name", params.account_name);
  if (params?.task_name) q.set("task_name", params.task_name);
  if (params?.limit != null) q.set("limit", String(params.limit));
  const qs = q.toString();
  return requestBlob(
    `/keyword-hits/export${qs ? `?${qs}` : ""}`,
    {},
    token,
    LONG_TIMEOUT_MS,
  );
};

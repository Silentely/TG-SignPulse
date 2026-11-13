/**
 * 自动化素材数据字典池 (Data Dictionary) API。
 */
import { request } from "./core";

export interface DataDictMeta {
  name: string;
  count: number;
  remark?: string;
  updated_at?: string;
}

export interface DataDictDetail {
  name: string;
  entries: string[];
  cursor?: number;
  remark?: string;
  updated_at?: string;
}

export interface BuiltinDataDictMeta {
  name: string;
  count: number;
  remark?: string;
  entries: string[];
  exists: boolean;
}

export interface SaveDataDictPayload {
  name: string;
  entries: string[];
  remark?: string;
}

export interface SampleEntryResponse {
  name: string;
  entry: string;
  mode: "random" | "round_robin";
}

export interface DataDictUsage {
  count: number;
  last_used?: string;
}

export interface DataDictStats {
  dicts: Record<string, DataDictUsage>;
  total: number;
  dict_count: number;
}

/** 获取各数据字典的使用统计 */
export const getDataDictStats = (token: string) => {
  return request<DataDictStats>("/data-dict/stats", {}, token);
};

/** 获取全部数据字典列表 */
export const listDataDicts = (token: string) => {
  return request<DataDictMeta[]>("/data-dict", {}, token);
};

/** 获取内置数据字典预设列表 */
export const listBuiltinDataDicts = (token: string) => {
  return request<BuiltinDataDictMeta[]>("/data-dict-presets", {}, token);
};

/** 引用一条内置数据字典写入用户数据目录 */
export const createDataDictFromBuiltin = (token: string, name: string) => {
  return request<DataDictDetail>(
    `/data-dict-presets/${encodeURIComponent(name)}`,
    { method: "POST" },
    token,
  );
};

/** 获取指定数据字典详情 */
export const getDataDict = (token: string, name: string) => {
  return request<DataDictDetail>(`/data-dict/${encodeURIComponent(name)}`, {}, token);
};

/** 保存（创建或更新）数据字典 */
export const saveDataDict = (token: string, payload: SaveDataDictPayload) => {
  return request<{ ok: boolean }>(
    "/data-dict",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    token,
  );
};

/** 删除指定数据字典 */
export const deleteDataDict = (token: string, name: string) => {
  return request<{ ok: boolean }>(
    `/data-dict/${encodeURIComponent(name)}`,
    {
      method: "DELETE",
    },
    token,
  );
};

/** 抽取词条样本预览 */
export const sampleDataDictEntry = (
  token: string,
  name: string,
  mode: "random" | "round_robin" = "random",
) => {
  return request<SampleEntryResponse>(
    `/data-dict/${encodeURIComponent(name)}/sample?mode=${encodeURIComponent(mode)}`,
    {},
    token,
  );
};

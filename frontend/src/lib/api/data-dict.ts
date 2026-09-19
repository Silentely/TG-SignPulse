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

/** 获取全部数据字典列表 */
export const listDataDicts = (token: string) => {
  return request<DataDictMeta[]>("/data-dict", {}, token);
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

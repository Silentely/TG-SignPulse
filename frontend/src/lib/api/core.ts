/**
 * API 请求核心：request<T> 与请求辅助。
 * 所有域文件从本模块导入 request / API_BASE。
 */
import { useAuthStore } from "../../stores/auth";
import type { ApiError, FastApiValidationError } from "../types";

export const API_BASE = import.meta.env.VITE_API_BASE || "/api";

export const toRecord = (headers?: HeadersInit): Record<string, string> => {
  if (!headers) return {};
  if (headers instanceof Headers) {
    return Object.fromEntries(headers.entries());
  }
  if (Array.isArray(headers)) {
    return Object.fromEntries(headers);
  }
  return headers as Record<string, string>;
};

/** 默认请求超时（毫秒），可用 options.signal 覆盖/组合 */
export const DEFAULT_TIMEOUT_MS = 30_000;

export async function request<T>(
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

  const controller = new AbortController();
  const externalSignal = options.signal;
  const onExternalAbort = () => controller.abort();
  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort();
    } else {
      externalSignal.addEventListener("abort", onExternalAbort, { once: true });
    }
  }
  const timeoutId = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT_MS);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: mergedHeaders,
      cache: "no-store", // 禁用缓存，确保获取最新数据
      signal: controller.signal,
    });
  } catch (e: unknown) {
    clearTimeout(timeoutId);
    if (externalSignal) {
      externalSignal.removeEventListener("abort", onExternalAbort);
    }
    const isAbort =
      (e instanceof DOMException && e.name === "AbortError") ||
      (e instanceof Error && e.name === "AbortError");
    const err = new Error(isAbort ? "NETWORK_TIMEOUT" : "NETWORK_ERROR") as ApiError;
    err.status = 0;
    err.code = isAbort ? "NETWORK_TIMEOUT" : "NETWORK_ERROR";
    throw err;
  } finally {
    clearTimeout(timeoutId);
    if (externalSignal) {
      externalSignal.removeEventListener("abort", onExternalAbort);
    }
  }

  if (!res.ok) {
    // 尝试解析 JSON 错误响应；默认消息中性，避免中英文混用硬编码
    let errorMessage = `Request failed (${res.status})`;
    let errorCode: string | undefined;
    try {
      const errorData = await res.json();
      if (errorData && typeof errorData === "object") {
        const detail = errorData.detail;
        if (typeof detail === "string" && detail.trim()) {
          errorMessage = detail.trim();
        } else if (Array.isArray(detail)) {
          // FastAPI validation error format: [{loc, msg, type}]
          const msgs = (detail as FastApiValidationError[])
            .map((d) => (d.msg || "").trim() || JSON.stringify(d))
            .filter(Boolean);
          if (msgs.length) errorMessage = msgs.join("; ");
        } else if (detail && typeof detail === "object") {
          errorMessage = JSON.stringify(detail);
        } else if (typeof errorData.message === "string" && errorData.message.trim()) {
          errorMessage = errorData.message.trim();
        } else {
          errorMessage = JSON.stringify(errorData);
        }
        errorCode = errorData.code;
      } else if (errorData != null) {
        errorMessage = JSON.stringify(errorData);
      }
    } catch {
      // 如果不是 JSON，使用文本
      try {
        const text = (await res.text()).trim();
        if (text) errorMessage = text;
      } catch {
        // 忽略
      }
    }

    // 如果是认证失败 (401) 且请求携带了 token，清除 token 并跳转到登录页
    // 注意：登录相关请求（不带 token）不应触发跳转
    if (res.status === 401 && token) {
      if (typeof window !== "undefined") {
        const authStore = useAuthStore();
        if (authStore.token === token) {
          authStore.clearToken();
          window.location.href = "/";
        }
      }
    }

    const err = new Error(errorMessage) as ApiError;
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

/**
 * 下载二进制响应（如头像、CSV 导出）。复用 request 的鉴权、超时、401 跳转
 * 与错误解析逻辑，成功时返回 Blob 而非 JSON。
 */
export async function requestBlob(
  path: string,
  options: RequestInit = {},
  token?: string | null
): Promise<Blob> {
  const mergedHeaders: Record<string, string> = {
    ...toRecord(options.headers),
  };
  if (token) {
    mergedHeaders["Authorization"] = `Bearer ${token}`;
  }

  const controller = new AbortController();
  const externalSignal = options.signal;
  const onExternalAbort = () => controller.abort();
  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort();
    } else {
      externalSignal.addEventListener("abort", onExternalAbort, { once: true });
    }
  }
  const timeoutId = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT_MS);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: mergedHeaders,
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (e: unknown) {
    clearTimeout(timeoutId);
    if (externalSignal) {
      externalSignal.removeEventListener("abort", onExternalAbort);
    }
    const isAbort =
      (e instanceof DOMException && e.name === "AbortError") ||
      (e instanceof Error && e.name === "AbortError");
    const err = new Error(isAbort ? "NETWORK_TIMEOUT" : "NETWORK_ERROR") as ApiError;
    err.status = 0;
    err.code = isAbort ? "NETWORK_TIMEOUT" : "NETWORK_ERROR";
    throw err;
  } finally {
    clearTimeout(timeoutId);
    if (externalSignal) {
      externalSignal.removeEventListener("abort", onExternalAbort);
    }
  }

  if (!res.ok) {
    let errorMessage = `Request failed (${res.status})`;
    try {
      const errorData = await res.json();
      if (errorData && typeof errorData === "object") {
        const detail = errorData.detail;
        if (typeof detail === "string" && detail.trim()) {
          errorMessage = detail.trim();
        } else if (Array.isArray(detail)) {
          const msgs = (detail as FastApiValidationError[])
            .map((d) => (d.msg || "").trim() || JSON.stringify(d))
            .filter(Boolean);
          if (msgs.length) errorMessage = msgs.join("; ");
        } else if (detail && typeof detail === "object") {
          errorMessage = JSON.stringify(detail);
        } else if (typeof errorData.message === "string" && errorData.message.trim()) {
          errorMessage = errorData.message.trim();
        } else {
          errorMessage = JSON.stringify(errorData);
        }
      }
    } catch {
      // 非 JSON 错误响应，使用文本兜底
      try {
        const text = (await res.text()).trim();
        if (text) errorMessage = text;
      } catch {
        // 忽略
      }
    }

    if (res.status === 401 && token) {
      if (typeof window !== "undefined") {
        const authStore = useAuthStore();
        if (authStore.token === token) {
          authStore.clearToken();
          window.location.href = "/";
        }
      }
    }

    const err = new Error(errorMessage) as ApiError;
    err.status = res.status;
    throw err;
  }
  return res.blob();
}

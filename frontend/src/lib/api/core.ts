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

/** 默认请求超时（毫秒）；长耗时请求可显式传 null 关闭固定超时。 */
export const DEFAULT_TIMEOUT_MS = 30_000;

/**
 * 内部请求基元：鉴权 header、超时、abort 传播、!res.ok 错误解析与 401 跳转。
 * 成功时返回原始 Response，由调用方决定 JSON/Blob 解析方式。
 */
export async function fetchWithAuth(
  path: string,
  headers: Record<string, string>,
  options: RequestInit,
  token?: string | null,
  timeoutMs: number | null = DEFAULT_TIMEOUT_MS,
): Promise<Response> {
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
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
  const timeoutId = timeoutMs === null
    ? null
    : setTimeout(() => controller.abort(), timeoutMs);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (e: unknown) {
    if (timeoutId !== null) clearTimeout(timeoutId);
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
    if (timeoutId !== null) clearTimeout(timeoutId);
    if (externalSignal) {
      externalSignal.removeEventListener("abort", onExternalAbort);
    }
  }

  if (!res.ok) {
    // 尝试解析 JSON 错误响应；默认消息中性，避免中英文混用硬编码
    let errorMessage = `Request failed (${res.status})`;
    let errorCode: string | undefined;
    let responseText = "";
    try {
      responseText = (await res.text()).trim();
    } catch {
      // 响应状态已确定时，正文读取失败不应绕过统一错误封装。
    }
    if (responseText) {
      try {
        const errorData = JSON.parse(responseText);
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
        // 响应体只能读取一次；非 JSON 时直接使用已读取的文本。
        errorMessage = responseText;
      }
    }

    // 如果是认证失败 (401) 且请求携带了 token，清除 token 并跳转到登录页
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
  return res;
}

export async function request<T>(
  path: string,
  options: RequestInit = {},
  token?: string | null
): Promise<T> {
  const headers: Record<string, string> = {
    ...toRecord(options.headers),
    "Content-Type": "application/json",
  };
  const res = await fetchWithAuth(path, headers, options, token);
  if (res.status === 204) {
    return {} as T;
  }
  return res.json();
}

/**
 * 下载二进制响应（如头像、CSV 导出）。
 * 成功时返回 Blob 而非 JSON。
 */
export async function requestBlob(
  path: string,
  options: RequestInit = {},
  token?: string | null
): Promise<Blob> {
  const headers: Record<string, string> = {
    ...toRecord(options.headers),
  };
  const res = await fetchWithAuth(path, headers, options, token);
  return res.blob();
}

/**
 * 下载文本响应（如 JSON 导出、纯文本日志）。
 * 成功时返回纯文本，复用鉴权、超时与 401 跳转。
 */
export async function requestText(
  path: string,
  options: RequestInit = {},
  token?: string | null
): Promise<string> {
  const headers: Record<string, string> = {
    ...toRecord(options.headers),
  };
  const res = await fetchWithAuth(path, headers, options, token);
  return res.text();
}

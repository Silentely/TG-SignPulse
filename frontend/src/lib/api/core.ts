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

/**
 * 默认请求超时（毫秒）。
 * 语义：仅约束到 Response headers 到达（TTFB）；body 读取阶段不再受此计时器约束。
 * 长耗时请求可传 LONG_TIMEOUT_MS，或 null 关闭固定超时。
 */
export const DEFAULT_TIMEOUT_MS = 30_000;

/** 长任务（备份/大导出/配置导入导出）与服务端 WebDAV 读写上限对齐。 */
export const LONG_TIMEOUT_MS = 600_000;

/** 并发 401 时只跳转一次，避免头像批量拉取触发多次 location 赋值。 */
let authRedirectScheduled = false;

function redirectToLoginIfTokenMatches(token: string): void {
  if (typeof window === "undefined") return;
  if (authRedirectScheduled) return;
  const authStore = useAuthStore();
  if (authStore.token !== token) return;
  authRedirectScheduled = true;
  authStore.clearToken();
  window.location.href = "/";
}

/** 测试用：复位 401 跳转闸门。 */
export function resetAuthRedirectGateForTests(): void {
  authRedirectScheduled = false;
}

/**
 * 内部请求基元：鉴权 header、超时、abort 传播、!res.ok 错误解析与 401 跳转。
 * 成功时返回原始 Response，由调用方决定 JSON/Blob 解析方式。
 *
 * 超时语义：计时器在 headers 到达后清除；body 下载不受 DEFAULT/LONG 超时限制。
 * abort 语义：
 * - 超时触发 → NETWORK_TIMEOUT
 * - 调用方 signal 取消 → NETWORK_ABORTED
 * - 其他网络失败 → NETWORK_ERROR
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
  // 区分超时 abort 与外部取消，避免卸载/导航误报「请求超时」
  let abortedByTimeout = false;
  let abortedByExternal = false;
  const onExternalAbort = () => {
    abortedByExternal = true;
    controller.abort();
  };
  if (externalSignal) {
    if (externalSignal.aborted) {
      abortedByExternal = true;
      controller.abort();
    } else {
      externalSignal.addEventListener("abort", onExternalAbort, { once: true });
    }
  }
  const timeoutId =
    timeoutMs === null
      ? null
      : setTimeout(() => {
          abortedByTimeout = true;
          controller.abort();
        }, timeoutMs);

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
    let code = "NETWORK_ERROR";
    if (isAbort) {
      // 外部取消优先：即使两者同时触发，用户主动取消更贴近真实意图
      code = abortedByExternal
        ? "NETWORK_ABORTED"
        : abortedByTimeout
          ? "NETWORK_TIMEOUT"
          : "NETWORK_ABORTED";
    }
    const err = new Error(code) as ApiError;
    err.status = 0;
    err.code = code;
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
          } else if (
            typeof errorData.message === "string" &&
            errorData.message.trim()
          ) {
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

    // 认证失败 (401) 且请求携带了 token：闸门防抖，批量并发只跳转一次
    if (res.status === 401 && token) {
      redirectToLoginIfTokenMatches(token);
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
  token?: string | null,
  timeoutMs: number | null = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  const headers: Record<string, string> = {
    ...toRecord(options.headers),
    "Content-Type": "application/json",
  };
  const res = await fetchWithAuth(path, headers, options, token, timeoutMs);
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
  token?: string | null,
  timeoutMs: number | null = DEFAULT_TIMEOUT_MS,
): Promise<Blob> {
  const headers: Record<string, string> = {
    ...toRecord(options.headers),
  };
  const res = await fetchWithAuth(path, headers, options, token, timeoutMs);
  return res.blob();
}

/**
 * 下载文本响应（如 JSON 导出、纯文本日志）。
 * 成功时返回纯文本，复用鉴权、超时与 401 跳转。
 */
export async function requestText(
  path: string,
  options: RequestInit = {},
  token?: string | null,
  timeoutMs: number | null = DEFAULT_TIMEOUT_MS,
): Promise<string> {
  const headers: Record<string, string> = {
    ...toRecord(options.headers),
  };
  const res = await fetchWithAuth(path, headers, options, token, timeoutMs);
  return res.text();
}

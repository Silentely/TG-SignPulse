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
 * request / requestBlob / requestText：覆盖「发起到 body 读完」的整段墙钟时间。
 * 直接使用 fetchWithAuth 时：仅约束到 Response headers（TTFB），body 由调用方负责。
 */
export const DEFAULT_TIMEOUT_MS = 30_000;

/** 长任务（备份/大导出/配置导入导出）与服务端 WebDAV 读写上限对齐。 */
export const LONG_TIMEOUT_MS = 600_000;

/** 中等耗时接口（WebDAV 探测、设备保活、会话检测等）。 */
export const MEDIUM_TIMEOUT_MS = 120_000;

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

type AbortCode = "NETWORK_TIMEOUT" | "NETWORK_ABORTED" | "NETWORK_ERROR";
type AbortReason = "timeout" | "external";

/** 跨嵌套 AbortSignal 传播超时/取消原因（request 外层 → fetchWithAuth 内层） */
const abortReasonBySignal = new WeakMap<AbortSignal, AbortReason>();

function toNetworkError(
  e: unknown,
  abortedByTimeout: boolean,
  abortedByExternal: boolean,
): ApiError {
  const isAbort =
    (e instanceof DOMException && e.name === "AbortError") ||
    (e instanceof Error && e.name === "AbortError");
  let code: AbortCode = "NETWORK_ERROR";
  if (isAbort) {
    code = abortedByExternal
      ? "NETWORK_ABORTED"
      : abortedByTimeout
        ? "NETWORK_TIMEOUT"
        : "NETWORK_ABORTED";
  }
  const err = new Error(code) as ApiError;
  err.status = 0;
  err.code = code;
  return err;
}

/**
 * 组合外部 AbortSignal 与可选超时，返回统一 signal 与 cleanup。
 * 超时在 cleanup 前一直有效，可覆盖 headers + body 整段操作。
 */
export function createRequestAbort(
  timeoutMs: number | null,
  externalSignal?: AbortSignal | null,
): {
  signal: AbortSignal;
  cleanup: () => void;
  wasAbortedByTimeout: () => boolean;
  wasAbortedByExternal: () => boolean;
} {
  const controller = new AbortController();
  let abortedByTimeout = false;
  let abortedByExternal = false;

  const markAndAbort = (reason: AbortReason) => {
    if (reason === "timeout") abortedByTimeout = true;
    else abortedByExternal = true;
    abortReasonBySignal.set(controller.signal, reason);
    controller.abort();
  };

  const onExternalAbort = () => {
    // 若外层 signal 本身因超时 abort，继承 timeout，避免被误标为用户取消
    const parentReason = externalSignal
      ? abortReasonBySignal.get(externalSignal)
      : undefined;
    markAndAbort(parentReason === "timeout" ? "timeout" : "external");
  };
  if (externalSignal) {
    if (externalSignal.aborted) {
      const parentReason = abortReasonBySignal.get(externalSignal);
      markAndAbort(parentReason === "timeout" ? "timeout" : "external");
    } else {
      externalSignal.addEventListener("abort", onExternalAbort, { once: true });
    }
  }
  const timeoutId =
    timeoutMs === null
      ? null
      : setTimeout(() => {
          markAndAbort("timeout");
        }, timeoutMs);

  const cleanup = () => {
    if (timeoutId !== null) clearTimeout(timeoutId);
    if (externalSignal) {
      externalSignal.removeEventListener("abort", onExternalAbort);
    }
  };

  return {
    signal: controller.signal,
    cleanup,
    wasAbortedByTimeout: () => abortedByTimeout,
    wasAbortedByExternal: () => abortedByExternal,
  };
}

/**
 * 内部请求基元：鉴权 header、可选超时、abort 传播、!res.ok 错误解析与 401 跳转。
 * 成功时返回原始 Response，由调用方决定 JSON/Blob 解析方式。
 *
 * timeoutMs 语义（本函数内）：仅约束到 headers 到达；若需覆盖 body，
 * 请用 request/requestBlob/requestText，或自行 createRequestAbort + timeoutMs=null。
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

  const abort = createRequestAbort(timeoutMs, options.signal ?? null);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
      cache: "no-store",
      signal: abort.signal,
    });
  } catch (e: unknown) {
    abort.cleanup();
    throw toNetworkError(
      e,
      abort.wasAbortedByTimeout(),
      abort.wasAbortedByExternal(),
    );
  }
  // headers 已到达：TTFB 超时结束（body 由 request* 的外层超时继续管，或调用方自管）
  abort.cleanup();

  if (!res.ok) {
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
        errorMessage = responseText;
      }
    }

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

/**
 * 带整段墙钟超时的请求：headers + body 解析均在 timeoutMs 内。
 * 内部对 fetchWithAuth 关闭 TTFB 超时，改由外层 createRequestAbort 统一约束。
 */
async function requestWithTotalTimeout<T>(
  path: string,
  options: RequestInit,
  token: string | null | undefined,
  timeoutMs: number | null,
  parse: (res: Response) => Promise<T>,
  extraHeaders?: Record<string, string>,
): Promise<T> {
  const abort = createRequestAbort(timeoutMs, options.signal ?? null);
  const headers: Record<string, string> = {
    ...toRecord(options.headers),
    ...extraHeaders,
  };
  try {
    const res = await fetchWithAuth(
      path,
      headers,
      { ...options, signal: abort.signal },
      token,
      null,
    );
    return await parse(res);
  } catch (e: unknown) {
    // 外层总超时经 signal 传入 fetchWithAuth 时会被标成 NETWORK_ABORTED，
    // 这里按外层 flag 纠正为 TIMEOUT / ABORTED。
    if (abort.wasAbortedByTimeout()) {
      const err = new Error("NETWORK_TIMEOUT") as ApiError;
      err.status = 0;
      err.code = "NETWORK_TIMEOUT";
      throw err;
    }
    if (abort.wasAbortedByExternal()) {
      const err = new Error("NETWORK_ABORTED") as ApiError;
      err.status = 0;
      err.code = "NETWORK_ABORTED";
      throw err;
    }
    if (
      e &&
      typeof e === "object" &&
      "code" in e &&
      (e as ApiError).code &&
      String((e as ApiError).code).startsWith("NETWORK_")
    ) {
      throw e;
    }
    if (
      (e instanceof DOMException && e.name === "AbortError") ||
      (e instanceof Error && e.name === "AbortError")
    ) {
      throw toNetworkError(e, false, false);
    }
    throw e;
  } finally {
    abort.cleanup();
  }
}

export async function request<T>(
  path: string,
  options: RequestInit = {},
  token?: string | null,
  timeoutMs: number | null = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  return requestWithTotalTimeout(
    path,
    options,
    token,
    timeoutMs,
    async (res) => {
      if (res.status === 204) return {} as T;
      return res.json() as Promise<T>;
    },
    { "Content-Type": "application/json" },
  );
}

/**
 * 下载二进制响应（如头像、CSV 导出）。
 * 超时覆盖发起到 blob() 完成。
 */
export async function requestBlob(
  path: string,
  options: RequestInit = {},
  token?: string | null,
  timeoutMs: number | null = DEFAULT_TIMEOUT_MS,
): Promise<Blob> {
  return requestWithTotalTimeout(
    path,
    options,
    token,
    timeoutMs,
    (res) => res.blob(),
  );
}

/**
 * 下载文本响应（如 JSON 导出、纯文本日志）。
 * 超时覆盖发起到 text() 完成。
 */
export async function requestText(
  path: string,
  options: RequestInit = {},
  token?: string | null,
  timeoutMs: number | null = DEFAULT_TIMEOUT_MS,
): Promise<string> {
  return requestWithTotalTimeout(
    path,
    options,
    token,
    timeoutMs,
    (res) => res.text(),
  );
}

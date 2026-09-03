/**
 * 浏览器文件下载与网络错误归一化共享工具。
 *
 * - downloadBlob：收敛「createObjectURL + a.click + revokeObjectURL」样板。
 * - normalizeNetworkError：收敛「NETWORK_* 重抛 + AbortError 归一化」样板，
 *   供长请求（备份下载/WebDAV 下载）的 catch 分支复用。
 */
import { toNetworkError } from "./api/core";
import type { ApiError } from "./types";

/**
 * 触发浏览器下载 Blob 文件。
 * 统一先挂载到 document.body 再移除，保证 Firefox 等浏览器兼容；
 * revokeObjectURL 延迟到宏任务，避免部分浏览器在下载尚未开始时即回收对象 URL。
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || "download";
  a.style.display = "none";
  try {
    document.body.appendChild(a);
    a.click();
  } finally {
    if (a.parentNode) {
      a.parentNode.removeChild(a);
    }
    setTimeout(() => {
      try {
        URL.revokeObjectURL(url);
      } catch {
        /* ignore */
      }
    }, 1000);
  }
}

/**
 * 网络错误归一化（恒抛，返回类型为 never）：
 * 1. 已封装的 NETWORK_* 错误（ApiError.code 以 NETWORK_ 开头）原样重抛；
 * 2. AbortError 按 abort 原因归一化为 NETWORK_TIMEOUT / NETWORK_ABORTED；
 * 3. 其余错误原样重抛。
 *
 * @param abort 可选：请求 abort 元信息，用于区分超时与外部取消。
 */
export function normalizeNetworkError(
  e: unknown,
  abort?: { wasAbortedByTimeout(): boolean; wasAbortedByExternal(): boolean },
): never {
  if (
    e &&
    typeof e === "object" &&
    "code" in e &&
    String((e as ApiError).code || "").startsWith("NETWORK_")
  ) {
    throw e;
  }
  if (
    (e instanceof DOMException && e.name === "AbortError") ||
    (e instanceof Error && e.name === "AbortError")
  ) {
    throw toNetworkError(
      e,
      abort?.wasAbortedByTimeout() ?? false,
      abort?.wasAbortedByExternal() ?? false,
    );
  }
  throw e;
}

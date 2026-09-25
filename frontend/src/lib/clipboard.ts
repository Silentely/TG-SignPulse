/**
 * 安全剪贴板复制封装：
 * 优先调用 navigator.clipboard.writeText，在非 HTTPS 或不支持的环境降级为 textarea + execCommand。
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  const content = String(text ?? "")
  if (!content) return false

  if (typeof navigator !== "undefined" && navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
    try {
      await navigator.clipboard.writeText(content)
      return true
    } catch {
      // 降级尝试
    }
  }

  // 首选 readonly：聚焦时不唤起移动端键盘，避免布局跳动。
  // iOS Safari 无法程序化选中 readonly textarea 导致复制失败，故失败后用可写 textarea 重试。
  if (execCommandCopy(content, true)) return true
  return execCommandCopy(content, false)
}

/**
 * 隐藏 textarea + execCommand("copy") 复制。
 * readonly 变体不会唤起移动端键盘，但 iOS 上可能因无法选中而复制失败；
 * 可写变体兼容 iOS，代价是聚焦时可能短暂弹出键盘。
 */
function execCommandCopy(content: string, readonly: boolean): boolean {
  if (typeof document === "undefined") return false

  let textarea: HTMLTextAreaElement | null = null
  try {
    textarea = document.createElement("textarea")
    textarea.value = content
    if (readonly) textarea.setAttribute("readonly", "")
    textarea.style.position = "fixed"
    textarea.style.left = "-9999px"
    textarea.style.top = "-9999px"
    textarea.style.opacity = "0"
    document.body.appendChild(textarea)
    textarea.focus()
    textarea.select()
    textarea.setSelectionRange(0, textarea.value.length)
    return document.execCommand("copy")
  } catch {
    return false
  } finally {
    textarea?.remove()
  }
}
